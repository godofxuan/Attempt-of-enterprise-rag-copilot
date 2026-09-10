"""Real service route and identity/index contracts; model transport is a fixed stub."""
from tests.api_v2.test_runtime_closure_flow import service


def test_http_coverage_notes_and_trace_agree(service):
    start, seen, _ = service
    with start([dict(id='travel', text='出差报销由部门经理审批。')]) as client:
        result = client.post('/agent/v2/chat', json={
            'question': '出差报销需要哪些材料、由谁审批、额度是多少？'
        })
    assert result.status_code == 200
    body = result.json()
    assert body['mode'] == 'partial'
    assert body['stop_reason'] == 'partial_evidence'
    assert '材料' in body['answer'] and '额度' in body['answer']
    assert body['trace']['query_need_coverage']['missing'] == 2
    assert body['trace']['final_mode'] == body['mode']
    assert body['claims'] and all(c['supported'] for c in body['citations'])
    assert len(seen['llm']) == 1


def test_http_personal_eligibility_requests_facts(service):
    start, _, _ = service
    with start([dict(id='travel', text='出差报销需要发票。')]) as client:
        result = client.post('/agent/v2/chat', json={'question': '我这次出差能不能报销？'})
    body = result.json()
    assert result.status_code == 200 and body['mode'] == 'partial'
    assert '请补充' in body['answer']
    assert body['trace']['query_need_coverage']['missing'] == 1
