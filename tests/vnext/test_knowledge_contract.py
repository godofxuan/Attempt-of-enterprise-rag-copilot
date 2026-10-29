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


def test_semantic_knowledge_path_keeps_admitted_candidates_and_original_request():
    from app.agent.controller_v2 import V2AgentController
    from tests.v2_test_support import user_context,RecordingNavigator,search_result,search_hit
    from app.agent.tools_v2 import V2ToolRegistry
    question='计划2028-12-06借电脑参加跨部门会议，请说明资格、期限和审批状态。'
    analysis=QueryAnalysis(original_question=question,intent='fact',required_aspects=[question],search_queries=[question],source='rules')
    controller=V2AgentController(semantic_question=True,clock_ms=lambda:0)
    state=controller.initialize(analysis,user_context())
    assert state.task_plan.mode=='task' and [n.text for n in state.task_plan.needs]==[question]
    navigator=RecordingNavigator(search_results=[search_result([search_hit(matched_text='有效维修记录才可借用电脑。期限1至14天。提交后待审批。',context_text='有效维修记录才可借用电脑。期限1至14天。提交后待审批。')])])
    registry=V2ToolRegistry(navigator,clock_ms=lambda:0)
    decision=controller.next_decision(state)
    state=controller.observe(state,registry.run(decision.action,state.budget_state))
    assert state.evidence_by_aspect[question], 'An admitted candidate is not an absence of evidence merely because a personal date is absent from policy prose'


def test_semantic_unknown_relation_cannot_become_complete_from_source_binding_alone():
    from app.agent.task_plan import bind_need_evaluations,apply_need_evaluations
    from app.domain.evidence import Claim
    question='2029年的制度是否同样适用？'
    analysis=QueryAnalysis(original_question=question,intent='fact',required_aspects=[question],search_queries=[question],source='rules')
    plan=build_task_plan(analysis).model_copy(update={'mode':'task'})
    claim=Claim(claim_id='c1',text='2026年的制度允许申请。',cited_chunk_ids=['s1'],critical=True,need_refs=['N1'])
    relation=bind_need_evaluations(plan,question,[claim],[dict(need_id='N1',claim_ids=['c1'],status='unknown',subject_matches=True,attribute_matches=True,conditions_preserved=False)])
    assessed=apply_need_evaluations(plan,question,[claim],relation)
    assert not assessed.needs[0].answer_claim_ids and assessed.needs[0].answer_relation_status=='unknown'


def test_saved_live_reply_recovered_unit_keeps_unambiguous_need_and_unknown_stays_unknown():
    import json
    from pathlib import Path
    from app.agent import generation_v2 as generation
    from app.agent.controller_v2 import V2AgentController
    from app.agent.evidence_ledger import build_ledger
    from app.domain.evidence_packet import DeliveredEvidence
    from tests.v2_test_support import admitted_search_hit,user_context
    from tests.agent_v2.test_generation_v2 import CapturingChat
    fixture=json.loads((Path(__file__).resolve().parents[1]/'fixtures/vnext/knowledge_unit_handoff.json').read_text('utf8'))
    q=fixture['question'];analysis=QueryAnalysis(original_question=q,intent='fact',required_aspects=['answer'],search_queries=[q],source='rules')
    state=V2AgentController(semantic_question=True,clock_ms=lambda:0).initialize(analysis,user_context())
    sources=[]
    for row in fixture['records']:
        hit=admitted_search_hit(chunk_id=row['source_id'],doc_id=row['source_id'],matched_text=row['matched_text'],context_text=row['context_text'] or row['matched_text'])
        view=DeliveredEvidence(hit,row['matched_text'],row['context_text'])
        record=dict(row);record.pop('source_units')
        sources.append(generation._PromptSource(row['source_id'],q,hit,generation._json_record(record),view,(q,)))
    state.evidence_by_aspect={'answer':[s.evidence for s in sources]};state.ledger=build_ledger(analysis,state.evidence_by_aspect)
    def replay(payload):return generation.GenerationV2ResponseBuilder(chat_fn=CapturingChat(payload),model='RECORDED_REPLY_NOT_NEW_MODEL',max_attempts=1).build(question=q,state=state,mode='answered',stop_reason='completed',trace={})
    payload=json.loads(fixture['response_content']);result=replay(payload)
    assert result.mode=='answered',json.dumps(result.trace,ensure_ascii=False)
    assert '提交后工单为待审批' in result.answer and '不得早于申请当天' in result.answer
    assert all(c.need_refs for c in result.claims)
    assert result.trace['draft_delivery_binding']['complete']
    payload['request_coverage'][0].update(status='unknown',conditions_preserved=False)
    negative=replay(payload)
    assert negative.mode!='answered' and not negative.trace['answer_decision']['requirements'][0]['claim_ids']
    payload.pop('request_coverage')
    assert replay(payload).mode!='answered', 'Missing semantic relation is not inferred from citations'
    payload=json.loads(fixture['response_content']);payload['claims'][0]['need_refs']=['N2']
    generated=generation._parse_generated_answer(json.dumps(payload,ensure_ascii=False))
    packet=generation._build_prompt_sources(state);by_id={s.source_id:s for s in packet}
    mapped=generation._map_claims(generated.claims,by_id)
    _,repair=generation._preserve_draft_units(generated,mapped,by_id,q)
    assert repair['restored_claim_ids']
    assert all(not c.need_refs for c in generated.claims if c.claim_id in repair['restored_claim_ids']), 'Shared source does not authorize guessing between needs'
