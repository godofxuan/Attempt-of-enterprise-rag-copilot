from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.documents import SourceLocator
from app.domain.queries import SearchHit
from app.evaluation.page_retrieval import PageReference, score_page_retrieval
from app.external_datasets.uda_finance import UdaFinanceQaRow
from app.external_datasets.uda_finance_page_eval import UdaFinancePageCaseResult
from app.external_datasets.uda_finance_r5 import (
    R5_PROTOCOL_PATH,
    load_uda_finance_r5_protocol,
    select_uda_finance_r5_cases,
    selection_sha256,
)
from app.external_datasets.uda_finance_r5_eval import analyze_company_cluster_pairs


def _rows() -> list[UdaFinanceQaRow]:
    rows: list[UdaFinanceQaRow] = []
    for company, counts in (("A", (2, 4)), ("B", (3,)), ("C", (2,))):
        for year_offset, count in enumerate(counts):
            year = 2020 + year_offset
            for item in range(count):
                rows.append(
                    UdaFinanceQaRow(
                        doc_name=f"{company}_{year}",
                        q_uid=f"{company}/{year}/page_{item + 1}.pdf-{item}",
                        question=f"question {company} {year} {item}",
                        answer_1="answer",
                        company_id=company,
                        report_year=year,
                        page_number=item + 1,
                    )
                )
    return rows


def _result(case_id: str, doc_id: str, *, hit: bool) -> UdaFinancePageCaseResult:
    hits = []
    if hit:
        hits.append(
            SearchHit(
                index_run_id="r5-index",
                chunk_id=f"chunk-{case_id}",
                doc_id=doc_id,
                policy_id=doc_id,
                source_path="documents/report.pdf",
                section_path=["Page 1"],
                locator=SourceLocator(kind="page", start=1, end=1),
                matched_text="evidence",
                context_text="evidence",
                tenant_id="uda-external",
                region="global",
                acl_groups=["uda-evaluator"],
                version_id=f"{doc_id}-v1",
                version="1",
                status="active",
                authority_level=90,
                variant="authoritative",
                fused_score=1.0,
            )
        )
    return UdaFinancePageCaseResult(
        case_id=case_id,
        gold_doc_id=doc_id,
        gold_page_number=1,
        score=score_page_retrieval(
            case_id=case_id,
            hits=hits,
            gold_pages=[PageReference(doc_id=doc_id, page_number=1)],
        ),
        latency_ms=1.0,
    )


def test_r5_selection_excludes_consumed_companies_and_uses_most_populated_report() -> None:
    selections = select_uda_finance_r5_cases(
        _rows(),
        excluded_company_ids=["C"],
        seed="r5-fresh-selection-test",
        minimum_questions_per_document=2,
        company_count=2,
        max_cases_per_document=3,
    )

    assert {item.company_id for item in selections} == {"A", "B"}
    selected_a = next(item for item in selections if item.company_id == "A")
    assert selected_a.doc_name == "A_2021"
    assert len(selected_a.q_uids) == 3
    assert len(selection_sha256(selections)) == 64


def test_r5_cluster_analysis_counts_rescues_and_companies() -> None:
    baseline = [
        _result("a-1", "doc-a", hit=False),
        _result("a-2", "doc-a", hit=False),
        _result("b-1", "doc-b", hit=True),
        _result("c-1", "doc-c", hit=True),
    ]
    candidate = [
        _result("a-1", "doc-a", hit=True),
        _result("a-2", "doc-a", hit=True),
        _result("b-1", "doc-b", hit=True),
        _result("c-1", "doc-c", hit=False),
    ]

    outcomes, macro, hit_interval, ndcg_interval = analyze_company_cluster_pairs(
        baseline,
        candidate,
        bootstrap_seed=9,
        bootstrap_iterations=10_000,
    )

    assert outcomes.candidate_only_hit == 2
    assert outcomes.baseline_only_hit == 1
    assert macro.company_count == 3
    assert hit_interval.estimate == pytest.approx(0.25)
    assert ndcg_interval.estimate == pytest.approx(0.25)


def test_r5_protocol_freezes_fresh_population_candidate_and_gates() -> None:
    protocol, digest = load_uda_finance_r5_protocol()

    assert len(digest) == 64
    assert protocol.excluded_company_count == 96
    assert protocol.company_count == 41
    assert protocol.case_count == 192
    assert protocol.candidate_id == "dense_dual_bm25_shared_scope_page_rrf_v3"
    assert protocol.require_hit_bootstrap_lower_bound_positive is True
    assert protocol.require_ndcg_bootstrap_lower_bound_positive is True
    assert protocol.max_p95_latency_multiplier == 1.15
    assert protocol.execution_limit == 1


def test_r5_public_protocol_does_not_disclose_selected_content() -> None:
    payload = json.loads(Path(R5_PROTOCOL_PATH).read_text(encoding="utf-8"))

    assert "company_ids" not in payload
    assert "questions" not in payload
    assert "answers" not in payload
    assert "document_ids" not in payload
