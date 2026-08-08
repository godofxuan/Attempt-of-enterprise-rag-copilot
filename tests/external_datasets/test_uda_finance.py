from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

import app.external_datasets.uda_finance as uda_module
from app.external_datasets.uda_finance import (
    DEFAULT_PROTOCOL_PATH,
    UdaFinanceQaRow,
    extract_selected_pdfs,
    load_uda_finance_protocol,
    prepare_uda_finance,
    select_uda_finance_cases,
    selection_sha256,
    sha256_bytes,
    verify_uda_finance_preparation,
)


def _rows() -> list[UdaFinanceQaRow]:
    rows: list[UdaFinanceQaRow] = []
    for company_index in range(6):
        company = f"C{company_index}"
        year = 2010 + company_index
        doc_name = f"{company}_{year}"
        for question_index in range(4):
            rows.append(
                UdaFinanceQaRow(
                    doc_name=doc_name,
                    q_uid=(
                        f"{company}/{year}/page_{question_index + 1}.pdf-"
                        f"{question_index}"
                    ),
                    question=f"question {company_index} {question_index}",
                    answer_1="1",
                    answer_2="1.0",
                    company_id=company,
                    report_year=year,
                    page_number=question_index + 1,
                )
            )
    return rows


def test_selection_is_deterministic_company_disjoint_and_fixed_size() -> None:
    kwargs = {
        "seed": "uda-finance-test-seed",
        "minimum_questions_per_document": 4,
        "dev_company_count": 2,
        "test_company_count": 3,
        "cases_per_document": 3,
    }
    first = select_uda_finance_cases(_rows(), **kwargs)
    second = select_uda_finance_cases(list(reversed(_rows())), **kwargs)

    assert first == second
    assert selection_sha256(first) == selection_sha256(second)
    assert sum(item.split == "dev" for item in first) == 2
    assert sum(item.split == "test" for item in first) == 3
    assert len({item.company_id for item in first}) == 5
    assert all(len(item.q_uids) == 3 for item in first)


def test_selection_rejects_an_underpowered_population() -> None:
    with pytest.raises(ValueError, match="too few eligible companies"):
        select_uda_finance_cases(
            _rows(),
            seed="seed",
            minimum_questions_per_document=5,
            dev_company_count=2,
            test_company_count=3,
            cases_per_document=3,
        )


def test_row_requires_one_answer_but_not_both() -> None:
    row = _rows()[0].model_copy(update={"answer_2": ""})
    assert UdaFinanceQaRow.model_validate(row.model_dump()).answer_1 == "1"
    with pytest.raises(ValueError, match="at least one answer"):
        UdaFinanceQaRow.model_validate(
            row.model_copy(update={"answer_1": ""}).model_dump()
        )


def test_selected_pdf_extraction_is_exact_and_non_overwriting(tmp_path: Path) -> None:
    archive = tmp_path / "docs.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("fin_docs/A_2020.pdf", b"%PDF-a")
        output.writestr("fin_docs/B_2021.pdf", b"%PDF-b")
        output.writestr("fin_docs/unselected.pdf", b"%PDF-c")
    destination = tmp_path / "selected"

    extracted = extract_selected_pdfs(
        archive,
        destination,
        ["A_2020", "B_2021"],
    )

    assert set(extracted) == {"A_2020", "B_2021"}
    assert sorted(path.name for path in destination.iterdir()) == [
        "A_2020.pdf",
        "B_2021.pdf",
    ]
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        extract_selected_pdfs(archive, destination, ["A_2020"])


def test_selected_pdf_extraction_rejects_zip_slip(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../A_2020.pdf", b"%PDF-a")

    with pytest.raises(ValueError, match="unsafe path"):
        extract_selected_pdfs(archive, tmp_path / "out", ["A_2020"])


def test_committed_protocol_is_strict_and_frozen() -> None:
    protocol, protocol_sha256 = load_uda_finance_protocol(DEFAULT_PROTOCOL_PATH)

    assert protocol.dev_case_count == 64
    assert protocol.test_case_count == 96
    assert protocol.test_execution_limit == 1
    assert protocol.selection_sha256 == (
        "cf167cfa4603f6d0877650721b73aec952c5ec4e8ed6d461d4eed33c401b1e4e"
    )
    assert len(protocol_sha256) == 64


def test_prepare_and_verify_builds_a_hash_bound_private_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qa_path = tmp_path / "fin_qa.csv"
    lines = ["doc_name|q_uid|question|answer_1|answer_2"]
    for company, year in (("A", 2020), ("B", 2021)):
        for index in range(2):
            lines.append(
                f"{company}_{year}|{company}/{year}/page_{index + 1}.pdf-{index}|"
                f"question {company} {index}|1|"
            )
    qa_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    qa_hash = sha256_bytes(qa_path.read_bytes())
    monkeypatch.setattr(uda_module, "UDA_FIN_QA_SHA256", qa_hash)
    rows = uda_module.load_uda_finance_rows(qa_path)
    selections = select_uda_finance_cases(
        rows,
        seed="uda-fixture-00000001",
        minimum_questions_per_document=2,
        dev_company_count=1,
        test_company_count=1,
        cases_per_document=2,
    )
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(
        json.dumps(
            {
                "schema_version": "uda_finance_page_protocol_v1",
                "dataset": "UDA-QA/FinHybrid",
                "repository": uda_module.UDA_REPOSITORY,
                "repository_revision": uda_module.UDA_REVISION,
                "huggingface_repository": uda_module.UDA_HF_REPOSITORY,
                "huggingface_revision": uda_module.UDA_HF_REVISION,
                "license": uda_module.UDA_LICENSE,
                "qa_sha256": qa_hash,
                "selection_seed": "uda-fixture-00000001",
                "minimum_questions_per_document": 2,
                "dev_company_count": 1,
                "test_company_count": 1,
                "cases_per_document": 2,
                "selection_sha256": selection_sha256(selections),
                "dev_case_count": 2,
                "test_case_count": 2,
                "retrieval_arms": ["bm25", "dense", "hybrid_rrf"],
                "selection_metric": "page_ndcg_at_5",
                "tie_break_metrics": ["page_hit_at_5", "latency_ms_p95"],
                "test_execution_limit": 1,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    pdf_root = tmp_path / "pdfs"
    pdf_root.mkdir()
    for name in ("A_2020", "B_2021"):
        (pdf_root / f"{name}.pdf").write_bytes(b"%PDF-1.4 fixture")
    source_root = tmp_path / "corpus"
    prepared_root = tmp_path / "prepared"

    manifest = prepare_uda_finance(
        qa_path=qa_path,
        pdf_root=pdf_root,
        source_root=source_root,
        prepared_root=prepared_root,
        protocol_path=protocol_path,
    )

    assert manifest.document_count == 2
    assert manifest.dev_case_count == 2
    assert manifest.test_case_count == 2
    assert verify_uda_finance_preparation(
        source_root=source_root, prepared_root=prepared_root
    ) == manifest
