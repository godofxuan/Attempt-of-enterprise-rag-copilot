from __future__ import annotations

import hashlib

from app.agent.runner_v2 import V2AgentRunner
from app.agent.tools_v2 import V2ToolRegistry
from app.evaluation.wixqa_multidoc_candidate import (
    SelectiveExtractiveResponseBuilder,
    decompose_query,
    derive_failure_analysis,
    evaluate_combined_gate,
    fuse_query_rankings,
    score_candidate_case,
    select_preferred_admitted_document_ids,
)
from tests.v2_test_support import (
    RecordingNavigator,
    search_hit,
    search_result,
    user_context,
)


def test_query_decomposition_is_bounded_and_deterministic() -> None:
    question = (
        "How do I configure account access, compare billing plans, "
        "and export audit records?"
    )
    expected = [
        question,
        "How do I configure account access",
        "compare billing plans",
    ]
    assert decompose_query(question) == expected
    assert decompose_query(question) == expected
    assert len(decompose_query(question)) <= 3


def test_query_decomposition_requires_two_substantial_clauses() -> None:
    assert decompose_query("What is billing and why?") == [
        "What is billing and why?"
    ]
    assert decompose_query("   What   is the account policy?  ") == [
        "What is the account policy?"
    ]


def test_multi_ranking_rrf_is_deterministic_and_deduplicates_sources() -> None:
    rankings = [
        ["doc-a", "doc-b", "doc-a"],
        ["doc-b", "doc-c"],
        ["doc-c", "doc-a"],
    ]
    first = fuse_query_rankings(rankings, rrf_k=60)
    second = fuse_query_rankings(rankings, rrf_k=60)
    assert first == second
    assert first == ["doc-a", "doc-b", "doc-c"]
    assert len(first) == len(set(first))


def test_selector_uses_only_guard_admitted_documents_and_is_bounded() -> None:
    selected = select_preferred_admitted_document_ids(
        [
            ["quarantined", "doc-a", "doc-b"],
            ["denied", "doc-b", "doc-a"],
            ["doc-c", "doc-a"],
            ["doc-d"],
        ],
        ["doc-a", "doc-b", "doc-c", "doc-d"],
        max_selected=3,
    )
    assert selected == ["doc-a", "doc-b", "doc-c"]
    assert "quarantined" not in selected
    assert "denied" not in selected


def test_selective_builder_does_not_bypass_agent_guarded_evidence() -> None:
    navigator = RecordingNavigator(
        search_results=[
            search_result(
                [
                    search_hit(doc_id="doc-a", chunk_id="chunk-a"),
                    search_hit(
                        doc_id="doc-b",
                        chunk_id="chunk-b",
                        policy_id="policy-b",
                        source_path="documents/doc-b.md",
                        matched_text="Remote work policy includes billing approval steps.",
                        context_text="Remote work policy includes billing approval steps.",
                        version_id="policy-b@2026",
                        fact_ids=["fact-b"],
                    ),
                ]
            )
        ]
    )
    builder = SelectiveExtractiveResponseBuilder(
        query_rankings=[
            ["not-admitted", "doc-a"],
            ["also-not-admitted", "doc-b"],
        ]
    )
    response = V2AgentRunner(
        registry=V2ToolRegistry(navigator, clock_ms=lambda: 0.0),
        response_builder=builder,
        clock_ms=lambda: 0.0,
    ).run("What are the remote work policy steps?", user_context(), top_k=2)

    assert builder.admitted_document_ids == ["doc-a", "doc-b"]
    assert builder.selected_document_ids == ["doc-a", "doc-b"]
    assert [source.doc_id for source in response.sources] == ["doc-a", "doc-b"]
    assert "not-admitted" not in builder.selected_document_ids


