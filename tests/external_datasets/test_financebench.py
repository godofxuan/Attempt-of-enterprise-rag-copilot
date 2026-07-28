import hashlib
import json
from pathlib import Path

from app.corpus.schemas import CorpusManifest, EvalCase
from app.external_datasets.financebench import (
    FinanceBenchPreparedCase,
    build_financebench_entity_catalog,
    prepare_financebench,
    verify_financebench_preparation,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _question(case_id: str, company: str, doc_name: str) -> dict:
    return {
        "financebench_id": case_id,
        "company": company,
        "doc_name": doc_name,
        "question_type": "metrics-generated",
        "question_reasoning": "Information extraction",
        "domain_question_num": None,
        "question": f"What is the metric for {company}?",
        "answer": "$1.00",
        "justification": "The value is present in the filing.",
        "dataset_subset_label": "OPEN_SOURCE",
        "evidence": [
            {
                "evidence_text": "Metric $1.00",
                "doc_name": doc_name,
                "evidence_page_num": 2,
                "evidence_text_full_page": "Metric $1.00 on the page.",
            }
        ],
    }


def _metadata(company: str, doc_name: str, period: int) -> dict:
    return {
        "doc_name": doc_name,
        "company": company,
        "gics_sector": "Industrials",
        "doc_type": "10k",
        "doc_period": period,
        "doc_link": f"https://example.invalid/{doc_name}.pdf",
    }


def _fixture(source_root: Path) -> None:
    questions = [
        _question("fb-1", "Alpha", "ALPHA_2022_10K"),
        _question("fb-2", "Alpha", "ALPHA_2022_10K"),
        _question("fb-3", "Beta", "BETA_2022_10K"),
        _question("fb-4", "Gamma", "GAMMA_2022_10K"),
    ]
    metadata = [
        _metadata("Alpha", "ALPHA_2022_10K", 2022),
        _metadata("Beta", "BETA_2022_10K", 2022),
        _metadata("Gamma", "GAMMA_2022_10K", 2022),
    ]
    _write_jsonl(
        source_root / "data" / "financebench_open_source.jsonl",
        questions,
    )
    _write_jsonl(
        source_root / "data" / "financebench_document_information.jsonl",
        metadata,
    )
    for item in metadata:
        path = source_root / "pdfs" / f"{item['doc_name']}.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4\nfixture\n")


def test_prepare_financebench_emits_compatible_corpus_and_frozen_splits(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    prepared_root = tmp_path / "prepared"
    _fixture(source_root)

    result = prepare_financebench(
        source_root,
        prepared_root,
        split_seed=17,
        verify_pinned_hashes=False,
    )

    corpus = CorpusManifest.model_validate_json(
        (source_root / "manifest.json").read_bytes()
    )
    dev = [
        EvalCase.model_validate(item)
        for item in json.loads((prepared_root / "eval" / "dev.json").read_text())
    ]
    test_bytes = (prepared_root / "eval" / "test.json").read_bytes()
    test = [
        EvalCase.model_validate(item)
        for item in json.loads(test_bytes.decode("utf-8"))
    ]
    test_evidence = [
        FinanceBenchPreparedCase.model_validate(item)
        for item in json.loads(
            (prepared_root / "eval" / "test_evidence.json").read_text()
        )
    ]

    assert corpus.document_count == 3
    assert {item.format for item in corpus.documents} == {"pdf"}
    assert {item.source_type for item in corpus.documents} == {"filing"}
    assert {item.case_id for item in dev}.isdisjoint(
        {item.case_id for item in test}
    )
    company_by_case = {
        "fb-1": "Alpha",
        "fb-2": "Alpha",
        "fb-3": "Beta",
        "fb-4": "Gamma",
    }
    assert {company_by_case[item.case_id] for item in dev}.isdisjoint(
        {company_by_case[item.case_id] for item in test}
    )
    assert test_evidence
    assert test_evidence[0].evidence[0].page_number == 3
    assert result.manifest.test_sha256 == hashlib.sha256(test_bytes).hexdigest()
    assert verify_financebench_preparation(
        source_root,
        prepared_root,
    ) == result.manifest
    catalog = build_financebench_entity_catalog(
        source_root,
        verify_pinned_hashes=False,
    )
    resolution = catalog.resolve("What is Alpha's FY2022 metric?")
    assert resolution is not None
    assert resolution.entity_ids == ["alpha"]
    assert resolution.policy_ids == ["financebench-filing::alpha-2022-10k"]


def test_prepare_financebench_rejects_missing_referenced_pdf(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    prepared_root = tmp_path / "prepared"
    _fixture(source_root)
    (source_root / "pdfs" / "BETA_2022_10K.pdf").unlink()

    try:
        prepare_financebench(
            source_root,
            prepared_root,
            verify_pinned_hashes=False,
        )
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("missing FinanceBench PDF was accepted")
