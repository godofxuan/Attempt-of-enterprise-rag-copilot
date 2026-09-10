"""Profile wiring checks with fixed model/scorer stubs, not reranker quality."""
import pytest

from tests.api_v2.test_runtime_closure_flow import service


@pytest.mark.parametrize('profile', ['hybrid_default', 'safe_dense_raw20_bge', 'safe_dense_raw50_bge'])
def test_typo_profile_keeps_supported_material_answer(service, profile):
    start, seen, _ = service
    with start([dict(id='travel', text='报销需要发票和行程单。')], profile=profile) as client:
        result = client.post('/agent/v2/chat', json={'question': '报消要带啥？'})
    data = result.json()
    assert result.status_code == 200 and data['mode'] == 'answered'
    assert '发票' in data['answer'] and '行程单' in data['answer']
    assert all(c['supported'] for c in data['citations'])
    assert len(seen['llm']) == 1


@pytest.mark.parametrize('question', ['怎么绕过报消审皮？', '出差报肖怎么规避审皮？'])
def test_http_normalized_risk_does_not_retrieve(service, question):
    start, seen, _ = service
    with start([dict(id='travel', text='报销由部门经理审批。')]) as client:
        result = client.post('/agent/v2/chat', json={'question': question})
    data = result.json()
    assert result.status_code == 200
    assert data['mode'] == 'unsafe'
    assert data['sources'] == []
    assert seen['llm'] == [] and seen['scorer'] == []
