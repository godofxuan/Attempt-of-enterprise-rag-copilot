"""Failure injection at the external answer boundary; real factory, runs and SQLite."""

from tests.product.test_turn_recovery import product
from tests.product.test_061_recovery import H, wait
from tests.vnext.test_conversations import SequenceModel
from app.service_desk.store import ServiceError


def test_unfinished_original_input_still_requires_review_before_read_recovery(tmp_path):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        kb = w.library.create('未完成输入合成场景')['id']
        task = w.service.create({'kind': 'loan', 'execution_ceiling': 'PREVIEW_ONLY', 'confirmed': True}, kb_id=kb)
        tid, cid = task['task_id'], task['conversation_id']
        calls = []

        async def broken_model(*args, **kwargs):
            calls.append(1)
            if len(calls) > 1:
                raise RuntimeError('SIMULATED_INTERPRETATION_FAILURE')
            return {'content': 'EXPLICIT_EXTERNAL_MODEL_DOUBLE', 'tool_calls': [{'function': {
                'name': 'update_parameters', 'arguments': {'changes': {'purpose': '已保存的合成用途'},
                'turn_request': {'preview': False, 'knowledge_quote': '借用期限'}}}}]}

        w.models.chat = broken_model
        first = c.post(f'/api/conversations/{cid}/turns', headers=H,
                       json={'text': '读取借用期限，把用途改为已保存的合成用途。', 'message_id': 'unfinished'})
        assert wait(c, first.json()['id'])['status'] == 'failed'
        retry = c.post(f'/api/product/conversations/{cid}/turns/unfinished/retry', headers=H, json={})
        assert wait(c, retry.json()['id'])['status'] == 'failed'
        shown = c.get(f'/api/product/tasks/{tid}').json()
        assert shown['next_action']['kind'] == 'resolve' and shown['pending_update']['id'] == 'unfinished'
        assert next(f['value'] for f in shown['fields'] if f['name'] == 'purpose') == '已保存的合成用途'
        assert len(calls) == 2 and not shown['preview'] and not shown['receipt']


def test_second_knowledge_failure_does_not_turn_applied_input_into_unresolved_changes(tmp_path):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        kb = w.library.create('重复瞬态失败合成场景')['id']
        task = w.service.create({'kind': 'loan', 'execution_ceiling': 'PREVIEW_ONLY', 'confirmed': True}, kb_id=kb)
        tid, cid = task['task_id'], task['conversation_id']
        calls = []

        async def answer(*args, **kwargs):
            calls.append((args, kwargs))
            if len(calls) <= 2:
                raise ServiceError('TRANSIENT_TOOL_FAILURE')
            return {'id': 'synthetic-recovered', 'result': {'mode': 'not_found', 'answer': '合成：无足够证据', 'sources': []}}

        w.library.answer = answer
        model = SequenceModel(
            [('update_parameters', {'changes': {}, 'turn_request': {'preview': False, 'knowledge_quote': '借用期限'}})],
            [('knowledge_answer', {'question': '借用期限'})], [('finish', {})],
        )
        w.models.chat = model.chat
        started = c.post(f'/api/conversations/{cid}/turns', headers=H,
                         json={'text': '先解释借用期限，日期未定。', 'message_id': 'read-recovery'})
        assert wait(c, started.json()['id'])['status'] == 'succeeded'
        retry = c.post(f'/api/product/conversations/{cid}/turns/read-recovery/retry', headers=H, json={})
        failed = wait(c, retry.json()['id'])
        assert failed['status'] == 'failed' and 'TRANSIENT_TOOL_FAILURE' in failed['error']
        shown = c.get(f'/api/product/tasks/{tid}').json()
        assert shown['pending_update'] is None, 'Knowledge failure must not manufacture unapplied business input'
        assert shown['next_action']['kind'] == 'retry_knowledge' and shown['turn_delivery']['retryable']
        retry = c.post(f'/api/product/conversations/{cid}/turns/read-recovery/retry', headers=H, json={})
        assert retry.status_code == 202 and wait(c, retry.json()['id'])['status'] == 'succeeded'
        final = c.get(f'/api/product/tasks/{tid}').json()
        assert final['turn_delivery']['status'] == 'complete'
        assert len(model.calls) == 3 and len(calls) == 3
        assert not final['preview'] and not final['receipt']
        assert all(not f['value'] for f in final['fields'])
        with w.service.store.transaction() as db:
            assert db.execute('SELECT count(*) FROM tickets').fetchone()[0] == 0
            assert db.execute('SELECT count(*) FROM action_proposals').fetchone()[0] == 0
