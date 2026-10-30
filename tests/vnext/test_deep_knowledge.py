"""Strategy/anchor checks, not model content-quality scores."""
import pytest
from app.agent.deep_knowledge import DeepPlan,DeepController
from app.agent.tools_v2 import V2ToolRegistry
from app.domain.agent import AgentBudget
from app.domain.queries import QueryAnalysis,OpenResult
from tests.v2_test_support import RecordingNavigator,search_hit,search_result,find_result,user_context


def test_deep_actually_searches_each_subquestion_and_reads_bound_results():
    plan=DeepPlan.model_validate({'subquestions':[
        {'question':'Policy A limit and conditions','query':'Policy A remote work conditions','read_hint':'remote'},
        {'question':'Policy B limit and conditions','query':'Policy B support shifts','read_hint':'shift'}]})
    hits=[search_hit(),search_hit(doc_id='doc-b',chunk_id='chunk-b',source_path='documents/doc-b.md',policy_id='policy-b',
        version_id='policy-b@2026',matched_text='Policy B allows two support shifts per week.',context_text='Policy B allows two support shifts per week.')]
    navigator=RecordingNavigator(search_results=[search_result([h]) for h in hits],
        find_results=[find_result(doc_id=h.doc_id) for h in hits],
        open_results=[OpenResult(request_id='test',target_type='chunk',target_id=h.chunk_id,doc_id=h.doc_id,
            content=h.matched_text,truncated=False,source_path=h.source_path,section_path=h.section_path) for h in hits])
    analysis=QueryAnalysis(original_question='Compare the two policies, preserving their applicability conditions.',intent='comparison',
        entities=[q.question for q in plan.subquestions],required_aspects=[q.question for q in plan.subquestions],
        search_queries=[q.query for q in plan.subquestions],source='model')
    controller=DeepController(plan,clock_ms=lambda:0)
    state=controller.initialize(analysis,user_context(),budget=AgentBudget(deadline_ms=240000,max_steps=18,max_search_calls=6))
    registry=V2ToolRegistry(navigator,clock_ms=lambda:0)
    for _ in range(18):
        decision=controller.next_decision(state)
        if decision.terminal_mode:break
        state=controller.observe(state,registry.run(decision.action,state.budget_state))
    assert [name for name,_ in navigator.calls]==['search','find','open','search','find','open']
    requests=[request for name,request in navigator.calls if name=='search']
    assert [r.query for r in requests]==[q.query for q in plan.subquestions]
    for name,request in navigator.calls:
        if name!='search':assert request.anchor_chunk_id and request.filters==analysis.filters
        assert request.user==user_context()
    assert state.task_plan.needs[0].text==analysis.original_question
    report=controller.report()
    assert len(report['evidence_table'])==2 and all(not r['retrieval_gap'] for r in report['evidence_table'])
    assert len(report['opened_targets'])==2


def test_deep_plan_is_bounded_and_cannot_accept_model_identity_or_filter_override():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):DeepPlan.model_validate({'subquestions':[], 'user':'operator'})
    with pytest.raises(ValidationError):DeepPlan.model_validate({'subquestions':[
        {'question':'same','query':'same','read_hint':''},{'question':'same','query':'same','read_hint':''}]})
