"""Current product/SQLite; model choices and failing external knowledge are explicit doubles."""
from contextlib import contextmanager
import pytest
from tests.product.test_turn_recovery import product
from tests.product.test_061_recovery import wait, H, reply
from tests.vnext.test_conversations import SequenceModel
from tests.vnext.test_service_lifecycle import create
from app.service_desk.store import ServiceError


def test_explicit_preparation_is_the_same_guarded_usecase_without_chat(tmp_path):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        task = create(w.service)
        path = '/api/product/tasks/' + task['task_id'] + '/prepare'
        request = {'asset_id': 'loan-laptop-1', 'expected_facts_revision': task['facts_revision']}
        first = c.post(path, headers=H, json=request)
        assert first.status_code == 200, first.text
        view = first.json()
        assert view['preview'] and not view['receipt']
        second = c.post(path, headers=H, json={**request, 'expected_facts_revision': view['revision']})
        assert second.json()['preview']['proposal_id'] == view['preview']['proposal_id']
        with w.service.store.transaction() as db:
            assert db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0] == 0
            assert db.execute('SELECT COUNT(*) FROM tickets').fetchone()[0] == 0
        readonly = create(w.service, 'READ_ONLY')
        denied = c.post('/api/product/tasks/' + readonly['task_id'] + '/prepare', headers=H,
                        json={'asset_id': 'loan-laptop-1', 'expected_facts_revision': readonly['facts_revision']})
        assert denied.status_code == 409 and denied.json()['error']['code'] == 'EXECUTION_CEILING'


@pytest.mark.parametrize('failure', [True, False])
def test_partial_turn_retries_only_missing_knowledge_and_preserves_latest_dates(tmp_path, failure):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        kb = w.library.create('明确的知识边界替身')['id']
        task = create(w.service, 'PREVIEW_ONLY'); tid = task['task_id']; cid = task['conversation_id']
        w.conversations.update(cid, {'kb_id': kb})
        called = []
        async def answer(kb_id, question, **kw):
            called.append((question, kw))
            if failure and len(called) == 1:
                raise ServiceError('EVIDENCE_INSUFFICIENT')
            result = reply(question)
            result['result']['mode'] = 'partial'  # explicit external boundary, no invented citations
            return result
        w.library.answer = answer
        intent = {'preview': True, 'knowledge_quote': '解释押金制度'}
        operations = [('prepare_preview', {'asset_id':'loan-laptop-1', 'turn_request': intent})]
        if failure:
            operations.append(('knowledge_answer', {'question':'解释押金制度'}))
        # In the omitted case the model declares the request but fails to
        # choose its knowledge tool even after the one targeted feedback.
        model = SequenceModel(operations, [('finish', {})])
        w.models.chat = model.chat
        run = c.post(f'/api/conversations/{cid}/turns', headers=H,
                     json={'text':'请准备借用预览，并解释押金制度，不提交。', 'message_id':'mixed-current'})
        done = wait(c, run.json()['id'])
        assert done['status'] == 'succeeded'
        current = w.service.view(tid)
        assert current['preview'] and not current['receipt']
        user = next(t for t in w.conversations.turns(cid) if t['id'] == 'mixed-current')
        assert user['status'] == 'PARTIAL' and user['payload']['turn_delivery']['retryable']
        old_preview = current['preview']['proposal_id']
        # Explicit later edit invalidates only the preview, never replays the
        # original input while retrying explanation.
        changed = w.service.facts(tid, {'purpose':'后来明确修改的用途'}, current['facts_revision'])
        async def forbidden(*args, **kw):
            raise AssertionError('Retry explanation must not call the service-choice model')
        w.models.chat = forbidden
        retry = c.post(f'/api/product/conversations/{cid}/turns/mixed-current/retry', headers=H, json={})
        assert retry.status_code == 202, retry.text
        result = wait(c, retry.json()['id'])
        assert result['status'] == 'succeeded', result['error']
        latest = w.service.view(tid)
        assert latest['facts']['purpose'] == '后来明确修改的用途'
        assert latest['knowledge_result'] and not latest['preview']
        assert latest['facts_revision'] == changed['facts_revision'] and not latest['receipt']
        assert called[-1][0] == '解释押金制度'
        partial = next(t for t in w.conversations.turns(cid) if t['id'] == 'mixed-current')
        assert partial['status'] == 'PARTIAL'
        assert partial['payload']['turn_delivery']['pending'] == ['preview']
        prepared = c.post(f'/api/product/tasks/{tid}/prepare', headers=H, json={
            'asset_id': 'loan-laptop-1', 'expected_facts_revision': latest['facts_revision'],
        })
        assert prepared.status_code == 200, prepared.text
        assert prepared.json()['preview']['proposal_id'] != old_preview
        final = next(t for t in w.conversations.turns(cid) if t['id'] == 'mixed-current')
        assert final['status'] == 'DONE'
        assert final['payload']['turn_delivery']['pending'] == []
        with w.service.store.transaction() as db:
            assert db.execute('SELECT COUNT(*) FROM action_proposals').fetchone()[0] == 2
            assert db.execute('SELECT COUNT(*) FROM tickets').fetchone()[0] == 0
            assert db.execute('SELECT COUNT(*) FROM action_proposals WHERE proposal_id=?', (old_preview,)).fetchone()[0] == 1


