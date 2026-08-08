from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.external_datasets.uda_finance as uda_v1
import app.external_datasets.uda_finance_r3 as uda_r3
from app.external_datasets.uda_finance import UdaFinanceQaRow
from scripts.build_uda_finance_index import build_parser as build_index_parser


def _rows() -> list[UdaFinanceQaRow]:
    rows: list[UdaFinanceQaRow] = []
    for company_index in range(10):
        company = f"C{company_index}"
        year = 2010 + company_index
        for question_index in range(4):
            rows.append(
                UdaFinanceQaRow(
                    doc_name=f"{company}_{year}",
                    q_uid=f"{company}/{year}/page_{question_index + 1}.pdf-{question_index}",
                    question=f"question {company_index} {question_index}",
                    answer_1="1",
                    company_id=company,
                    report_year=year,
                    page_number=question_index + 1,
                )
            )
    return rows


def test_r3_selection_excludes_consumed_companies_and_is_order_invariant() -> None:
    kwargs = {
        "seed": "r3-selection-fixture",
        "excluded_company_ids": ["C0", "C1"],
        "minimum_questions_per_document": 4,
        "cases_per_document": 3,
        "dev_company_count": 2,
        "validation_company_count": 2,
        "test_company_count": 2,
    }
    first, first_reserve = uda_r3.select_uda_finance_r3_cases(_rows(), **kwargs)
    second, second_reserve = uda_r3.select_uda_finance_r3_cases(list(reversed(_rows())), **kwargs)

    assert first == second
    assert first_reserve == second_reserve
    assert len(first_reserve) == 2
    assert {item.company_id for item in first}.isdisjoint({"C0", "C1"})
    assert [sum(item.split == split for item in first) for split in ("dev", "validation", "test")] == [2, 2, 2]
    assert len({item.company_id for item in first}) == 6
    assert len({q_uid for item in first for q_uid in item.q_uids}) == 18


def test_r3_protocol_rejects_unsorted_exclusions() -> None:
    payload = {
        "schema_version": "uda_finance_r3_protocol_v1",
        "baseline_revision": uda_r3.R3_BASE_REVISION,
        "dataset": "UDA-QA/FinHybrid",
        "repository": uda_v1.UDA_REPOSITORY,
        "repository_revision": uda_v1.UDA_REVISION,
        "huggingface_repository": uda_v1.UDA_HF_REPOSITORY,
        "huggingface_revision": uda_v1.UDA_HF_REVISION,
        "license": uda_v1.UDA_LICENSE,
        "qa_sha256": uda_v1.UDA_FIN_QA_SHA256,
        "selection_seed": "fixture-seed-00000001",
        "excluded_company_ids": [f"C{x:02d}" for x in range(19)] + ["C00"],
        "minimum_questions_per_document": 2,
        "cases_per_document": 2,
        "dev_company_count": 1,
        "validation_company_count": 1,
        "test_company_count": 1,
        "dev_case_count": 2,
        "validation_case_count": 2,
        "test_case_count": 2,
        "selection_sha256": "a" * 64,
        "reserve_company_count": 1,
        "reserve_company_ids_sha256": "b" * 64,
        "validation_execution_limit": 1,
        "test_execution_limit": 1,
    }
    with pytest.raises(ValueError, match="sorted and unique"):
        uda_r3.UdaFinanceR3Protocol.model_validate(payload)


def test_index_builder_requires_explicit_r3_contract() -> None:
    parser = build_index_parser()

    assert parser.parse_args([]).dataset_contract == "v1"
    assert parser.parse_args(["--dataset-contract", "r3"]).dataset_contract == "r3"


def test_committed_r3_protocol_recomputes_selection() -> None:
    protocol, protocol_sha = uda_r3.load_uda_finance_r3_protocol()
    qa_path = Path(".private/external/uda-benchmark-src/dataset/qa/fin_qa.csv")
    if not qa_path.is_file():
        pytest.skip("pinned private UDA QA file is not available")
    rows = uda_v1.load_uda_finance_rows(qa_path)
    selections, reserve = uda_r3.verify_r3_protocol_selection(protocol, rows)

    assert len(protocol_sha) == 64
    assert len(selections) == 48
    assert len(reserve) == 28
    assert {item.company_id for item in selections}.isdisjoint(protocol.excluded_company_ids)
    assert sum(item.split == "dev" for item in selections) == 24
    assert sum(item.split == "validation" for item in selections) == 12
    assert sum(item.split == "test" for item in selections) == 12


def test_r3_prepare_and_verify_private_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    qa_path = tmp_path / "fin_qa.csv"
    lines = ["doc_name|q_uid|question|answer_1|answer_2"]
    for company, year in (("A", 2020), ("B", 2021), ("C", 2022), ("D", 2023)):
        for index in range(2):
            lines.append(f"{company}_{year}|{company}/{year}/page_{index + 1}.pdf-{index}|q|1|")
    qa_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    qa_hash = uda_v1.sha256_bytes(qa_path.read_bytes())
    monkeypatch.setattr(uda_v1, "UDA_FIN_QA_SHA256", qa_hash)
    monkeypatch.setattr(uda_r3, "UDA_FIN_QA_SHA256", qa_hash)
    rows = uda_v1.load_uda_finance_rows(qa_path)
    selections, reserve = uda_r3.select_uda_finance_r3_cases(
        rows,
        seed="fixture-r3-00000001",
        excluded_company_ids=[],
        minimum_questions_per_document=2,
        cases_per_document=2,
        dev_company_count=1,
        validation_company_count=1,
        test_company_count=1,
    )
    protocol = {
        "schema_version": "uda_finance_r3_protocol_v1",
        "baseline_revision": uda_r3.R3_BASE_REVISION,
        "dataset": "UDA-QA/FinHybrid",
        "repository": uda_v1.UDA_REPOSITORY,
        "repository_revision": uda_v1.UDA_REVISION,
        "huggingface_repository": uda_v1.UDA_HF_REPOSITORY,
        "huggingface_revision": uda_v1.UDA_HF_REVISION,
        "license": uda_v1.UDA_LICENSE,
        "qa_sha256": qa_hash,
        "selection_seed": "fixture-r3-00000001",
        "excluded_company_ids": [f"X{x:02d}" for x in range(20)],
        "minimum_questions_per_document": 2,
        "cases_per_document": 2,
        "dev_company_count": 1,
        "validation_company_count": 1,
        "test_company_count": 1,
        "dev_case_count": 2,
        "validation_case_count": 2,
        "test_case_count": 2,
        "selection_sha256": uda_r3.r3_selection_sha256(selections),
        "reserve_company_count": len(reserve),
        "reserve_company_ids_sha256": uda_r3.reserve_company_ids_sha256(reserve),
        "validation_execution_limit": 1,
        "test_execution_limit": 1,
    }
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
    pdf_root = tmp_path / "pdfs"
    pdf_root.mkdir()
    for item in selections:
        (pdf_root / f"{item.doc_name}.pdf").write_bytes(b"%PDF-1.4 fixture")
    source_root = tmp_path / "corpus"
    prepared_root = tmp_path / "prepared"

    manifest = uda_r3.prepare_uda_finance_r3(
        qa_path=qa_path,
        pdf_root=pdf_root,
        source_root=source_root,
        prepared_root=prepared_root,
        protocol_path=protocol_path,
    )

    assert manifest.document_count == 3
    assert manifest.split_case_counts == {"dev": 2, "validation": 2, "test": 2}
    assert uda_r3.verify_uda_finance_r3_preparation(
        source_root=source_root, prepared_root=prepared_root
    ) == manifest
