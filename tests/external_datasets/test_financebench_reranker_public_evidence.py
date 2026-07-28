import json
import re
from pathlib import Path


EVIDENCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "external_datasets"
    / "evidence"
    / "financebench_dev_page_reranker_v2.json"
)


def test_financebench_reranker_public_evidence_keeps_claim_boundaries() -> None:
    payload = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))

    assert (
        payload["schema_version"]
        == "financebench_dev_page_reranker_public_evidence_v1"
    )
    boundaries = payload["boundaries"]
    assert boundaries["answer_accuracy"] == "NOT_RUN"
    assert boundaries["frozen_test_v1_reused_for_v2_tuning"] is False
    assert boundaries["promotion_status"] == (
        "NEW_INDEPENDENT_HOLDOUT_REQUIRED"
    )
    assert boundaries["threshold_selected_on"] == "financebench_dev_49"
    assert payload["dataset"]["case_count"] == 49
    assert payload["artifacts"]["private_artifacts_committed"] is False


def test_financebench_reranker_public_evidence_records_pareto_tradeoff() -> None:
    payload = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    runs = {item["variant"]: item for item in payload["runs"]}
    baseline = runs["dense_top_document_10_candidate_baseline"]
    full = runs["full_qwen3_reranking_with_dense_top1_preserved"]
    small = runs["small_model_negative_control"]
    gated = runs["development_candidate_confidence_gated_qwen3"]

    assert gated["reranker_case_count"] == 13
    assert full["reranker_case_count"] == 49
    assert gated["generation_calls"] < full["generation_calls"]
    assert gated["page_hit_at_5"] > baseline["page_hit_at_5"]
    assert gated["macro_page_recall_at_5"] > baseline[
        "macro_page_recall_at_5"
    ]
    assert gated["latency_ms_p95"] < full["latency_ms_p95"]
    assert small["page_hit_at_5"] < baseline["page_hit_at_5"]
    assert small["structured_output_retry_count"] == 8


def test_financebench_reranker_public_evidence_uses_content_free_hashes() -> None:
    payload = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=True)

    assert "D:\\\\" not in serialized
    assert re.fullmatch(
        r"[0-9a-f]{40}",
        payload["artifacts"]["verification_code_revision"],
    )
    for run in payload["runs"]:
        assert re.fullmatch(r"[0-9a-f]{40}", run["code_revision"])
        assert all(
            re.fullmatch(r"[0-9a-f]{64}", value)
            for value in run["artifacts"].values()
        )


def test_financebench_reranker_public_evidence_records_repository_checks() -> None:
    payload = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    verification = payload["repository_verification"]

    assert verification["full_test_passed"] == 2496
    assert verification["full_test_skipped"] == 30
    assert verification["full_test_failed"] == 0
    assert verification["public_audit_candidates"] == 946
    assert verification["public_audit_findings"] == 0
