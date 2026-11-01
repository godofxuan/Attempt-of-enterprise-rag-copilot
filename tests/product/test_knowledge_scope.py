"""Explicit scope completion reaches real command revisions, retries and SQLite."""
import json
import pytest
from tests.product.test_turn_recovery import product
from tests.product.test_061_recovery import H, wait
from tests.vnext.test_conversations import SequenceModel


@pytest.mark.parametrize('already_selected', [False, True])
def test_complete_missing_scope_without_replaying_business_changes(tmp_path, already_selected):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        t = w.service.create({'kind': 'loan', 'execution_ceiling': 'PREVIEW_ONLY', 'confirmed': True})
        cid, tid = t['conversation_id'], t['task_id']
        model = SequenceModel([('update_parameters', {'changes': {'purpose': '保留的合成用途'},
            'turn_request': {'preview': False, 'knowledge_quote': '借用期限'}})], [('finish', {})])
        w.models.chat = model.chat
        text = '用途是保留的合成用途，先解释借用期限，不准备申请。'
        run = c.post(f'/api/conversations/{cid}/turns', headers=H,
                     json={'text': text, 'message_id': 'scope-recovery', 'detailed': True}).json()
        assert wait(c, run['id'])['status'] == 'succeeded'
        original = w.conversations.command({'conversation_id': cid, 'message_id': 'scope-recovery', 'text': text})
        assert original['kb_id'] is None and original['detailed'] is True
        facts = w.service.view(tid)['facts'].copy()
        revision = w.service.view(tid)['facts_revision']
        kb = w.library.create('明确补选的合成库')['id']
        if already_selected:
            # Persist the historical stranded shape; no test-only runtime shortcut.
            with w.conversations.db() as db:
                db.execute('UPDATE conversations SET kb_id=? WHERE id=?', (kb, cid))
        assert c.patch(f'/api/conversations/{cid}', headers=H, json={'kb_id': kb}).status_code == 200
        revised = w.conversations.command({'conversation_id': cid, 'message_id': 'scope-recovery', 'text': text})
        assert revised == {**original, 'kb_id': kb}
        # Explicit same-library completion is idempotent, not another revision.
        with w.conversations.db() as db:
            before = db.execute('SELECT count(*) FROM turn_commands').fetchone()[0]
        assert c.patch(f'/api/conversations/{cid}', headers=H, json={'kb_id': kb}).status_code == 200
        with w.conversations.db() as db:
            assert db.execute('SELECT count(*) FROM turn_commands').fetchone()[0] == before
        seen = []
        async def answer(k, q, **kw):
            seen.append((k, q, kw))
            return {'id': 'scope-synthetic', 'result': {'mode': 'not_found', 'answer': '合成无证据结果', 'sources': []}}
        w.library.answer = answer
        retried = c.post(f'/api/product/conversations/{cid}/turns/scope-recovery/retry', headers=H, json={})
        assert wait(c, retried.json()['id'])['status'] == 'succeeded'
        assert len(model.calls) == 2 and len(seen) == 1
        assert seen[0][0:2] == (kb, '借用期限') and seen[0][2]['detailed'] is True
        current = w.service.view(tid)
        assert current['facts'] == facts and current['facts_revision'] == revision
        assert not current['preview'] and not current['receipt']
        with w.service.store.transaction() as db:
            assert db.execute('SELECT count(*) FROM tickets').fetchone()[0] == 0


def test_completed_empty_and_nonempty_scope_are_not_rebound(tmp_path):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        a, b = w.library.create('A')['id'], w.library.create('B')['id']
        cid = w.conversations.create()['id']
        for mid, status, kb in [('done', 'DONE', None), ('bound', 'PARTIAL', a)]:
            w.conversations.append(cid, 'user', 'message', mid, turn_id=mid, status=status)
            with w.conversations.db() as db:
                db.execute('INSERT INTO turn_commands(turn_id,revision,conversation_id,payload) VALUES(?,?,?,?)',
                           (mid, 0, cid, json.dumps({'kb_id': kb, 'text': mid})))
        assert c.patch(f'/api/conversations/{cid}', headers=H, json={'kb_id': b}).status_code == 200
        with w.conversations.db() as db:
            rows = db.execute('SELECT payload,revision FROM turn_commands ORDER BY turn_id').fetchall()
        assert len(rows) == 2 and all(r['revision'] == 0 for r in rows)
        assert {json.loads(r['payload'])['kb_id'] for r in rows} == {None, a}


def test_status_closes_its_read_only_connection_immediately(tmp_path, monkeypatch):
    import sqlite3
    with product(tmp_path) as c:
        original = sqlite3.connect
        opened = []
        def connect(path, *args, **kwargs):
            db = original(path, *args, **kwargs)
            if kwargs.get('uri') and str(path).endswith('?mode=ro'):
                opened.append(db)
            return db
        monkeypatch.setattr(sqlite3, 'connect', connect)
        assert c.get('/api/status').status_code == 200
        assert opened
        async def assert_closed():
            for db in opened:
                with pytest.raises(sqlite3.ProgrammingError, match='closed'):
                    db.execute('SELECT 1')
        c.portal.call(assert_closed)
