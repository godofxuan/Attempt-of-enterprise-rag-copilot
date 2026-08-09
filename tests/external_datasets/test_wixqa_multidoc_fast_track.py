from __future__ import annotations

from pathlib import Path

from app.external_datasets.wixqa_multidoc_fast_track import (
    score_arm_case,
    summarize_arm,
)
from scripts.build_wixqa_multidoc_dev_cohort import build_cohort
from scripts.publish_wixqa_multidoc_fast_track import build_public_evidence


ROOT = Path(__file__).resolve().parents[2]


def test_multidoc_cohort_is_hash_bound_and_explicitly_retrospective() -> None:
    payload = build_cohort()

    assert payload["question_count"] == 27
    assert payload["consumption"] == (
        "RETROSPECTIVE_DEVELOPMENT_ONLY_ALREADY_OBSERVED"
    )
    assert all(
        item["required_source_count"] >= 2 for item in payload["records"]
    )
    assert payload == __import__("json").loads(
        (
            ROOT
            / "docs"
            / "rapid_upgrade"
            / "evidence"
            / "MULTIDOC_DEV_COHORT.json"
        ).read_text(encoding="utf-8")
    )


def test_fast_track_scores_evidence_and_citations_separately() -> None:
    trace = {
        "budget": {"search_calls": 1, "open_calls": 0, "find_calls": 0},
        "steps": [
            {"tool": "search", "status": "ok", "error_code": None},
            {"tool": "answer", "status": "terminal", "error_code": None},
        ],
        "stop_reason": "completed",
    }
    case = score_arm_case(
        question_id="case-1",
        arm="candidate",
        gold_source_ids=["a", "b"],
        retrieved_source_ids=["a", "b", "c"],
        accepted_source_ids=["a", "b"],
        cited_source_ids=["a"],
        trace=trace,
        latency_ms=12,
    )

    assert case.retrieval_complete == 1
    assert case.required_evidence_complete == 1
    assert case.citation_complete == 0
    assert case.citation_precision == 1
    assert case.citation_recall == 0.5
    summary = summarize_arm([case], arm="candidate")
    assert summary.required_evidence_completeness == 1
    assert summary.tool_error_count == 0
    assert summary.generation_tokens == 0


def test_publication_preserves_retrospective_and_resume_boundaries() -> None:
    run = {
        "mode": "RETROSPECTIVE_DEVELOPMENT_ONLY_ALREADY_OBSERVED",
        "promotion_status": "HOLD_NO_UNCONSUMED_VALIDATION",
        "claim_boundary": {"resume_quality_claim_allowed": False},
        "code_revision": "a" * 40,
        "dataset_manifest_sha256": "b" * 64,
        "cohort_sha256": "c" * 64,
        "index_run_id": "index-1",
        "index_manifest_sha256": "d" * 64,
        "embedding_model": "bge-m3",
        "embedding_model_sha256": "e" * 64,
        "agent_budget": {},
        "same_retriever_across_arms": True,
        "same_guard_acl_across_agent_arms": True,
        "retrieval_baseline": {},
        "arm_summaries": {},
        "candidate_vs_current": {},
        "registered_gates": {},
        "registered_gate_status": "PASS",
        "precision_tradeoff_status": "REVIEW_REQUIRED",
    }

    payload = build_public_evidence(run, private_summary_sha256="f" * 64)

    assert payload["promotion_status"] == "HOLD_NO_UNCONSUMED_VALIDATION"
    assert payload["claim_boundary"]["resume_quality_claim_allowed"] is False
