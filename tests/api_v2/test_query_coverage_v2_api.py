import json

import pytest

from tests.api_v2.test_runtime_closure_flow import service


@pytest.mark.parametrize('text,claim', [
    ('报销需要发票。超过500元的报销还需要发票原件。', '报销需要发票。'),
    ('报销需要发票。报销需要航班取消证明。', '报销需要发票。'),
])
def test_http_omitted_obligation_is_visible_partial(service, monkeypatch, text, claim):
    def chat(model, messages, **kwargs):
        records = next(json.loads(line) for line in messages[1]['content'].splitlines() if line.startswith('[{'))
        return json.dumps(dict(answer=claim, claims=[dict(claim_id='c1', text=claim,
            critical=True, cited_source_ids=[records[0]['source_id']])]), ensure_ascii=False)
    monkeypatch.setattr('app.agent.generation_v2.chat_with_ollama', chat)
    start, _, _ = service
    with start([dict(id='travel', text=text)]) as client:
        result = client.post('/agent/v2/chat', json={'question': '报销需要哪些材料？'})
    body = result.json()
    assert result.status_code == 200
    assert body['mode'] == 'partial'
    assert body['stop_reason'] == body['trace']['stop_reason'] == 'partial_evidence'
    assert body['trace']['final_mode'] == 'partial'
    assert '材料' in body['answer'] and body['warnings']
    assert claim in body['answer']
    assert all(c['supported'] for c in body['citations'])


@pytest.mark.parametrize('question', ['报销需要哪些材料、由谁审批、额度是多少？', '出差报消要带啥、由谁审皮、额度是多少？'])
def test_http_three_supported_claims_remain_published(service, monkeypatch, question):
    facts = ['出差报销需要发票。', '出差报销由部门经理审批。', '出差报销额度为500元。']
    def chat(model, messages, **kwargs):
        records = next(json.loads(line) for line in messages[1]['content'].splitlines() if line.startswith('[{'))
        claims = [dict(claim_id=f'c{i}', text=t, critical=True, cited_source_ids=[records[0]['source_id']])
                  for i, t in enumerate(facts)]
        return json.dumps(dict(answer='\n'.join(facts), claims=claims), ensure_ascii=False)
    monkeypatch.setattr('app.agent.generation_v2.chat_with_ollama', chat)
    start, _, _ = service
    with start([dict(id='travel', text=''.join(facts))]) as client:
        result = client.post('/agent/v2/chat', json={'question': question})
    body = result.json()
    assert result.status_code == 200 and body['mode'] == 'answered'
    assert len(body['claims']) == 3
    assert all(t in body['answer'] for t in facts)
    assert all(c['supported'] for c in body['citations'])
