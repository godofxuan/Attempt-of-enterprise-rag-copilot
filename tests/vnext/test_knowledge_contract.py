"""Original obligations and one selected source unit per generated critical claim."""
from app.agent.task_plan import build_task_plan
from app.domain.queries import QueryAnalysis
from app.agent.generation_v2 import generation_response_format, _build_prompt_sources
from tests.agent_v2.test_generation_v2 import state_with_evidence


def test_independent_question_clauses_do_not_invent_materials_obligation():
    question='临时电脑维修期间能借多久？提交后是什么状态？'
    analysis=QueryAnalysis(original_question=question,intent='fact',required_aspects=[question],search_queries=[question],source='rules')
    plan=build_task_plan(analysis)
    assert plan.needs and all(n.text in question for n in plan.needs)
    assert any(n.text==question for n in plan.needs), 'The whole original obligation must survive clause layout'
    assert all('材料' not in n.text for n in plan.needs)


def test_wire_contract_requires_a_host_bound_complete_unit_not_a_composite_quote():
    state=state_with_evidence()
    sources=_build_prompt_sources(state)
    schema=generation_response_format(sources,state.task_plan)
    row=schema['properties']['claims']['items']
    assert 'source_unit_id' in row['required'] and 'text' not in row['required']
    assert row['properties']['source_unit_id']['enum']
