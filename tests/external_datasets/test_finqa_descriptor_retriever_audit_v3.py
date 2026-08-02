from __future__ import annotations

from types import SimpleNamespace

from scripts.audit_finqa_descriptor_retriever_v3 import _summarize


def test_hybrid_summary_enforces_embedding_and_generation_budgets() -> None:
    gates = SimpleNamespace(
        min_role_recall_at_4=0.85,
        min_role_recall_at_8=0.95,
        min_complete_typed_case_rate_at_8=0.9,
        min_candidate_edge_reduction_rate=0.7,
        max_mean_latency_ms=5000.0,
        max_p95_latency_ms=5000.0,
        max_embedding_requests_per_typed_case=1,
    )
    protocol = SimpleNamespace(gates=gates)
    row = {
        "status": "EVALUATED",
        "route_match": True,
        "embedding_request_count": 1,
        "generation_request_count": 1,
        "latency_ms": 1.0,
        "evidence_role_count": 1,
        "baseline_role_candidate_edges": 20,
        "selected_role_candidate_edges": 2,
        "complete_at_8": True,
        "embedding_payload_violation": False,
        "prompt_leakage": False,
        "candidate_identity_preserved": True,
        "input_order_invariant": True,
        "retention": [{"retained_at_4": True, "retained_at_8": True}],
    }

    summary = _summarize([row], protocol, model_identity_match=True)

    assert summary["gate_checks"]["embedding_request_budget"] is True
    assert summary["gate_checks"]["zero_generation_requests"] is False
    assert summary["decision"] == "HYBRID_DESCRIPTOR_RETRIEVER_GATE_FAILED"
