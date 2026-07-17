from __future__ import annotations

import pytest

from app.corpus.schemas import EvalCase, EvalUserContext
from app.domain.agent import AgentBudget
from app.domain.evidence import AnswerResponse, AnswerSource, Claim, ClaimCitation
from app.evaluation.agent import evaluate_agent_case


def eval_case(**updates) -> EvalCase:
    values = {
        "case_id": "case-one",
        "question": "Policy A 的当前规则是什么？",
        "task_type": "fact_lookup",
        "answer_mode": "answered",
        "user_context": EvalUserContext(
            user_id="employee-one",
            tenant="tenant-one",
            region="cn",
            groups=["employees"],
        ),
        "required_fact_ids": ["fact-a"],
        "gold_doc_ids": ["doc-a"],
        "distractor_doc_ids": [],
        "forbidden_doc_ids": [],
        "expected_answer": "3 天",
        "expected_filters": {},
        "expected_authority_doc_ids": ["doc-a"],
        "tags": ["current"],
    }
    values.update(updates)
    return EvalCase(**values)


def trace(
    tools: list[str],
    *,
    intent: str = "fact",
    stop_reason: str = "completed",
    required_aspect_count: int = 1,
    budget_updates: dict | None = None,
) -> dict:
    counters = {
        "search_calls": sum(tool == "search" for tool in tools),
        "find_calls": sum(tool == "find" for tool in tools),
        "open_calls": sum(tool == "open" for tool in tools),
        "steps": sum(tool in {"search", "find", "open"} for tool in tools),
        "context_chars": 100 * sum(tool in {"search", "find", "open"} for tool in tools),
    }
    counters.update(budget_updates or {})
    steps = []
    for sequence, tool in enumerate(tools, start=1):
        terminal = tool in {"answer", "stop", "refuse"}
        steps.append(
            {
                "sequence": sequence,
                "tool": tool,
                "status": "terminal" if terminal else "ok",
                "latency_ms": 1.0,
                "visible_count": 0 if terminal else 1,
                "context_chars_added": 0 if terminal else 100,
                "error_code": None,
                "budget": dict(counters),
            }
        )
    return {
        "intent": intent,
        "analysis_source": "rules",
        "required_aspect_count": required_aspect_count,
        "steps": steps,
        "stop_reason": stop_reason,
        "budget": counters,
    }


def response_with_trace(payload: dict, *, mode: str = "answered") -> AnswerResponse:
    if mode != "answered":
        return AnswerResponse(
            mode=mode,
            answer="No supported answer is available.",
            stop_reason=payload["stop_reason"],
            trace=payload,
        )
    return AnswerResponse(
        mode="answered",
        answer="Policy A allows 3 days.",
        claims=[
            Claim(
                claim_id="c1",
                text="Policy A allows 3 days.",
                cited_chunk_ids=["chunk-a"],
            )
        ],
        citations=[
            ClaimCitation(
                claim_id="c1",
                cited_chunk_ids=["chunk-a"],
                citation_present=True,
                references_visible_evidence=True,
                lexical_support=1.0,
                supported=True,
            )
        ],
        sources=[
            AnswerSource(
                doc_id="doc-a",
                source_path="documents/doc-a.md",
                section_path=["Policy"],
                chunk_id="chunk-a",
                preview="Policy A allows 3 days.",
            )
        ],
        stop_reason="completed",
        trace=payload,
    )


def test_agent_fact_trajectory_passes_intent_budget_stop_and_trace() -> None:
    response = response_with_trace(trace(["search", "answer"]))

    evaluated = evaluate_agent_case(
        eval_case(),
        response,
        AgentBudget(),
        runtime_mode="deterministic",
    )

    assert evaluated.layer.passed is True
    assert evaluated.layer.metrics["intent_correct"] is True
    assert evaluated.layer.metrics["tool_choice_correct"] is True
    assert evaluated.layer.metrics["budget_compliant"] is True
    assert evaluated.layer.metrics["stop_reason_correct"] is True
    assert evaluated.layer.metrics["trace_complete"] is True
    assert evaluated.layer.metrics["final_outcome_correct"] is True
    assert evaluated.layer.metrics["exact_trajectory_contract"] is True
    assert evaluated.tool_sequence == ["search", "answer"]


