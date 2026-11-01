"""Real generation/parser/publication functions, injected outputs, zero model sends."""
import pytest

from app.agent.generation_v2 import GenerationV2ResponseBuilder
from tests.agent_v2.test_generation_v2 import CapturingChat, state_with_evidence, valid_payload, _replace_state
from tests.v2_test_support import admitted_search_hit


def build(state, payload):
    chat = CapturingChat(payload)
    result = GenerationV2ResponseBuilder(chat_fn=chat, model='program-fixture', max_attempts=1).build(
        question=state.analysis.original_question, state=state, mode='answered', stop_reason='completed', trace={})
    assert len(chat.calls) == 1
    assert 'request_coverage' in chat.calls[0]['response_format']['required']
    return result


def relation(state, *, supported=True):
    return [{'need_id': n.need_id, 'claim_ids': ['claim-1'],
        'status': 'supported' if supported else 'evidence_insufficient',
        'subject_matches': supported, 'attribute_matches': supported, 'conditions_preserved': supported}
        for n in state.task_plan.needs]


def test_new_wire_relation_reaches_unique_publication_on_actual_final_claims():
    state = state_with_evidence()
    payload = valid_payload()
    payload['request_coverage'] = relation(state)
    result = build(state, payload)
    assert result.mode == 'answered'
    decision = result.trace['answer_decision']
    assert decision['publication_count'] == 1
    assert decision['requirements'][0]['basis'] == 'bound_generation_relation_not_independent_semantic_proof'
    assert set(result.trace['generation_need_relations']['claim_bindings']) == {c.claim_id for c in result.claims}


def test_empty_claims_do_not_publish_the_unverified_model_prose_or_any_source():
    result = build(state_with_evidence(), {'answer': 'Unsupported secret allocation', 'claims': [], 'request_coverage': []})
    assert result.mode == 'partial' and result.trace['answer_strategy'] == 'bounded_insufficiency'
    assert result.sources == result.claims == result.citations == []
    assert 'Unsupported' not in result.answer and 'secret' not in result.model_dump_json().lower()


@pytest.mark.parametrize('defect', ['wrong_subject', 'wrong_attribute'])
def test_legitimate_but_irrelevant_source_is_not_complete_with_unresolved_relation(defect):
    state = state_with_evidence()
    text = ('Policy B allows remote work three days per month.' if defect == 'wrong_subject'
        else 'Policy A requires a refundable equipment deposit of 300 dollars.')
    hit = admitted_search_hit(chunk_id='chunk-a', doc_id='doc-a', matched_text=text, context_text=text)
    state = _replace_state(state, evidence_by_aspect={'answer': [hit]})
    payload = valid_payload(claim_text=text)
    payload['request_coverage'] = relation(state, supported=False)
    result = build(state, payload)
    assert result.mode != 'answered'
    assert result.trace['answer_decision']['requirement_counts']['supported_and_stated'] == 0
    # This is a genuine source, not a claim mutated while borrowing an old citation.
    assert result.trace['delivery_binding_dropped_claims'] == 0


def test_literal_source_scope_protection_overrules_even_a_positive_model_relation():
    state = state_with_evidence()
    question = 'What is the monthly remote work limit in London office?'
    from app.agent.task_plan import build_task_plan
    from app.domain.queries import QueryAnalysis
    analysis = QueryAnalysis(original_question=question, intent='fact', required_aspects=[question],
        search_queries=[question], source='rules')
    text = 'Paris office allows remote work three days per month.'
    hit = admitted_search_hit(chunk_id='chunk-a', doc_id='doc-a', matched_text=text, context_text=text)
    state = _replace_state(state, analysis=analysis, task_plan=build_task_plan(analysis),
        evidence_by_aspect={'answer': [hit]})
    payload = valid_payload(claim_text=text)
    payload['request_coverage'] = relation(state)
    result = build(state, payload)
    assert result.mode != 'answered' and not result.claims
    assert result.trace['query_applicability']['dropped_claims'] == 1