def test_command_does_not_hold_a_connection_during_domain_projection(tmp_path, monkeypatch):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        task = create(w.service)
        original_db, original_view = w.conversations.db, w.service.view
        held = []
        @contextmanager
        def tracked():
            with original_db() as db:
                held.append(db)
                try: yield db
                finally: held.pop()
        def view(tid):
            assert not held, 'Command must close its snapshot before opening a domain connection'
            return original_view(tid)
        monkeypatch.setattr(w.conversations, 'db', tracked)
        monkeypatch.setattr(w.service, 'view', view)
        result = w.conversations.command({'conversation_id':task['conversation_id'], 'text':'继续', 'message_id':'connection-boundary'})
        assert result['task_id'] == task['task_id']


def test_readonly_model_brief_cannot_add_a_preview_and_can_correct_without_repeating_reads(tmp_path):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        task = create(w.service, 'READ_ONLY'); cid = task['conversation_id']
        model = SequenceModel(
            [('loan_policy', {}), ('assets_search', {}), ('tickets_list_mine', {}),
             ('finish', {'turn_request': {'preview': True, 'knowledge_quote': ''}})],
            [('finish', {'turn_request': {'preview': False, 'knowledge_quote': ''}})],
        )
        w.models.chat = model.chat
        run = c.post(f'/api/conversations/{cid}/turns', headers=H,
                     json={'text': '只查询本人资格、库存和本人申请，不准备。', 'message_id': 'readonly-brief'})
        done = wait(c, run.json()['id'])
        assert done['status'] == 'succeeded', done.get('error')
        current = w.service.view(task['task_id'])
        assert not current['preview'] and not current['receipt']
        turn = next(t for t in w.conversations.turns(cid) if t['id'] == 'readonly-brief')
        assert turn['status'] == 'DONE' and turn['payload']['turn_delivery']['pending'] == []
        assert len(model.calls) == 2
        assert [o['tool'] for o in current['observations']].count('assets.search') == 1
        assert any(e['kind'] == 'request_brief_rejected' for e in w.runs.events(run.json()['id']))
        with w.service.store.transaction() as db:
            assert db.execute('SELECT COUNT(*) FROM action_proposals').fetchone()[0] == 0
            assert db.execute('SELECT COUNT(*) FROM tickets').fetchone()[0] == 0
        # Saved metadata from the measured 219b failure must be recoverable,
        # without silently rewriting its original model proposal as correct.
        legacy = w.conversations.coordinator.delivery('readonly-brief')
        legacy['requested']['preview'] = True
        w.conversations.coordinator.save_delivery('readonly-brief', legacy)
        with w.conversations.db() as db:
            db.execute("UPDATE conversation_turns SET status='PARTIAL' WHERE id='readonly-brief'")
        assert not w.conversations.coordinator.delivery('readonly-brief')['accepted']
        w.models.chat = SequenceModel([('finish', {'turn_request': {'preview': False, 'knowledge_quote': ''}})]).chat
        resumed = c.post(f'/api/product/conversations/{cid}/turns/readonly-brief/retry', headers=H, json={})
        assert resumed.status_code == 202, resumed.text
        assert wait(c, resumed.json()['id'])['status'] == 'succeeded'
        final = w.conversations.coordinator.for_task(w.service.view(task['task_id']))
        assert final['status'] == 'complete' and final['rejected_prior_request']['preview']
