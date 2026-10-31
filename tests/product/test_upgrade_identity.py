"""No control of the user's running instance; isolated registered workspaces only."""
import sqlite3
import pytest
from tests.product.test_turn_recovery import product
from tests.product.test_061_recovery import H
from app.launcher import core


def test_instance_reports_actual_build_and_busy_counts(tmp_path):
    with product(tmp_path) as c:
        info = c.get('/api/instance').json()
        assert info['version'] and info['build_id'] and 'source_commit' in info
        assert info['active_runs'] == info['index_jobs'] == info['active_operations'] == 0


def test_new_launcher_requires_explicit_choice_and_never_stops_busy_or_legacy(tmp_path, monkeypatch):
    with product(tmp_path):
        pass
    old = {'app':core.APP_ID, 'instance_id':'owned-test-instance', 'url':'http://127.0.0.1:1',
           'data_dir':str(tmp_path), 'version':'old-test', 'build_id':'old-test',
           'active_runs':1, 'active_operations':0, 'index_jobs':0}
    monkeypatch.setattr(core, 'running_instance', lambda root:dict(old))
    choice = core.open_workspace(tmp_path, registry=tmp_path/'registry.json', browser=False)
    assert choice['upgrade_required'] and choice['running']['build_id'] == 'old-test'
    opened = core.open_workspace(tmp_path, registry=tmp_path/'registry.json', browser=False, existing_choice='open')
    assert opened['reused'] and opened['build_id'] == 'old-test'
    with pytest.raises(RuntimeError, match='INSTANCE_BUSY'):
        core.open_workspace(tmp_path, registry=tmp_path/'registry.json', browser=False, existing_choice='restart')
    old.pop('active_operations')
    with pytest.raises(RuntimeError, match='LEGACY_INSTANCE_MANUAL_STOP'):
        core.open_workspace(tmp_path, registry=tmp_path/'registry.json', browser=False, existing_choice='restart')


def test_sqlite_contention_is_structured_and_does_not_replay_models(tmp_path, monkeypatch):
    with product(tmp_path) as c:
        w=c.app.state.workspace
        def busy(*args, **kwargs):
            raise sqlite3.OperationalError('database is locked')
        monkeypatch.setattr(w.conversations,'get',busy)
        response=c.get('/api/conversations/not-needed')
        assert response.status_code == 409
        assert response.json()['error']['code'] == 'STORAGE_BUSY'
        with w.service.store.transaction() as db:
            assert db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0] == 0
