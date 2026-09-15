import pytest

from app.security import demo_identity as identity


def setup_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(identity, "_now_epoch", lambda: 1_790_000_000)
    root = tmp_path / "identity"
    status = identity.initialize_demo_identity(
        root, issuer="test-issuer", audience="test-audience", token_lifetime_seconds=900
    )
    return root, status


def test_renew_preserves_keyring_and_refreshes_tokens(tmp_path, monkeypatch):
    root, before = setup_identity(tmp_path, monkeypatch)
    saved = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    monkeypatch.setattr(identity, "_now_epoch", lambda: 1_790_001_000)
    probes = []
    result = identity.renew_demo_identity(
        root,
        token_lifetime_seconds=900,
        snapshot_verifier=lambda token, kid: probes.append(kid) or True,
    )
    assert result.active_kid == before.active_kid and result.key_ids == before.key_ids
    assert probes == [before.active_kid]
    assert (root / identity._JWKS_FILE).read_bytes() == saved[identity._JWKS_FILE]
    assert (root / identity._HMAC_FILE).read_bytes() == saved[identity._HMAC_FILE]
    assert (root / identity._PERSONA_FILE).read_bytes() != saved[identity._PERSONA_FILE]
    assert identity.demo_identity_status(root).active_kid == before.active_kid


def test_rejected_renewal_does_not_change_files(tmp_path, monkeypatch):
    root, _ = setup_identity(tmp_path, monkeypatch)
    saved = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    with pytest.raises(identity.IdentityConfigurationError):
        identity.renew_demo_identity(
            root, token_lifetime_seconds=900, snapshot_verifier=lambda *a: False
        )
    assert {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()} == saved


@pytest.mark.parametrize("lifetime", [0, 901, True])
def test_renewal_cannot_extend_token_policy(tmp_path, monkeypatch, lifetime):
    root, _ = setup_identity(tmp_path, monkeypatch)
    with pytest.raises((ValueError, TypeError)):
        identity.renew_demo_identity(
            root, token_lifetime_seconds=lifetime, snapshot_verifier=lambda *a: True
        )


def test_renewal_interruption_recovers_same_committed_key(tmp_path, monkeypatch):
    root, before = setup_identity(tmp_path, monkeypatch)
    monkeypatch.setattr(identity, "_now_epoch", lambda: 1_790_001_000)
    original = identity._atomic_write

    def fail_once(path, payload):
        if path.name == identity._PERSONA_FILE:
            raise OSError("injected write interruption")
        return original(path, payload)

    monkeypatch.setattr(identity, "_atomic_write", fail_once)
    with pytest.raises(OSError):
        identity.renew_demo_identity(
            root, token_lifetime_seconds=900, snapshot_verifier=lambda *a: True
        )
    monkeypatch.setattr(identity, "_atomic_write", original)
    recovered = identity.demo_identity_status(root)
    assert recovered.active_kid == before.active_kid
    assert not (root / identity._OPERATION_FILE).exists()


def test_renewal_preserves_pending_rotation(tmp_path, monkeypatch):
    root, before = setup_identity(tmp_path, monkeypatch)
    staged = identity.rotate_demo_identity(root)
    result = identity.renew_demo_identity(
        root, token_lifetime_seconds=60, snapshot_verifier=lambda *a: True
    )
    assert result.pending_kid == staged.pending_kid and result.active_kid == before.active_kid


def test_renew_cli_requires_local_api_probe(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    from scripts import manage_demo_identity as cli

    root, before = setup_identity(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cli, "get_settings", lambda: SimpleNamespace(identity_jwks_path=root / "jwks.json")
    )
    seen = []
    monkeypatch.setattr(
        cli,
        "_api_snapshot_accepts_pending_key",
        lambda **kwargs: seen.append(kwargs["expected_kid"]) or True,
    )
    cli.main(["--directory", str(root), "renew", "--api-base-url", "http://127.0.0.1:8123"])
    output = capsys.readouterr().out
    assert seen == [before.active_kid] and "active_kid" in output and "tokens" not in output
