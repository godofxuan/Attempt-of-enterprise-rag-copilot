from __future__ import annotations

from types import SimpleNamespace

from scripts.audit_finqa_descriptor_retriever_v1 import _summarize


def test_retriever_summary_requires_zero_model_requests() -> None:
    gates = SimpleNamespace(
        min_role_recall_at_4=0.85,
        min_role_recall_at_8=0.95,
        min_complete_typed_case_rate_at_8=0.9,
        min_candidate_edge_reduction_rate=0.7,
        max_mean_latency_ms=100.0,
        max_p95_latency_ms=250.0,
    )
    protocol = SimpleNamespace(gates=gates)
    row = {
        "status": "EVALUATED",
        "route_match": True,
        "model_request_count": 1,
        "latency_ms": 1.0,
        "evidence_role_count": 1,
        "baseline_role_candidate_edges": 20,
        "selected_role_candidate_edges": 2,
        "complete_at_8": True,
        "prompt_leakage": False,
        "candidate_identity_preserved": True,
        "input_order_invariant": True,
        "retention": [{"retained_at_4": True, "retained_at_8": True}],
    }

    summary = _summarize([row], protocol)

    assert summary["gate_checks"]["zero_model_requests"] is False
    assert summary["decision"] == "DETERMINISTIC_DESCRIPTOR_RETRIEVER_GATE_FAILED"
