import json

from app.agent.query_analysis import RuleFirstQueryAnalyzer
from app.agent.task_plan import build_task_plan
from tests.v2_test_support import user_context


def test_advisor_keeps_original_needs_and_never_changes_query_filters():
    from app.agent.task_advisor import TaskAdvisor

    question = "出差报消要带啥，领导签个字就行？"
    analysis = RuleFirstQueryAnalyzer().analyze(question, user_context())
    before = analysis.model_dump_json()
    proposal = {"needs": [{"source_span": "领导签个字就行", "question": "领导签字是否足够"}]}
    advisor = TaskAdvisor(chat_fn=lambda *a, **kw: json.dumps(proposal), model="stub")
    original = build_task_plan(analysis)
    planned = advisor.plan(question, original)
    assert planned.planner_status == "accepted"
    assert planned.needs[: len(original.needs)] == original.needs
    assert analysis.model_dump_json() == before
    assert planned.planner_calls == 1
    assert advisor.plan(question, planned) == planned


def test_advisor_rejects_invented_numbers_and_nonexistent_original_span():
    from app.agent.task_advisor import TaskAdvisor

    question = "2026年制度BX-07里，不超过500元可以报销吗？"
    analysis = RuleFirstQueryAnalyzer().analyze(question, user_context())
    original = build_task_plan(analysis)
    for proposal in [
        {"needs": [{"source_span": question, "question": "超过900元可以报销"}]},
        {"needs": [{"source_span": "2027年", "question": "报销条件"}]},
        {"needs": [], "tool": "network"},
    ]:
        advisor = TaskAdvisor(
            chat_fn=lambda *a, proposal=proposal, **kw: json.dumps(proposal), model="stub"
        )
        result = advisor.plan(question, original)
        assert result.planner_status == "rejected"
        assert result.needs == original.needs


def test_advisor_failure_is_bounded_and_does_not_remove_rule_plan():
    from app.agent.task_advisor import TaskAdvisor

    question = "入职需要哪些材料，试用期多久？"
    original = build_task_plan(RuleFirstQueryAnalyzer().analyze(question, user_context()))
    calls = []

    def broken(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("private-token-must-not-be-logged")

    result = TaskAdvisor(chat_fn=broken, model="stub").plan(question, original)
    assert result.planner_status == "timeout" and result.needs == original.needs
    assert calls == [1]
    assert "private-token" not in result.model_dump_json()


def test_model_support_requires_known_visible_evidence_but_is_not_proof():
    from app.agent.task_advisor import TaskAdvisor
    from app.domain.evidence_packet import DeliveredEvidence
    from tests.v2_test_support import admitted_search_hit

    question = "入职需要哪些材料，试用期多久？"
    plan = build_task_plan(RuleFirstQueryAnalyzer().analyze(question, user_context()))
    hit = admitted_search_hit(matched_text="入职需要身份证。", context_text="入职需要身份证。")
    evidence = [DeliveredEvidence(anchor=hit, matched_text=hit.hit.matched_text)]
    proposal = {"assessments": [{"need_id": "N2", "status": "supported", "evidence_ids": ["E999"]}]}
    advisor = TaskAdvisor(chat_fn=lambda *a, **kw: json.dumps(proposal), model="stub")
    result = advisor.assess(question, plan, evidence)
    assert result.status == "rejected"
    assert not any(need.answer_claim_ids for need in plan.needs)


def test_standalone_advisor_has_local_deadline_and_restores_context():
    from app.agent.task_advisor import TaskAdvisor
    from app.runtime.request_context import current_request_context, remaining_seconds

    observed = []

    def chat(*args, **kwargs):
        observed.append(remaining_seconds())
        return '{"needs":[{"source_span":"入职","question":"入职"}]}'

    question = "入职材料？"
    plan = build_task_plan(RuleFirstQueryAnalyzer().analyze(question, user_context()))
    TaskAdvisor(model="stub", chat_fn=chat).plan(question, plan)
    assert observed[0] is not None and 0 < observed[0] <= 5
    assert current_request_context() is None


def test_advisor_does_not_extend_existing_request_deadline():
    from app.agent.task_advisor import TaskAdvisor
    from app.runtime.request_context import (
        bind_request_context,
        current_request_context,
        reset_request_context,
    )

    token = bind_request_context("outer", deadline_ms=1000)
    original = current_request_context().deadline_at_ms
    seen = []

    def chat(*a, **kw):
        seen.append(current_request_context().deadline_at_ms)
        raise TimeoutError()

    try:
        plan = build_task_plan(RuleFirstQueryAnalyzer().analyze("入职材料？", user_context()))
        TaskAdvisor(model="stub", chat_fn=chat).plan("入职材料？", plan)
        assert seen == [original] and current_request_context().deadline_at_ms == original
    finally:
        reset_request_context(token)


def test_advisor_suggested_negation_change_is_rejected():
    from app.agent.task_advisor import TaskAdvisor

    question = "不得超过500元"
    plan = build_task_plan(RuleFirstQueryAnalyzer().analyze(question, user_context()))
    result = TaskAdvisor(
        model="stub",
        chat_fn=lambda *a, **kw: json.dumps(
            {"needs": [{"source_span": question, "question": "超过500元"}]}
        ),
    ).plan(question, plan)
    assert result.planner_status == "rejected" and result.needs == plan.needs


def test_task_plan_ids_must_be_stable_and_unique():
    import pytest
    from pydantic import ValidationError

    from app.agent.task_plan import RequestNeed, TaskPlan

    need = RequestNeed(need_id="N1", text="A", kind="explicit")
    with pytest.raises(ValidationError):
        TaskPlan(needs=(need, need))


def test_unicode_source_spans_are_presented_as_text_not_escape_sequences():
    from app.agent.task_advisor import TaskAdvisor

    observed = []

    def chat(model, messages, **kwargs):
        observed.append(messages[1]["content"])
        return json.dumps({"needs": [{"source_span": "年假", "question": "年假"}]})

    question = "年假怎么申请？"
    plan = build_task_plan(RuleFirstQueryAnalyzer().analyze(question, user_context()))
    TaskAdvisor(model="stub", chat_fn=chat).plan(question, plan)
    assert question in observed[0]
    assert "\\u5e74" not in observed[0]
