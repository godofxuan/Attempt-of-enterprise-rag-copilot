"""HTTP integration; JWT is real local fixture, embedding/reranker/LLM are stubs."""
import pytest
from tests.api_v2.test_runtime_closure_flow import service


@pytest.mark.parametrize('profile', ['hybrid_default', 'safe_dense_raw20_bge', 'safe_dense_raw50_bge'])
@pytest.mark.parametrize('office', ['Elm', 'Quarry', 'Summit'])
def test_http_literal_office_scope_is_consistent(service, profile, office):
    start, seen, _ = service
    text = 'Elm office travel policy\nStaff grade | Elm lodging limit (CNY/night)\nG24 | 276.50'
    with start([dict(id='travel', text=text)], profile=profile) as client:
        r = client.post('/agent/v2/chat', json=dict(question=f'For {office} office staff grade G24, what is the lodging limit in CNY/night?'))
    assert r.status_code == 200
    body = r.json()
    assert body['mode'] == body['trace']['final_mode']
    assert body['stop_reason'] == body['trace']['stop_reason']
    if office == 'Elm':
        assert body['mode'] == 'answered'
        assert body['claims'] and all(c['supported'] for c in body['citations'])
        assert '276.50' in body['answer']
    else:
        assert body['mode'] == 'not_found'
        assert not body['claims'] and not body['citations'] and not body['sources']
        assert '276.50' not in body['answer']
        assert not seen['llm']
