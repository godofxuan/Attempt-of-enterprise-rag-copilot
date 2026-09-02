from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.domain.documents import SourceLocator
from app.domain.queries import SearchHit
from app.evaluation.page_retrieval import PageReference, score_page_retrieval
from app.external_datasets.uda_finance_page_eval import UdaFinancePageCaseResult
from app.external_datasets.uda_finance_r4_canary import (
    analyze_r4_pairs,
    verify_r4_canary_evidence,
)


def _row(case_id: str, *, gold_page: int, retrieved_page: int | None) -> UdaFinancePageCaseResult:
    hits = []
    if retrieved_page is not None:
        hits.append(
            SearchHit(
                index_run_id="index-r4",
                chunk_id=f"chunk-{case_id}",
                doc_id="doc-1",
                policy_id="doc-1",
                source_path="documents/report.pdf",
                section_path=[f"Page {retrieved_page}"],
                locator=SourceLocator(kind="page", start=retrieved_page, end=retrieved_page),
                matched_text="evidence",
                context_text="evidence",
                tenant_id="uda-external",
                region="global",
                acl_groups=["uda-evaluator"],
                version_id="doc-1-v1",
                version="1",
                status="active",
                authority_level=90,
                variant="authoritative",
                fused_score=1.0,
            )
        )
    return UdaFinancePageCaseResult(
        case_id=case_id,
        gold_doc_id="doc-1",
        gold_page_number=gold_page,
        score=score_page_retrieval(
            case_id=case_id,
            hits=hits,
            gold_pages=[PageReference(doc_id="doc-1", page_number=gold_page)],
        ),
        latency_ms=1.0,
    )


def test_paired_analysis_distinguishes_rescues_from_regressions() -> None:
    baseline = [
        _row("same-hit", gold_page=1, retrieved_page=1),
        _row("rescued", gold_page=2, retrieved_page=None),
        _row("regressed", gold_page=3, retrieved_page=3),
        _row("same-miss", gold_page=4, retrieved_page=None),
        _row("rescued-2", gold_page=5, retrieved_page=None),
    ]
    candidate = [
        _row("same-hit", gold_page=1, retrieved_page=1),
        _row("rescued", gold_page=2, retrieved_page=2),
        _row("regressed", gold_page=3, retrieved_page=None),
        _row("same-miss", gold_page=4, retrieved_page=None),
        _row("rescued-2", gold_page=5, retrieved_page=5),
    ]

    outcomes, hit_interval, ndcg_interval = analyze_r4_pairs(
        baseline,
        candidate,
        bootstrap_seed=7,
        bootstrap_iterations=1_000,
    )

    assert outcomes.candidate_only_hit == 2
    assert outcomes.baseline_only_hit == 1
    assert outcomes.baseline_misses == 3
    assert outcomes.candidate_misses == 2
    assert outcomes.relative_miss_reduction == pytest.approx(1 / 3)
    assert outcomes.exact_mcnemar_two_sided_p == 1.0
    assert hit_interval.estimate == pytest.approx(0.2)
    assert ndcg_interval.estimate == pytest.approx(0.2)


def test_paired_analysis_rejects_case_mismatch() -> None:
    with pytest.raises(ValueError, match="case IDs"):
        analyze_r4_pairs(
            [_row("baseline", gold_page=1, retrieved_page=1)],
            [_row("candidate", gold_page=1, retrieved_page=1)],
            bootstrap_iterations=1_000,
        )


def test_checked_in_canary_evidence_preserves_original_rejection() -> None:
    source_path = Path("docs/r4/evidence/uda_finance_r4_public_v1.json")
    evidence = verify_r4_canary_evidence(
        Path("docs/r4/evidence/uda_finance_r4_canary_review_v1.json"),
        source_public_evidence_path=source_path,
    )

    assert (
        evidence.source_public_evidence_sha256
        == hashlib.sha256(source_path.read_bytes()).hexdigest()
    )
    assert evidence.original_gate_decision == "VALIDATION_REJECTED_TEST_FORBIDDEN"
    assert evidence.promotion_decision == "LIMITED_CANARY_APPROVED"
    assert evidence.activation == "EXPLICIT_OPT_IN_ONLY"
    assert evidence.page_hit_at_5_delta.lower_95 < 0
    assert evidence.page_ndcg_at_5_delta.lower_95 > 0
