"""Original wire replies through real parsing, mapping, verification and publication.

This uses the exact saved delivered packet, not new retrieval/model success.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.agent import generation_v2 as generation
from app.agent import answer_publication as publication
from app.agent.controller_v2 import V2AgentController
from app.agent.evidence_ledger import build_ledger
from app.agent.source_unit_completion import complete_units
from app.agent.task_plan import TaskPlan, RequestNeed, observe_task
from app.domain.evidence_packet import DeliveredEvidence
from app.domain.queries import QueryAnalysis
from tests.v2_test_support import admitted_search_hit, user_context
from tests.agent_v2.test_generation_v2 import state_with_evidence, valid_payload, CapturingChat

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures' / 'a1_mapping'


def recorded(number):
    path = FIXTURES / (number + '.json')
    raw = json.loads(path.read_text('utf8'))
    metadata = raw['metadata']
    records = raw['records']
    chunks = json.loads((FIXTURES / 'chunks.json').read_text('utf8'))
    sources = []
    for record in records:
        row = deepcopy(record)
        for field in ('matched_text', 'context_text'):
            for unit_id in record['source_units']:
                row[field] = row[field].replace('[' + unit_id + ']', '').replace('[/' + unit_id + ']', '')
        original = next(c for c in chunks if c['doc_id'] == record['source_doc_id'] and c['version_id'] == record['version'])
        assert row['matched_text'] in original['text'], 'Recorded text must remain anchored to the frozen original'
        hit = admitted_search_hit(chunk_id=original['chunk_id'], doc_id=original['doc_id'],
            policy_id=original['policy_id'], source_path=original['source_path'], section_path=original['section_path'],
            tenant_id=original['tenant_id'], region=original['region'], acl_groups=original['acl_groups'],
            version_id=original['version_id'], version=original['version'], status=original['status'],
            authority_level=original['authority_level'], index_run_id='r4-hybrid-v1',
            matched_text=original['text'], context_text=original['text'])
        view = DeliveredEvidence(hit, row['matched_text'], row['context_text'])
        row['source_units'] = [{'unit_id': record['source_id'] + 'U' + str(i), 'field': u.field,
                               'start': u.start, 'end': u.end} for i, u in enumerate(complete_units(view), 1)]
        assert [u['unit_id'] for u in row['source_units']] == record['source_units']
        sources.append(generation._PromptSource(record['source_id'], record['aspect'], hit,
            json.dumps(row, ensure_ascii=False, separators=(',', ':')), view, (record['aspect'],)))
    question = metadata['question']
    analysis = QueryAnalysis(original_question=question, intent=metadata['intent'], required_aspects=['answer'],
                             search_queries=[question], source='rules')
    who = user_context().model_copy(update={'tenant_id': 'p03r-isolated', 'region': 'CN'})
    state = V2AgentController(clock_ms=lambda: 0).initialize(analysis, who)
    values = {k: getattr(state, k) for k in type(state).model_fields}
    plan = TaskPlan(needs=tuple(RequestNeed(need_id=n['id'], text=n['question'], kind='explicit') for n in metadata['request_needs']))
    values.update(task_plan=observe_task(plan, question, [s.delivered for s in sources], searched=True),
                  evidence_by_aspect={'answer': [s.evidence for s in sources]},
                  ledger=build_ledger(analysis, {'answer': [s.evidence for s in sources]}))
    return type(state)(**values), sources, raw['response_content']


def save(name, result, extra=None):
    folder = os.environ.get('SERVICE_AGENT_EVIDENCE')
    if folder:
        Path(folder, name + '.json').write_text(json.dumps({'kind': 'OFFLINE_SAVED_REPLY_NOT_NEW_MODEL',
            'response': result.model_dump(mode='json'), **(extra or {})}, ensure_ascii=False, indent=2), 'utf8')


def replay(monkeypatch, number='09694', mutate=None, name=None):
    state, sources, raw = recorded(number)
    payload = json.loads(raw)
    if mutate:
        mutate(payload)
        raw = json.dumps(payload, ensure_ascii=False)
    original = generation._parse_generated_answer(raw)
    mapping_error = None
    try:
        mapped = generation._map_claims(original.claims, {s.source_id: s for s in sources})
    except ValueError as exc:
        mapped = []
        mapping_error = str(exc)
    saved_trace = json.loads((FIXTURES / 'packet_trace.json').read_text('utf8'))
    def saved_packet(*args, **kwargs):
        audit = kwargs['audit']
        audit.update({k: deepcopy(v) for k, v in saved_trace.items() if k.startswith('packet_')})
        audit['replay_packet_scope'] = 'ORIGINAL_DELIVERED_PACKET_NOT_NEW_RETRIEVAL_OR_PACKING_MEASUREMENT'
        return sources
    monkeypatch.setattr(generation, '_build_prompt_sources', saved_packet)
    chat = CapturingChat(raw)
    result = generation.GenerationV2ResponseBuilder(chat_fn=chat, model='SAVED_ORIGINAL_REPLY', max_attempts=1).build(
        question=state.analysis.original_question, state=state, mode='answered', stop_reason='completed', trace={})
    save(name or ('RAW_' + number), result, {'raw_answer': payload['answer'],
        'wire_units': {c['claim_id']: c.get('source_unit_id') for c in payload['claims']},
        'initial_mapped_claims': [c.model_dump(mode='json') for c in mapped],
        'initial_mapping_error': mapping_error,
        'delivered_units': {s.source_id: [u.quote for u in complete_units(s.delivered)] for s in sources}})
    assert len(chat.calls) == 1, result.trace
    return result, sources


@pytest.mark.parametrize('number', ['09694', '09697'])
def test_original_complete_draft_keeps_each_required_supported_clause(monkeypatch, number):
    result, sources = replay(monkeypatch, number)
    expected = [u.quote for u in complete_units(sources[0].delivered)]
    assert all(text in result.answer for text in expected), 'A required source-backed draft condition disappeared'
    assert result.mode == 'answered'
    assert result.trace['answer_decision']['publication_count'] == 1
    assert not any(c.cited_chunk_ids == [s.delivered.citation_id] for s in sources[1:] for c in result.claims)


def test_legal_repeated_unit_is_preserved_without_rejecting_shared_citation(monkeypatch):
    def narrow(payload):
        state, sources, _ = recorded('09694')
        payload['answer'] = next(complete_units(sources[0].delivered)).quote
        payload['claims'] = payload['claims'][:2]
        payload['request_coverage'] = [{'need_id': n.need_id, 'claim_ids': ['C1', 'C2'], 'status': 'unknown',
            'subject_matches': True, 'attribute_matches': True, 'conditions_preserved': True} for n in state.task_plan.needs]
    result, _ = replay(monkeypatch, mutate=narrow, name='LEGAL_REPEATED_UNIT')
    assert {c.claim_id for c in result.claims} == {'C1', 'C2'}
    assert result.trace.get('generation_error_category') is None
    assert result.trace['delivery_binding_dropped_claims'] == 0


def test_unverified_free_prose_never_becomes_a_fact(monkeypatch):
    def add(payload):
        payload['answer'] += '设备已批准并分配，押金为9999元。'
    result, _ = replay(monkeypatch, '09697', add, 'UNVERIFIED_FREE_PROSE')
    assert '9999' not in result.answer and '设备已批准并分配' not in result.answer
    assert all('9999' not in c.text for c in result.claims)


def test_invented_structured_fact_is_not_supported(monkeypatch):
    def add(payload):
        payload['claims'].append({'claim_id': 'invented', 'text': '设备已批准并分配，押金为9999元。',
            'cited_source_ids': ['S1'], 'critical': True})
    result, _ = replay(monkeypatch, '09697', add, 'UNSUPPORTED_STRUCTURED_FACT')
    assert result.mode != 'answered'
    assert '9999' not in result.answer


def test_late_publication_loss_invalidates_completion_even_with_valid_relations(monkeypatch):
    original_policy = publication.assess_answer_applicability
    def discard(question, response):
        decision = original_policy(question, response)
        assert decision is None
        keep = {c.claim_id for c in response.claims if not c.claim_id.startswith('host-answer-unit-')}
        return SimpleNamespace(claim_ids=keep, notes=[], audit={'offline_injected_selection_loss': True})
    monkeypatch.setattr(publication, 'assess_answer_applicability', discard)
    result, _ = replay(monkeypatch, name='LATE_SELECTION_LOSS')
    assert result.mode == 'partial'
    assert result.trace['answer_decision']['requirement_counts']['supported_and_stated'] == 0
    assert result.trace['draft_delivery_binding']['missing_content']
    assert '未完整交付' in result.answer


def test_missing_declared_condition_is_fail_closed(monkeypatch):
    def mutate(payload):
        payload['claims'][0]['condition_claim_ids'] = ['missing-condition']
    result, _ = replay(monkeypatch, mutate=mutate, name='MISSING_DECLARED_CONDITION')
    assert result.mode != 'answered'


def test_cross_version_condition_cannot_repair_a_draft(monkeypatch):
    def mutate(payload):
        payload['claims'][0]['condition_claim_ids'] = ['C2']
        payload['claims'][1].update(source_unit_id='S2U1', cited_source_ids=['S2'], evidence_role='necessary_condition')
    result, _ = replay(monkeypatch, mutate=mutate, name='CROSS_POLICY_CONDITION')
    assert result.mode != 'answered' and not result.claims


def test_true_insufficiency_preserves_bounded_unknown_without_model_prose(monkeypatch):
    def mutate(payload):
        payload.update(answer='No evidence establishes the requested fact. Private hypothetical 9999.', claims=[], request_coverage=[])
    result, _ = replay(monkeypatch, mutate=mutate, name='TRUE_INSUFFICIENCY')
    assert result.mode == 'partial' and not result.claims and not result.sources
    assert '9999' not in result.model_dump_json()


def test_wrong_subject_with_positive_model_label_remains_blocked():
    from tests.agent_v2.test_continuous_generation_handoff import build, relation
    from tests.agent_v2.test_generation_v2 import _replace_state
    from app.agent.task_plan import build_task_plan
    state = state_with_evidence()
    question = 'What is the monthly remote work limit in London office?'
    analysis = QueryAnalysis(original_question=question, intent='fact', required_aspects=[question], search_queries=[question], source='rules')
    text = 'Paris office allows remote work three days per month.'
    hit = admitted_search_hit(matched_text=text, context_text=text)
    state = _replace_state(state, analysis=analysis, task_plan=build_task_plan(analysis), evidence_by_aspect={'answer': [hit]})
    payload = valid_payload(claim_text=text)
    payload['request_coverage'] = relation(state)
    result = build(state, payload)
    save('WRONG_SUBJECT', result)
    assert result.mode != 'answered' and not result.claims


def test_normal_shared_quote_remains_answered():
    from tests.agent_v2.test_continuous_generation_handoff import build, relation
    state = state_with_evidence()
    payload = valid_payload()
    payload['claims'].append({**payload['claims'][0], 'claim_id': 'claim-2'})
    payload['request_coverage'] = relation(state)
    payload['request_coverage'][0]['claim_ids'].append('claim-2')
    result = build(state, payload)
    save('NORMAL_SHARED_QUOTE', result)
    assert result.mode == 'answered' and len(result.claims) == 2
    assert result.answer.count(payload['answer']) == 1


def test_http_serializer_delivers_the_actual_replayed_builder_result(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from tests.api_v2.helpers import USER_HEADERS, make_container
    result, sources = replay(monkeypatch, name='API_BUILDER_RESULT')
    def saved_stage(question, user, top_k=None):
        assert question == recorded('09694')[0].analysis.original_question
        return result
    monkeypatch.setattr('app.main.run_agent_v2_chat', saved_stage)
    client = TestClient(create_app(make_container()))
    reply = client.post('/agent/v2/chat', headers=USER_HEADERS,
                        json={'question': recorded('09694')[0].analysis.original_question})
    assert reply.status_code == 200
    body = reply.json()
    assert body['answer'] == result.answer and body['mode'] == result.mode
    assert all(u.quote in body['answer'] for u in complete_units(sources[0].delivered))
    folder = os.environ.get('SERVICE_AGENT_EVIDENCE')
    if folder:
        Path(folder, 'API_SERIALIZED_BODY.json').write_text(json.dumps({
            'kind': 'OFFLINE_REAL_HTTP_SERIALIZER_WITH_SAVED_GENERATION_STAGE_NOT_LIVE_RETRIEVAL_OR_IDENTITY_REACCEPTANCE',
            'status': reply.status_code, 'body': body}, ensure_ascii=False, indent=2), 'utf8')


@pytest.mark.parametrize('variant', ['normal', 'ambiguous_version', 'capacity'])
def test_generic_unit_preservation_is_bounded_and_not_specific_to_original_ids(variant):
    first = 'Policy Q permits one workspace booking per employee.'
    condition = 'An employee without sponsor approval cannot book a workspace.'
    sources = {}
    for sid, version in [('S8', 'v-current'), *([('S9', 'v-previous')] if variant == 'ambiguous_version' else [])]:
        hit = admitted_search_hit(doc_id='workspaces', policy_id='workspace-policy', version_id=version,
            matched_text=first + ' ' + condition, context_text=first + ' ' + condition)
        view = DeliveredEvidence(hit, hit.hit.matched_text)
        sources[sid] = generation._PromptSource(sid, 'answer', hit, '{}', view, ('answer',))
    rows = [{'claim_id': 'q' + str(i), 'source_unit_id': ('S9' if i == 1 and variant == 'ambiguous_version' else 'S8') + 'U1',
             'cited_source_ids': ['S9' if i == 1 and variant == 'ambiguous_version' else 'S8']}
            for i in range(20 if variant == 'capacity' else 2 if variant == 'ambiguous_version' else 1)]
    generated = generation.GeneratedAnswer.model_validate({'answer': first + ' ' + condition, 'claims': rows})
    mapped = generation._map_claims(generated.claims, sources)
    mapped, audit = generation._preserve_draft_units(generated, mapped, sources, 'Workspace booking conditions?')
    if variant == 'normal':
        assert condition in [c.text for c in mapped] and len(audit['restored_claim_ids']) == 1
        assert not audit['unresolved_unit_sha256']
    else:
        assert not audit['restored_claim_ids'] and audit['unresolved_unit_sha256']
        assert len(mapped) == len(rows)


def test_authored_unit_without_any_selected_source_is_explicitly_unresolved():
    texts = {'S8': 'Policy Q permits one workspace booking per employee.',
             'S9': 'Policy Z requires sponsor approval for a workspace booking.'}
    sources = {}
    for sid, text in texts.items():
        hit = admitted_search_hit(doc_id=sid, policy_id=sid, matched_text=text, context_text=text)
        view = DeliveredEvidence(hit, text)
        sources[sid] = generation._PromptSource(sid, 'answer', hit, '{}', view, ('answer',))
    generated = generation.GeneratedAnswer.model_validate({'answer': '\n'.join(texts.values()),
        'claims': [{'claim_id': 'q', 'source_unit_id': 'S8U1', 'cited_source_ids': ['S8']}]})
    mapped = generation._map_claims(generated.claims, sources)
    mapped, audit = generation._preserve_draft_units(generated, mapped, sources, 'The requested booking conditions')
    assert len(mapped) == 1 and not audit['restored_claim_ids']
    assert audit['unresolved_unit_sha256'], 'An authored delivered unit without a selected origin was silently ignored'
