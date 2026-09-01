from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.external_datasets.uda_finance import UdaFinanceQaRow
from app.external_datasets.uda_finance_r4 import (
    R4_PROTOCOL_PATH,
    UdaFinanceR4PreparedCase,
    load_uda_finance_r4_protocol,
    r4_selection_sha256,
    select_uda_finance_r4_cases,
)


def _rows() -> list[UdaFinanceQaRow]:
    rows: list[UdaFinanceQaRow] = []
    for company in ("A", "B", "C"):
        for item in range(2):
            rows.append(
                UdaFinanceQaRow(
                    doc_name=f"{company}_2020",
                    q_uid=f"{company}/2020/page_{item + 1}.pdf-{item}",
                    question=f"question {company} {item}",
                    answer_1="answer",
                    company_id=company,
                    report_year=2020,
                    page_number=item + 1,
                )
            )
    return rows


def test_r4_selection_is_company_document_and_question_disjoint() -> None:
    selections = select_uda_finance_r4_cases(
        _rows(),
        reserve_company_ids=["A", "B", "C"],
        seed="r4-test-selection-seed",
        minimum_questions_per_document=2,
        cases_per_document=2,
        dev_company_count=1,
        validation_company_count=1,
        test_company_count=1,
    )

    assert {item.split for item in selections} == {"dev", "validation", "test"}
    assert len({item.company_id for item in selections}) == 3
    assert len({item.doc_name for item in selections}) == 3
    assert len({q_uid for item in selections for q_uid in item.q_uids}) == 6
    assert len(r4_selection_sha256(selections)) == 64


def test_r4_selection_rejects_incomplete_reserve() -> None:
    with pytest.raises(ValueError, match="fully eligible"):
        select_uda_finance_r4_cases(
            _rows(),
            reserve_company_ids=["A", "missing"],
            seed="r4-test-selection-seed",
            minimum_questions_per_document=2,
            cases_per_document=2,
            dev_company_count=1,
            validation_company_count=0,
            test_company_count=1,
        )


def test_r4_protocol_freezes_population_candidate_and_gates() -> None:
    protocol, digest = load_uda_finance_r4_protocol()

    assert len(digest) == 64
    assert protocol.predecessor_reserve_company_count == 28
    assert protocol.dev_case_count == 96
    assert protocol.validation_case_count == protocol.test_case_count == 64
    assert protocol.candidate_id == "dense_focused_bm25_page_rrf_v1"
    assert protocol.baseline_candidate_k == 40
    assert protocol.baseline_max_chunks_per_doc == 5
    assert protocol.lexical_weight == 0.5
    assert protocol.min_page_hit_at_5_delta == 0.05
    assert protocol.min_page_ndcg_at_5_delta == 0.03
    assert protocol.test_execution_limit == 1


def test_r4_protocol_does_not_publish_company_or_question_content() -> None:
    payload = json.loads(Path(R4_PROTOCOL_PATH).read_text(encoding="utf-8"))

    assert "company_ids" not in payload
    assert "questions" not in payload
    assert "answers" not in payload


def test_r4_case_schema_requires_page_locator() -> None:
    with pytest.raises(ValueError):
        UdaFinanceR4PreparedCase(
            case_id="r4-case",
            split="test",
            company_id="A",
            doc_name="A_2020",
            q_uid="A/2020/page_1.pdf-1",
            question="question",
            answers=["answer"],
            gold_doc_id="uda-fin-a-2020",
            page_number=0,
        )