def test_comparison_requires_two_aspect_searches() -> None:
    case = eval_case(
        task_type="comparison",
        question="比较 Policy A 和 Policy B",
        gold_doc_ids=["doc-a", "doc-b"],
        required_fact_ids=["fact-a", "fact-b"],
        expected_authority_doc_ids=["doc-a", "doc-b"],
        tags=["comparison"],
    )
    response = response_with_trace(
        trace(
            ["search", "answer"],
            intent="comparison",
            required_aspect_count=2,
        )
    )

    evaluated = evaluate_agent_case(case, response, AgentBudget())

    assert evaluated.layer.passed is False
    assert evaluated.layer.metrics["decomposition_rewrite_correct"] is False
    assert any(
        failure.stage == "decomposition_rewrite"
        for failure in evaluated.layer.failures
    )


def test_completeness_requires_open_after_search() -> None:
    case = eval_case(task_type="completeness", tags=["completeness"])
    response = response_with_trace(
        trace(["search", "answer"], intent="completeness")
    )

    evaluated = evaluate_agent_case(case, response, AgentBudget())

    assert evaluated.layer.passed is False
    assert evaluated.layer.metrics["tool_choice_correct"] is False
    assert any(failure.code == "completeness_open_missing" for failure in evaluated.layer.failures)


def test_missing_trace_budget_key_is_system_runtime_failure() -> None:
    payload = trace(["search", "answer"])
    del payload["budget"]["context_chars"]
    response = response_with_trace(payload)

    evaluated = evaluate_agent_case(eval_case(), response, AgentBudget())

    assert evaluated.layer.passed is False
    assert evaluated.layer.metrics["trace_complete"] is False
    assert evaluated.layer.failures[0].stage == "system_runtime"


def test_budget_overrun_fails_even_when_outcome_is_correct() -> None:
    budget = AgentBudget(max_search_calls=1)
    response = response_with_trace(
        trace(
            ["search", "search", "answer"],
            budget_updates={"search_calls": 2},
        )
    )

    evaluated = evaluate_agent_case(eval_case(), response, budget)

    assert evaluated.layer.metrics["budget_compliant"] is False
    assert evaluated.layer.passed is False
    assert any(failure.code == "agent_budget_violation" for failure in evaluated.layer.failures)


def test_wrong_outcome_and_stop_reason_are_separate_failures() -> None:
    payload = trace(["search", "stop"], stop_reason="not_found")
    response = response_with_trace(payload, mode="not_found")

    evaluated = evaluate_agent_case(eval_case(), response, AgentBudget())

    assert evaluated.layer.metrics["final_outcome_correct"] is False
    assert evaluated.layer.metrics["stop_reason_correct"] is True
    assert any(failure.code == "final_outcome_mismatch" for failure in evaluated.layer.failures)


def test_exact_sequence_is_reported_but_not_live_hard_gate() -> None:
    response = response_with_trace(trace(["search", "find", "answer"]))

    evaluated = evaluate_agent_case(
        eval_case(),
        response,
        AgentBudget(),
        runtime_mode="live",
    )

    assert evaluated.layer.metrics["exact_trajectory_contract"] is False
    assert evaluated.layer.passed is True


def test_no_answer_search_then_stop_is_valid() -> None:
    case = eval_case(
        task_type="no_answer",
        answer_mode="not_found",
        required_fact_ids=[],
        gold_doc_ids=[],
        expected_answer=None,
        expected_authority_doc_ids=[],
        tags=["no_answer"],
    )
    response = response_with_trace(
        trace(["search", "stop"], intent="no_answer", stop_reason="not_found"),
        mode="not_found",
    )

    evaluated = evaluate_agent_case(case, response, AgentBudget())

    assert evaluated.layer.passed is True
    assert evaluated.layer.metrics["retry_rewrite_decision_correct"] is True


@pytest.mark.parametrize("intent", ["fact", "process", "completeness", "no_answer"])
def test_no_answer_outcome_accepts_evidence_seeking_input_intents(intent: str) -> None:
    case = eval_case(
        task_type="no_answer",
        answer_mode="not_found",
        required_fact_ids=[],
        gold_doc_ids=[],
        expected_answer=None,
        expected_authority_doc_ids=[],
        tags=["no_answer"],
    )
    tools = ["search", "open", "stop"] if intent == "completeness" else ["search", "stop"]
    response = response_with_trace(
        trace(tools, intent=intent, stop_reason="not_found"),
        mode="not_found",
    )

    evaluated = evaluate_agent_case(case, response, AgentBudget())

    assert evaluated.layer.metrics["intent_correct"] is True
    assert evaluated.layer.passed is True
