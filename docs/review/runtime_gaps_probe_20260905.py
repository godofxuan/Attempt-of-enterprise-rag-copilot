"""Read-only synthetic probes for the d27c0f8 runtime review, not quality evals."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.agent.controller_v2 import V2AgentController
from app.agent.evidence_ledger import build_ledger
from app.agent.generation_v2 import GenerationV2ResponseBuilder
from app.agent.tools_v2 import V2ToolRegistry
from app.domain.queries import QueryAnalysis
from tests.agent_v2.test_generation_v2 import (
    CapturingChat,
    TEST_NONCE,
    _replace_state,
    evidence_records_from_prompt,
    state_with_evidence,
    valid_payload,
)
from tests.v2_test_support import (
    RecordingNavigator,
    admit_open_result,
    admitted_search_hit,
    open_result,
    search_hit,
    search_result,
    user_context,
)


def generate(state, text=None, *, error=None):
    chat = CapturingChat(error if error is not None else valid_payload(claim_text=text))
    response = GenerationV2ResponseBuilder(
        chat_fn=chat,
        model="synthetic-no-model-call",
        max_attempts=1,
        nonce_factory=lambda: TEST_NONCE,
    ).build(
        question=state.analysis.original_question,
        state=state,
        mode="answered",
        stop_reason="completed",
        trace={"stop_reason": "completed"},
    )
    records = evidence_records_from_prompt(
        chat.calls[0]["messages"][1]["content"], TEST_NONCE
    )
    return response, records


def packing_starvation():
    state = state_with_evidence(include_second=True)
    text = "Policy A allows remote work three days per month. " + "Policy background. " * 65
    evidence = {
        "Policy A": [
            admitted_search_hit(
                chunk_id=f"a-{index}",
                doc_id=f"a-doc-{index}",
                matched_text=text,
                context_text=text,
            )
            for index in range(5)
        ],
        "Policy B": state.evidence_by_aspect["Policy B"],
    }
    state = _replace_state(
        state, evidence_by_aspect=evidence, ledger=build_ledger(state.analysis, evidence)
    )
    response, records = generate(state)
    return {
        "ledger_coverage": state.ledger.coverage,
        "ledger_aspects": state.ledger.supported_aspects,
        "prompt_aspects": sorted({row["aspect"] for row in records}),
        "prompt_record_count": len(records),
        "response_mode": response.mode,
        "response_stop_reason": response.stop_reason,
        "answer_mentions_policy_b": "Policy B" in response.answer,
    }


def open_evidence_cannot_support():
    state = state_with_evidence()
    claim = "Policy A allows 9 remote work days per quarter."
    state = _replace_state(
        state,
        open_results=[admit_open_result(open_result(content=claim))],
    )
    response, records = generate(state, claim)
    return {
        "open_fact_in_prompt": any(claim in str(row) for row in records),
        "requested_claim_published": any(row.text == claim for row in response.claims),
        "response_mode": response.mode,
        "response_stop_reason": response.stop_reason,
        "trace_stop_reason": response.trace.get("stop_reason"),
    }


def trimmed_evidence_can_support():
    state = state_with_evidence()
    claim = "The escalation window is 17 hours."
    text = "General policy background. " * 60 + claim
    evidence = {
        "answer": [admitted_search_hit(matched_text=text, context_text=text)]
    }
    state = _replace_state(
        state, evidence_by_aspect=evidence, ledger=build_ledger(state.analysis, evidence)
    )
    response, records = generate(state, claim)
    return {
        "claim_in_prompt_evidence": any(claim in str(row) for row in records),
        "claim_in_full_admitted_evidence": claim in text,
        "claim_published": any(row.text == claim for row in response.claims),
        "response_mode": response.mode,
        "citation_supported": [row.supported for row in response.citations],
    }


def conflicting_evidence():
    analysis = QueryAnalysis(
        original_question="What is the refund processing deadline?",
        intent="fact",
        required_aspects=["answer"],
        search_queries=["refund processing deadline"],
        source="rules",
    )
    texts = [
        "The refund processing deadline is 7 days.",
        "The refund processing deadline is 30 days.",
    ]
    hits = [
        search_hit(
            chunk_id=f"refund-{index}",
            doc_id=f"refund-doc-{index}",
            matched_text=text,
            context_text=text,
        )
        for index, text in enumerate(texts)
    ]
    navigator = RecordingNavigator(search_results=[search_result(hits)])
    registry = V2ToolRegistry(navigator, clock_ms=lambda: 0.0)
    controller = V2AgentController(clock_ms=lambda: 0.0)
    state = controller.initialize(analysis, user_context())
    action = controller.next_decision(state).action
    execution = registry.run(action, state.budget_state)
    state = controller.observe(state, execution)
    terminal = controller.next_decision(state)
    return {
        "guard_admitted_hits": len(execution.result.hits),
        "ledger_relations": [item.relation for item in state.ledger.items],
        "ledger_conflicting_aspects": state.ledger.conflicting_aspects,
        "ledger_coverage": state.ledger.coverage,
        "terminal_mode": terminal.terminal_mode,
    }


def final_outcome_trace():
    state = state_with_evidence()
    response, _ = generate(state, error=RuntimeError("synthetic transport failure"))
    return {
        "response_mode": response.mode,
        "response_stop_reason": response.stop_reason,
        "trace_stop_reason": response.trace.get("stop_reason"),
        "generation_attempts": response.trace.get("generation_attempts"),
    }


def main():
    root = Path(__file__).resolve().parents[2]
    actual_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    dirty = bool(subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=root
    ).strip())
    print(json.dumps({
        "kind": "SYNTHETIC_COMPONENT_DIAGNOSTIC_NOT_MODEL_EVAL",
        "review_reference_sha": "d27c0f8a68830fd74bbb983567e8b4d50967c0ae",
        "actual_head_sha": actual_sha,
        "actual_worktree_dirty": dirty,
        "packing_starvation": packing_starvation(),
        "open_evidence_cannot_support": open_evidence_cannot_support(),
        "trimmed_evidence_can_support": trimmed_evidence_can_support(),
        "conflicting_evidence": conflicting_evidence(),
        "final_outcome_trace": final_outcome_trace(),
    }, indent=2))


if __name__ == "__main__":
    main()