def _case(
    *,
    arm: str,
    case_id: str,
    cited: list[str],
    latency_ms: float = 10.0,
):
    return score_candidate_case(
        question_id_sha256=hashlib.sha256(case_id.encode()).hexdigest(),
        arm=arm,
        gold_document_ids=["gold-a", "gold-b"],
        retrieved_document_ids=["gold-a", "gold-b", "noise"],
        admitted_document_ids=["gold-a", "gold-b", "noise"],
        cited_document_ids=cited,
        response_mode="answered",
        trace={
            "budget": {"search_calls": 1, "find_calls": 0, "open_calls": 0},
            "stop_reason": "completed",
            "steps": [],
        },
        query_variant_count=1 if arm == "current" else 3,
        embedding_calls=1 if arm == "current" else 3,
        retrieval_compute_ms=latency_ms,
        mechanism_ms=0.0,
    )


def test_gate_requires_quality_precision_cost_and_paired_safety() -> None:
    baseline = [_case(arm="current", case_id=str(i), cited=["gold-a"]) for i in range(3)]
    candidate = [
        _case(
            arm="combined",
            case_id=str(i),
            cited=["gold-a", "gold-b"],
            latency_ms=15.0,
        )
        for i in range(3)
    ]
    gate = evaluate_combined_gate(
        baseline,
        candidate,
        guard_enabled=True,
        acl_enabled=True,
        production_paths_unchanged=True,
    )
    assert gate.decision == "DEVELOPMENT_CANDIDATE_HOLD_FOR_FIXED_VALIDATION"
    assert gate.paired_fix_count == 3
    assert gate.paired_regression_count == 0
    assert all(gate.checks.values())


def test_gate_rejects_naive_precision_collapse() -> None:
    baseline = [
        _case(arm="current", case_id=str(i), cited=["gold-a"])
        for i in range(3)
    ]
    candidate = [
        _case(
            arm="combined",
            case_id=str(i),
            cited=["gold-a", "gold-b", "noise"],
        )
        for i in range(3)
    ]
    gate = evaluate_combined_gate(
        baseline,
        candidate,
        guard_enabled=True,
        acl_enabled=True,
        production_paths_unchanged=True,
    )
    assert gate.decision == "DEVELOPMENT_CANDIDATE_REJECTED"
    assert gate.checks["citation_precision_drop_no_more_than_10pp"] is False


def test_failure_analysis_separates_acquisition_and_selection_loss() -> None:
    baseline = [
        _case(arm="current", case_id="a", cited=["gold-a"]),
        _case(arm="current", case_id="b", cited=["gold-a"]),
    ]
    candidate = [
        _case(arm="combined", case_id="a", cited=["gold-a", "noise"]),
        _case(arm="combined", case_id="b", cited=["gold-a", "gold-b"]),
    ]
    candidate[1] = candidate[1].model_copy(
        update={
            "retrieved_document_ids": ["gold-a", "noise"],
            "admitted_document_ids": ["gold-a", "noise"],
            "retrieval_recall": 0.5,
            "retrieval_complete": 0.0,
        }
    )
    gold = {
        item.question_id_sha256: ["gold-a", "gold-b"] for item in baseline
    }

    analysis = derive_failure_analysis(
        baseline,
        candidate,
        gold_documents_by_question_id_sha256=gold,
    )
    assert analysis.acquisition_incomplete_case_count == 1
    assert analysis.all_gold_admitted_case_count == 1
    assert analysis.selection_incomplete_after_complete_admission_count == 1
    assert analysis.cited_noise_document_count == 1


def test_candidate_module_does_not_change_default_response_selection() -> None:
    navigator = RecordingNavigator(
        search_results=[
            search_result(
                [
                    search_hit(doc_id="doc-a", chunk_id="chunk-a"),
                    search_hit(
                        doc_id="doc-b",
                        chunk_id="chunk-b",
                        policy_id="policy-b",
                        source_path="documents/doc-b.md",
                        matched_text="Remote work policy includes billing approval steps.",
                        context_text="Remote work policy includes billing approval steps.",
                        version_id="policy-b@2026",
                        fact_ids=["fact-b"],
                    ),
                ]
            )
        ]
    )
    response = V2AgentRunner(
        registry=V2ToolRegistry(navigator, clock_ms=lambda: 0.0),
        clock_ms=lambda: 0.0,
    ).run("What are the remote work policy steps?", user_context(), top_k=2)

    assert [source.doc_id for source in response.sources] == ["doc-a"]
