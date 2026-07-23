from __future__ import annotations

import base64
import json
import multiprocessing
import os
from pathlib import Path

import pytest

from app.security import demo_identity
from app.security.demo_identity import (
    demo_identity_status,
    initialize_demo_identity,
    retire_demo_identity_key,
    rotate_demo_identity,
)
from app.security.identity import (
    AuthenticationFailure,
    IdentityConfigurationError,
    LocalJwksKeyProvider,
    LocalJwtIdentityVerifier,
)
from app.security.token_source import (
    BearerTokenFileSource,
    PersonaTokenBundleSource,
)


def _verifier(directory: Path) -> LocalJwtIdentityVerifier:
    return LocalJwtIdentityVerifier(
        provider=LocalJwksKeyProvider.load(
            directory / "jwks.json", max_bytes=65_536, max_keys=8
        ),
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        algorithm="RS256",
        token_type="at+jwt",
        clock_skew_seconds=30,
        max_lifetime_seconds=900,
        max_token_bytes=8_192,
    )


def _activate_staged(
    directory: Path,
    status: demo_identity.DemoIdentityStatus,
) -> demo_identity.DemoIdentityStatus:
    assert status.pending_kid is not None
    snapshot = _verifier(directory)

    def snapshot_accepts(token: str, expected_kid: str) -> bool:
        try:
            principal = snapshot.verify_bearer(f"Bearer {token}")
        except AuthenticationFailure:
            return False
        return principal.key_id == expected_kid

    return demo_identity.activate_demo_identity(
        directory,
        kid=status.pending_kid,
        token_lifetime_seconds=900,
        snapshot_verifier=snapshot_accepts,
    )


def _rotate_in_process(directory: str, results) -> None:
    try:
        status = rotate_demo_identity(Path(directory))
        results.put(("ok", status.active_kid))
    except Exception as exc:
        results.put(("error", type(exc).__name__))


def test_demo_identity_initialization_separates_persona_and_operator_tokens(
    tmp_path: Path,
) -> None:
    status = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    verifier = _verifier(tmp_path)
    personas = PersonaTokenBundleSource(tmp_path / "persona_tokens.json")
    employee = verifier.verify_bearer(
        f"Bearer {personas.get_token('user_employee')}"
    )
    operator = verifier.verify_bearer(
        "Bearer " + BearerTokenFileSource(tmp_path / "operator_token.txt").get_token()
    )

    assert employee.subject == "user_employee"
    assert employee.roles == []
    assert operator.subject == "demo-operator"
    assert operator.roles == ["rag.operator"]
    assert status.active_kid == employee.key_id == operator.key_id
    bundle_text = (tmp_path / "persona_tokens.json").read_text(encoding="utf-8")
    assert "demo-operator" not in bundle_text
    load_user = verifier.verify_bearer(
        "Bearer "
        + BearerTokenFileSource(tmp_path / "load_user_token.txt").get_token()
    )
    assert load_user.subject == "load-demo-employee"
    assert load_user.roles == []
    jwks = json.loads((tmp_path / "jwks.json").read_text(encoding="utf-8"))
    assert len(jwks["keys"]) == 1
    assert not {"d", "p", "q", "dp", "dq", "qi"}.intersection(jwks["keys"][0])
    assert (tmp_path / "feedback_actor_hmac.key").stat().st_size == 32


def test_demo_identity_rotation_overlaps_then_retires_old_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    initial = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    old_token = PersonaTokenBundleSource(tmp_path / "persona_tokens.json").get_token(
        "user_employee"
    )

    staged = rotate_demo_identity(tmp_path)
    overlap_verifier = _verifier(tmp_path)
    rotated = _activate_staged(tmp_path, staged)
    new_token = PersonaTokenBundleSource(tmp_path / "persona_tokens.json").get_token(
        "user_employee"
    )

    assert rotated.active_kid != initial.active_kid
    assert set(rotated.key_ids) == {initial.active_kid, rotated.active_kid}
    assert overlap_verifier.verify_bearer(f"Bearer {old_token}").key_id == initial.active_kid
    assert overlap_verifier.verify_bearer(f"Bearer {new_token}").key_id == rotated.active_kid

    retire_not_before = dict(rotated.retirement_not_before)[initial.active_kid]
    with pytest.raises(ValueError, match="overlap window remains active"):
        retire_demo_identity_key(tmp_path, kid=initial.active_kid)

    monkeypatch.setattr(demo_identity, "_now_epoch", lambda: retire_not_before)
    retired = retire_demo_identity_key(tmp_path, kid=initial.active_kid)
    retired_verifier = _verifier(tmp_path)
    assert retired.key_ids == (rotated.active_kid,)
    with pytest.raises(AuthenticationFailure):
        retired_verifier.verify_bearer(f"Bearer {old_token}")
    assert retired_verifier.verify_bearer(f"Bearer {new_token}").key_id == rotated.active_kid
    assert not (tmp_path / f"private-{initial.active_kid}.pem").exists()


def test_emergency_retirement_requires_confirmation_and_is_auditable(
    tmp_path: Path,
) -> None:
    initial = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    staged = rotate_demo_identity(tmp_path)
    activated = _activate_staged(tmp_path, staged)

    with pytest.raises(ValueError, match="exact confirmation phrase"):
        retire_demo_identity_key(
            tmp_path,
            kid=initial.active_kid,
            emergency_revoke=True,
        )

    retired = retire_demo_identity_key(
        tmp_path,
        kid=initial.active_kid,
        emergency_revoke=True,
        emergency_confirmation=demo_identity.EMERGENCY_RETIRE_CONFIRMATION,
    )
    manifest = json.loads(
        (tmp_path / "identity_manifest.json").read_text(encoding="ascii")
    )

    assert activated.emergency_revocation_count == 0
    assert retired.emergency_revocation_count == 1
    assert retired.retirement_not_before == ()
    assert manifest["emergency_revocations"] == [
        {
            "kid": initial.active_kid,
            "revoked_at": manifest["emergency_revocations"][0]["revoked_at"],
        }
    ]


def test_retirement_deadline_uses_max_skew_despite_later_config_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    clock = [demo_identity._now_epoch()]
    monkeypatch.setattr(demo_identity, "_now_epoch", lambda: clock[0])
    initial = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    staged = rotate_demo_identity(tmp_path)
    activated = _activate_staged(tmp_path, staged)
    retire_not_before = dict(activated.retirement_not_before)[initial.active_kid]

    assert retire_not_before == (
        clock[0]
        + demo_identity._MAX_TOKEN_LIFETIME_SECONDS
        + demo_identity.IDENTITY_CLOCK_SKEW_MAX_SECONDS
    )
    clock[0] = retire_not_before - 1
    with pytest.raises(ValueError, match="overlap window remains active"):
        retire_demo_identity_key(tmp_path, kid=initial.active_kid)

    clock[0] = retire_not_before
    retired = retire_demo_identity_key(tmp_path, kid=initial.active_kid)
    assert initial.active_kid not in retired.key_ids


def test_emergency_retirement_journal_recovers_after_overlap_deadline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    clock = [demo_identity._now_epoch()]
    monkeypatch.setattr(demo_identity, "_now_epoch", lambda: clock[0])
    initial = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    staged = rotate_demo_identity(tmp_path)
    activated = _activate_staged(tmp_path, staged)
    retire_not_before = dict(activated.retirement_not_before)[initial.active_kid]
    original_write = demo_identity._atomic_write
    failed = False

    def fail_first_jwks_write(path: Path, payload: bytes) -> None:
        nonlocal failed
        if Path(path).name == "jwks.json" and not failed:
            failed = True
            raise OSError("injected emergency retirement publication failure")
        original_write(path, payload)

    monkeypatch.setattr(demo_identity, "_atomic_write", fail_first_jwks_write)
    with pytest.raises(OSError, match="emergency retirement publication"):
        retire_demo_identity_key(
            tmp_path,
            kid=initial.active_kid,
            emergency_revoke=True,
            emergency_confirmation=demo_identity.EMERGENCY_RETIRE_CONFIRMATION,
        )
    journal = json.loads(
        (tmp_path / ".identity-operation.json").read_text(encoding="ascii")
    )
    assert journal["retirement_authorization"] == {
        "mode": "emergency",
        "authorized_at": clock[0],
    }

    clock[0] = retire_not_before + 1
    monkeypatch.setattr(demo_identity, "_atomic_write", original_write)
    recovered = demo_identity_status(tmp_path)

    assert initial.active_kid not in recovered.key_ids
    assert recovered.emergency_revocations == (
        (initial.active_kid, journal["retirement_authorization"]["authorized_at"]),
    )
    assert not (tmp_path / ".identity-operation.json").exists()


def test_multiple_rotations_preserve_and_retire_each_old_key_window(
    tmp_path: Path,
    monkeypatch,
) -> None:
    clock = [demo_identity._now_epoch()]
    monkeypatch.setattr(demo_identity, "_now_epoch", lambda: clock[0])
    initial = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    first_active = _activate_staged(tmp_path, rotate_demo_identity(tmp_path))
    second_active = _activate_staged(tmp_path, rotate_demo_identity(tmp_path))
    deadlines = dict(second_active.retirement_not_before)

    assert set(deadlines) == {initial.active_kid, first_active.active_kid}
    assert second_active.active_kid not in deadlines

    clock[0] = max(deadlines.values())
    after_first = retire_demo_identity_key(tmp_path, kid=initial.active_kid)
    after_second = retire_demo_identity_key(
        tmp_path,
        kid=first_active.active_kid,
    )

    assert set(after_first.key_ids) == {
        first_active.active_kid,
        second_active.active_kid,
    }
    assert after_second.key_ids == (second_active.active_kid,)
    assert after_second.retirement_not_before == ()


def test_rotation_stages_verification_key_without_replacing_client_tokens(
    tmp_path: Path,
) -> None:
    initial = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    running_verifier = _verifier(tmp_path)
    client_files = (
        "persona_tokens.json",
        "operator_token.txt",
        "load_user_token.txt",
    )
    before_clients = {
        name: (tmp_path / name).read_bytes()
        for name in client_files
    }

    staged = rotate_demo_identity(tmp_path)

    assert staged.active_kid == initial.active_kid
    assert staged.pending_kid is not None
    assert staged.pending_kid != initial.active_kid
    assert set(staged.key_ids) == {initial.active_kid, staged.pending_kid}
    assert staged.restart_required is True
    assert {
        name: (tmp_path / name).read_bytes()
        for name in client_files
    } == before_clients
    current_token = PersonaTokenBundleSource(
        tmp_path / "persona_tokens.json"
    ).get_token("user_employee")
    assert (
        running_verifier.verify_bearer(f"Bearer {current_token}").key_id
        == initial.active_kid
    )
    assert set(_verifier(tmp_path).provider.key_ids) == {
        initial.active_kid,
        staged.pending_kid,
    }


def test_staged_rotation_requires_restarted_snapshot_before_token_activation(
    tmp_path: Path,
) -> None:
    initial = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    old_snapshot = _verifier(tmp_path)
    staged = rotate_demo_identity(tmp_path)
    assert staged.pending_kid is not None
    client_files = (
        "persona_tokens.json",
        "operator_token.txt",
        "load_user_token.txt",
    )
    staged_clients = {
        name: (tmp_path / name).read_bytes()
        for name in client_files
    }

    def accepted_by(verifier: LocalJwtIdentityVerifier):
        def verify(token: str, expected_kid: str) -> bool:
            try:
                principal = verifier.verify_bearer(f"Bearer {token}")
            except AuthenticationFailure:
                return False
            return principal.key_id == expected_kid

        return verify

    with pytest.raises(
        IdentityConfigurationError,
        match="not loaded by the API snapshot",
    ):
        demo_identity.activate_demo_identity(
            tmp_path,
            kid=staged.pending_kid,
            token_lifetime_seconds=900,
            snapshot_verifier=accepted_by(old_snapshot),
        )

    assert {
        name: (tmp_path / name).read_bytes()
        for name in client_files
    } == staged_clients

    restarted_snapshot = _verifier(tmp_path)
    activated = demo_identity.activate_demo_identity(
        tmp_path,
        kid=staged.pending_kid,
        token_lifetime_seconds=900,
        snapshot_verifier=accepted_by(restarted_snapshot),
    )
    new_token = PersonaTokenBundleSource(
        tmp_path / "persona_tokens.json"
    ).get_token("user_employee")

    assert activated.active_kid == staged.pending_kid
    assert activated.pending_kid is None
    assert activated.restart_required is False
    assert (
        restarted_snapshot.verify_bearer(f"Bearer {new_token}").key_id
        == staged.pending_kid
    )
    with pytest.raises(AuthenticationFailure):
        old_snapshot.verify_bearer(f"Bearer {new_token}")
    assert initial.active_kid in activated.key_ids


def test_interrupted_activation_recovers_the_staged_key_and_new_tokens(
    tmp_path: Path,
    monkeypatch,
) -> None:
    initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    staged = rotate_demo_identity(tmp_path)
    assert staged.pending_kid is not None
    restarted_snapshot = _verifier(tmp_path)

    def snapshot_accepts(token: str, expected_kid: str) -> bool:
        return (
            restarted_snapshot.verify_bearer(f"Bearer {token}").key_id
            == expected_kid
        )

    original_write = demo_identity._atomic_write
    failed = False

    def fail_first_manifest(path: Path, payload: bytes) -> None:
        nonlocal failed
        if Path(path).name == "identity_manifest.json" and not failed:
            failed = True
            raise OSError("injected activation publication failure")
        original_write(path, payload)

    monkeypatch.setattr(demo_identity, "_atomic_write", fail_first_manifest)
    with pytest.raises(OSError, match="activation publication"):
        demo_identity.activate_demo_identity(
            tmp_path,
            kid=staged.pending_kid,
            token_lifetime_seconds=900,
            snapshot_verifier=snapshot_accepts,
        )
    with pytest.raises(IdentityConfigurationError, match="not committed"):
        PersonaTokenBundleSource(tmp_path / "persona_tokens.json").get_token(
            "user_employee"
        )

    monkeypatch.setattr(demo_identity, "_atomic_write", original_write)
    recovered = demo_identity_status(tmp_path)
    new_token = PersonaTokenBundleSource(
        tmp_path / "persona_tokens.json"
    ).get_token("user_employee")

    assert recovered.active_kid == staged.pending_kid
    assert recovered.pending_kid is None
    assert recovered.restart_required is True
    assert (
        restarted_snapshot.verify_bearer(f"Bearer {new_token}").key_id
        == staged.pending_kid
    )


def test_activation_journal_rejects_a_shortened_retirement_deadline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    initialized = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    staged = rotate_demo_identity(tmp_path)
    assert staged.pending_kid is not None
    snapshot = _verifier(tmp_path)
    original_write = demo_identity._atomic_write
    failed = False

    def snapshot_accepts(token: str, expected_kid: str) -> bool:
        return (
            snapshot.verify_bearer(f"Bearer {token}").key_id
            == expected_kid
        )

    def fail_first_manifest(path: Path, payload: bytes) -> None:
        nonlocal failed
        if Path(path).name == "identity_manifest.json" and not failed:
            failed = True
            raise OSError("injected activation publication failure")
        original_write(path, payload)

    monkeypatch.setattr(demo_identity, "_atomic_write", fail_first_manifest)
    with pytest.raises(OSError, match="activation publication"):
        demo_identity.activate_demo_identity(
            tmp_path,
            kid=staged.pending_kid,
            token_lifetime_seconds=900,
            snapshot_verifier=snapshot_accepts,
        )
    monkeypatch.setattr(demo_identity, "_atomic_write", original_write)

    manifest_path = tmp_path / "identity_manifest.json"
    committed_manifest = manifest_path.read_bytes()
    journal_path = tmp_path / ".identity-operation.json"
    journal = json.loads(journal_path.read_text(encoding="ascii"))
    target = json.loads(
        base64.b64decode(
            journal["writes"]["identity_manifest.json"],
            validate=True,
        ).decode("ascii")
    )
    target["retire_not_before"][initialized.active_kid] = 1
    journal["writes"]["identity_manifest.json"] = base64.b64encode(
        demo_identity._json_bytes(target)
    ).decode("ascii")
    journal_path.write_text(json.dumps(journal), encoding="ascii")

    with pytest.raises(IdentityConfigurationError, match="journal is invalid"):
        demo_identity._recover_pending_operation(tmp_path)

    assert manifest_path.read_bytes() == committed_manifest


def test_retiring_pending_key_cancels_stage_without_replacing_client_tokens(
    tmp_path: Path,
) -> None:
    initial = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    before_clients = (
        tmp_path / "persona_tokens.json"
    ).read_bytes()
    staged = rotate_demo_identity(tmp_path)
    assert staged.pending_kid is not None

    cancelled = retire_demo_identity_key(
        tmp_path,
        kid=staged.pending_kid,
    )

    assert cancelled.active_kid == initial.active_kid
    assert cancelled.pending_kid is None
    assert cancelled.key_ids == (initial.active_kid,)
    assert cancelled.restart_required is True
    assert (
        tmp_path / "persona_tokens.json"
    ).read_bytes() == before_clients
    assert not (
        tmp_path / f"private-{staged.pending_kid}.pem"
    ).exists()


def test_demo_identity_refuses_accidental_reinitialization(tmp_path: Path) -> None:
    initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )

    with pytest.raises(FileExistsError):
        initialize_demo_identity(
            tmp_path,
            issuer="https://identity.localhost/",
            audience="enterprise-rag-api",
            token_lifetime_seconds=900,
        )


def test_status_has_no_permission_or_lock_side_effects_on_non_identity_directory(
    tmp_path: Path,
) -> None:
    ordinary = tmp_path / "ordinary"
    ordinary.mkdir()
    note = ordinary / "notes.txt"
    note.write_bytes(b"must-remain")
    before_private = demo_identity._private_directory_permissions_are_secure(
        ordinary
    )
    before_entries = sorted(path.name for path in ordinary.iterdir())
    before_directory_mode = ordinary.stat().st_mode
    before_note_mode = note.stat().st_mode

    with pytest.raises(IdentityConfigurationError):
        demo_identity_status(ordinary)

    assert (
        demo_identity._private_directory_permissions_are_secure(ordinary)
        is before_private
    )
    assert sorted(path.name for path in ordinary.iterdir()) == before_entries
    assert ordinary.stat().st_mode == before_directory_mode
    assert note.stat().st_mode == before_note_mode
    assert note.read_bytes() == b"must-remain"


def test_status_has_no_side_effects_for_invalid_manifest_marker(
    tmp_path: Path,
) -> None:
    ordinary = tmp_path / "ordinary-with-marker"
    ordinary.mkdir()
    manifest = ordinary / "identity_manifest.json"
    manifest.write_text('{"not": "an identity manifest"}', encoding="ascii")
    before_private = demo_identity._private_directory_permissions_are_secure(
        ordinary
    )
    before_entries = sorted(path.name for path in ordinary.iterdir())
    before_directory_mode = ordinary.stat().st_mode
    before_manifest_mode = manifest.stat().st_mode

    with pytest.raises(IdentityConfigurationError):
        demo_identity_status(ordinary)

    assert (
        demo_identity._private_directory_permissions_are_secure(ordinary)
        is before_private
    )
    assert sorted(path.name for path in ordinary.iterdir()) == before_entries
    assert ordinary.stat().st_mode == before_directory_mode
    assert manifest.stat().st_mode == before_manifest_mode
    assert manifest.read_text(encoding="ascii") == (
        '{"not": "an identity manifest"}'
    )


def test_demo_identity_rotation_refuses_to_overflow_keyring_without_writes(
    tmp_path: Path,
) -> None:
    initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    for _ in range(7):
        staged = rotate_demo_identity(tmp_path)
        _activate_staged(tmp_path, staged)
    before = {
        path.name: path.read_bytes()
        for path in tmp_path.iterdir()
        if path.is_file()
    }

    with pytest.raises(ValueError, match="keyring is full"):
        rotate_demo_identity(tmp_path)

    after = {
        path.name: path.read_bytes()
        for path in tmp_path.iterdir()
        if path.is_file()
    }
    assert after == before


def test_demo_identity_rejects_manifest_private_key_path_escape(tmp_path: Path) -> None:
    initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    outside = tmp_path.parent / f"{tmp_path.name}-outside.pem"
    outside.write_bytes(b"must-survive")
    manifest_path = tmp_path / "identity_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    escaped_kid = f"../../../{outside.stem}"
    manifest["keys"][0]["kid"] = escaped_kid
    manifest["keys"][0]["private_key_file"] = f"private-{escaped_kid}.pem"
    manifest["keys"][0]["public_jwk"]["kid"] = escaped_kid
    manifest["active_kid"] = escaped_kid
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(IdentityConfigurationError, match="manifest is invalid"):
        initialize_demo_identity(
            tmp_path,
            issuer="https://identity.localhost/",
            audience="enterprise-rag-api",
            token_lifetime_seconds=900,
            force=True,
        )

    assert outside.read_bytes() == b"must-survive"


def test_demo_identity_rejects_redirecting_ancestor_directory(tmp_path: Path) -> None:
    actual_parent = tmp_path / "actual"
    actual_parent.mkdir()
    redirecting_parent = tmp_path / "redirect"
    try:
        redirecting_parent.symlink_to(actual_parent, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink creation is not available")

    with pytest.raises(IdentityConfigurationError, match="directory is unsafe"):
        initialize_demo_identity(
            redirecting_parent / "identity",
            issuer="https://identity.localhost/",
            audience="enterprise-rag-api",
            token_lifetime_seconds=900,
        )

    assert not (actual_parent / "identity" / "identity_manifest.json").exists()


def test_failed_retirement_is_recoverable_and_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    initial = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    old_token = PersonaTokenBundleSource(tmp_path / "persona_tokens.json").get_token(
        "user_employee"
    )
    staged = rotate_demo_identity(tmp_path)
    activated = _activate_staged(tmp_path, staged)
    retire_not_before = dict(activated.retirement_not_before)[initial.active_kid]
    monkeypatch.setattr(demo_identity, "_now_epoch", lambda: retire_not_before)
    original_write = demo_identity._atomic_write
    failed = False

    def fail_first_jwks_write(path: Path, payload: bytes) -> None:
        nonlocal failed
        if Path(path).name == "jwks.json" and not failed:
            failed = True
            raise OSError("injected JWKS publication failure")
        original_write(path, payload)

    monkeypatch.setattr(demo_identity, "_atomic_write", fail_first_jwks_write)
    with pytest.raises(OSError, match="injected JWKS"):
        retire_demo_identity_key(tmp_path, kid=initial.active_kid)
    monkeypatch.setattr(demo_identity, "_atomic_write", original_write)

    recovered = retire_demo_identity_key(tmp_path, kid=initial.active_kid)

    assert initial.active_kid not in recovered.key_ids
    with pytest.raises(AuthenticationFailure):
        _verifier(tmp_path).verify_bearer(f"Bearer {old_token}")
    assert not (tmp_path / f"private-{initial.active_kid}.pem").exists()


def test_concurrent_rotations_are_serialized_without_lost_keys(tmp_path: Path) -> None:
    initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    workers = [
        context.Process(target=_rotate_in_process, args=(str(tmp_path), results))
        for _ in range(2)
    ]

    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)

    assert all(not worker.is_alive() and worker.exitcode == 0 for worker in workers)
    outcomes = [results.get(timeout=5)[0] for _ in workers]
    assert sorted(outcomes) == ["error", "ok"]
    manifest = json.loads(
        (tmp_path / "identity_manifest.json").read_text(encoding="utf-8")
    )
    jwks = json.loads((tmp_path / "jwks.json").read_text(encoding="utf-8"))
    assert len(manifest["keys"]) == 2
    assert {item["kid"] for item in manifest["keys"]} == {
        item["kid"] for item in jwks["keys"]
    }


def test_uncommitted_runtime_artifact_bytes_fail_closed(tmp_path: Path) -> None:
    initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    jwks_path = tmp_path / "jwks.json"
    original_jwks = jwks_path.read_bytes()
    jwks_path.write_bytes(original_jwks + b"\n")

    with pytest.raises(IdentityConfigurationError, match="not committed"):
        _verifier(tmp_path)

    jwks_path.write_bytes(original_jwks)
    token_path = tmp_path / "operator_token.txt"
    token_path.write_bytes(token_path.read_bytes() + b"\n")
    with pytest.raises(IdentityConfigurationError, match="not committed"):
        BearerTokenFileSource(token_path).get_token()


def test_interrupted_first_initialization_never_publishes_uncommitted_jwks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original_write = demo_identity._atomic_write

    def fail_manifest(path: Path, payload: bytes) -> None:
        if Path(path).name == "identity_manifest.json":
            raise OSError("injected manifest publication failure")
        original_write(path, payload)

    monkeypatch.setattr(demo_identity, "_atomic_write", fail_manifest)
    with pytest.raises(OSError, match="manifest publication"):
        initialize_demo_identity(
            tmp_path,
            issuer="https://identity.localhost/",
            audience="enterprise-rag-api",
            token_lifetime_seconds=900,
        )

    assert (tmp_path / ".identity-operation.json").exists()
    assert not (tmp_path / "identity_manifest.json").exists()
    with pytest.raises(IdentityConfigurationError, match="not committed"):
        _verifier(tmp_path)

    monkeypatch.setattr(demo_identity, "_atomic_write", original_write)
    recovered = demo_identity_status(tmp_path)
    assert recovered.active_kid in recovered.key_ids
    assert recovered.restart_required is True
    _verifier(tmp_path).ready()


def test_oversized_serialized_journal_is_rejected_before_any_secret_is_written(
    tmp_path: Path,
) -> None:
    oversized_issuer = "https://identity.localhost/" + ("a" * 30_000)

    with pytest.raises(
        IdentityConfigurationError,
        match="operation journal exceeds",
    ):
        initialize_demo_identity(
            tmp_path,
            issuer=oversized_issuer,
            audience="enterprise-rag-api",
            token_lifetime_seconds=900,
        )

    assert not (tmp_path / ".identity-operation.json").exists()
    assert not (tmp_path / "identity_manifest.json").exists()
    assert not (tmp_path / "jwks.json").exists()
    assert not (tmp_path / "persona_tokens.json").exists()
    assert not list(tmp_path.glob("private-*.pem"))


def test_legacy_manifest_is_rejected_by_readers_then_transactionally_upgraded(
    tmp_path: Path,
) -> None:
    initialized = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    manifest_path = tmp_path / "identity_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    manifest["schema_version"] = "demo-identity-keyring-v1"
    manifest.pop("retired_kids")
    manifest.pop("retire_not_before")
    manifest.pop("emergency_revocations")
    manifest.pop("artifacts")
    for record in manifest["keys"]:
        record.pop("private_key_sha256")
    manifest_path.write_text(json.dumps(manifest), encoding="ascii")

    with pytest.raises(IdentityConfigurationError, match="legacy"):
        _verifier(tmp_path)

    status = demo_identity_status(tmp_path)
    upgraded = json.loads(manifest_path.read_text(encoding="ascii"))
    assert status.active_kid == initialized.active_kid
    assert status.restart_required is True
    assert upgraded["schema_version"] == "demo-identity-keyring-v3"
    assert upgraded["retire_not_before"] == {}
    assert upgraded["emergency_revocations"] == []
    assert set(upgraded["artifacts"]) == {
        "jwks.json",
        "persona_tokens.json",
        "operator_token.txt",
        "load_user_token.txt",
        "feedback_actor_hmac.key",
    }
    _verifier(tmp_path).ready()


def test_previous_v2_manifest_is_transactionally_upgraded_before_lifecycle_use(
    tmp_path: Path,
) -> None:
    initialized = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    manifest_path = tmp_path / "identity_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    manifest["schema_version"] = "demo-identity-keyring-v2"
    manifest.pop("retire_not_before")
    manifest.pop("emergency_revocations")
    manifest_path.write_text(json.dumps(manifest), encoding="ascii")

    with pytest.raises(IdentityConfigurationError, match="legacy"):
        _verifier(tmp_path)

    status = demo_identity_status(tmp_path)
    upgraded = json.loads(manifest_path.read_text(encoding="ascii"))

    assert status.active_kid == initialized.active_kid
    assert status.restart_required is True
    assert upgraded["schema_version"] == "demo-identity-keyring-v3"
    assert upgraded["retire_not_before"] == {}
    assert upgraded["emergency_revocations"] == []
    _verifier(tmp_path).ready()


def test_previous_v2_multikey_manifest_gets_conservative_old_key_windows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    clock = [demo_identity._now_epoch()]
    monkeypatch.setattr(demo_identity, "_now_epoch", lambda: clock[0])
    initial = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    first_active = _activate_staged(tmp_path, rotate_demo_identity(tmp_path))
    second_active = _activate_staged(tmp_path, rotate_demo_identity(tmp_path))
    manifest_path = tmp_path / "identity_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    manifest["schema_version"] = "demo-identity-keyring-v2"
    manifest.pop("retire_not_before")
    manifest.pop("emergency_revocations")
    manifest_path.write_text(json.dumps(manifest), encoding="ascii")

    status = demo_identity_status(tmp_path)
    expected_deadline = (
        clock[0]
        + demo_identity._MAX_TOKEN_LIFETIME_SECONDS
        + demo_identity.IDENTITY_CLOCK_SKEW_MAX_SECONDS
    )

    assert status.active_kid == second_active.active_kid
    assert dict(status.retirement_not_before) == {
        initial.active_kid: expected_deadline,
        first_active.active_kid: expected_deadline,
    }
    _verifier(tmp_path).ready()


def test_legacy_manifest_path_escape_is_rejected_before_outside_file_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    manifest_path = tmp_path / "identity_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    manifest["schema_version"] = "demo-identity-keyring-v1"
    manifest.pop("retired_kids")
    manifest.pop("retire_not_before")
    manifest.pop("emergency_revocations")
    manifest.pop("artifacts")
    manifest["keys"][0].pop("private_key_sha256")
    manifest["keys"][0]["private_key_file"] = "../outside.pem"
    manifest_path.write_text(json.dumps(manifest), encoding="ascii")
    outside = tmp_path.parent / "outside.pem"
    outside.write_bytes(b"outside-secret")
    observed: list[Path] = []
    original_read = demo_identity.read_private_file_snapshot

    def recording_read(path: Path, *, max_bytes: int) -> bytes:
        observed.append(Path(path).absolute())
        return original_read(path, max_bytes=max_bytes)

    monkeypatch.setattr(demo_identity, "read_private_file_snapshot", recording_read)
    with pytest.raises(IdentityConfigurationError, match="manifest is invalid"):
        demo_identity_status(tmp_path)

    assert outside.absolute() not in observed
    assert outside.read_bytes() == b"outside-secret"


def test_recovered_force_initialization_does_not_swallow_current_force_intent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    initial = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    original_write = demo_identity._atomic_write
    failed = False

    def fail_first_manifest(path: Path, payload: bytes) -> None:
        nonlocal failed
        if Path(path).name == "identity_manifest.json" and not failed:
            failed = True
            raise OSError("injected force publication failure")
        original_write(path, payload)

    monkeypatch.setattr(demo_identity, "_atomic_write", fail_first_manifest)
    with pytest.raises(OSError, match="force publication"):
        initialize_demo_identity(
            tmp_path,
            issuer="https://identity.localhost/",
            audience="enterprise-rag-api",
            token_lifetime_seconds=900,
            force=True,
        )
    journal = json.loads(
        (tmp_path / ".identity-operation.json").read_text(encoding="ascii")
    )
    recovered_kid = journal["subject_kid"]

    monkeypatch.setattr(demo_identity, "_atomic_write", original_write)
    final = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
        force=True,
    )

    assert final.active_kid not in {initial.active_kid, recovered_kid}
    assert final.key_ids == (final.active_kid,)


def test_recovered_rotation_does_not_swallow_current_rotation_intent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    initial = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    original_write = demo_identity._atomic_write
    failed = False

    def fail_first_manifest(path: Path, payload: bytes) -> None:
        nonlocal failed
        if Path(path).name == "identity_manifest.json" and not failed:
            failed = True
            raise OSError("injected rotation publication failure")
        original_write(path, payload)

    monkeypatch.setattr(demo_identity, "_atomic_write", fail_first_manifest)
    with pytest.raises(OSError, match="rotation publication"):
        rotate_demo_identity(tmp_path)
    journal = json.loads(
        (tmp_path / ".identity-operation.json").read_text(encoding="ascii")
    )
    recovered_kid = journal["subject_kid"]

    monkeypatch.setattr(demo_identity, "_atomic_write", original_write)
    with pytest.raises(ValueError, match="staged identity key"):
        rotate_demo_identity(tmp_path)
    final = demo_identity_status(tmp_path)

    assert final.active_kid == initial.active_kid
    assert final.pending_kid == recovered_kid
    assert set(final.key_ids) == {initial.active_kid, recovered_kid}


def test_stale_atomic_temporary_file_is_removed_only_under_lifecycle_lock(
    tmp_path: Path,
) -> None:
    initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    stale = tmp_path / ".jwks.json.tmp-0123456789abcdef"
    unrelated = tmp_path / ".notes.tmp-0123456789abcdef"
    stale.write_bytes(b"interrupted-write")
    unrelated.write_bytes(b"must-remain")

    demo_identity_status(tmp_path)

    assert not stale.exists()
    assert unrelated.read_bytes() == b"must-remain"


def test_hard_link_is_rejected_before_permissions_or_bytes_are_changed(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-lock"
    outside.write_bytes(b"outside")
    try:
        os.link(outside, tmp_path / ".identity.lock")
    except OSError:
        pytest.skip("hard-link creation is not available")

    with pytest.raises(IdentityConfigurationError, match="permissions"):
        initialize_demo_identity(
            tmp_path,
            issuer="https://identity.localhost/",
            audience="enterprise-rag-api",
            token_lifetime_seconds=900,
        )

    assert outside.read_bytes() == b"outside"


def test_directory_guard_is_released_when_lock_path_validation_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    exits: list[bool] = []
    real_hold = demo_identity.hold_private_directory
    real_validate = demo_identity.validate_private_path_ancestors

    class Guard:
        def __enter__(self):
            self.delegate = real_hold(tmp_path)
            return self.delegate.__enter__()

        def __exit__(self, exc_type, exc, traceback):
            exits.append(True)
            return self.delegate.__exit__(exc_type, exc, traceback)

    def fail_lock_path(path: Path, *, allow_missing: bool = False) -> None:
        if Path(path).name == ".identity.lock":
            raise IdentityConfigurationError("injected unsafe lock path")
        real_validate(path, allow_missing=allow_missing)

    monkeypatch.setattr(demo_identity, "hold_private_directory", lambda _path: Guard())
    monkeypatch.setattr(
        demo_identity,
        "validate_private_path_ancestors",
        fail_lock_path,
    )

    with pytest.raises(IdentityConfigurationError, match="unsafe lock path"):
        demo_identity_status(tmp_path)

    assert exits == [True]


def test_directory_identity_change_fails_before_operation_journal_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    before = {
        path.name: path.read_bytes()
        for path in tmp_path.iterdir()
        if path.is_file()
    }
    monkeypatch.setattr(
        demo_identity,
        "_active_directory_path_is_current",
        lambda _root: False,
        raising=False,
    )

    with pytest.raises(
        IdentityConfigurationError,
        match="changed while locked",
    ):
        rotate_demo_identity(tmp_path)

    after = {
        path.name: path.read_bytes()
        for path in tmp_path.iterdir()
        if path.is_file()
    }
    assert after == before


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory rename semantics")
def test_posix_root_replacement_cannot_receive_writes_from_old_lock(
    tmp_path: Path,
) -> None:
    initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    moved = tmp_path.with_name(f"{tmp_path.name}-moved")

    with demo_identity._identity_lock(tmp_path):
        tmp_path.rename(moved)
        tmp_path.mkdir(mode=0o700)
        with pytest.raises(
            IdentityConfigurationError,
            match="changed while locked",
        ):
            demo_identity._atomic_write(
                tmp_path / "jwks.json",
                b"must-not-be-written",
            )

    assert not (tmp_path / "jwks.json").exists()
    assert (moved / "identity_manifest.json").exists()


def test_posix_lock_uses_the_same_bounded_timeout_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lock_path = tmp_path / "bounded-posix.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    attempts = 0

    def always_contended(_descriptor: int, operation: int) -> None:
        nonlocal attempts
        attempts += 1
        assert operation == 2 | 4
        raise BlockingIOError("lock is held")

    monkeypatch.setattr(demo_identity, "_LOCK_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(demo_identity, "_LOCK_POLL_SECONDS", 0.001)
    try:
        with pytest.raises(
            IdentityConfigurationError,
            match="lifecycle lock timed out",
        ):
            demo_identity._lock_posix_descriptor(
                descriptor,
                flock=always_contended,
                lock_ex=2,
                lock_nonblocking=4,
            )
    finally:
        os.close(descriptor)

    assert attempts >= 2


def test_semantically_inconsistent_journal_fails_before_mutating_committed_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    initialized = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    original_write = demo_identity._atomic_write

    def fail_first_jwks(path: Path, payload: bytes) -> None:
        if Path(path).name == "jwks.json":
            raise OSError("injected rotate staging failure")
        original_write(path, payload)

    monkeypatch.setattr(demo_identity, "_atomic_write", fail_first_jwks)
    with pytest.raises(OSError, match="rotate staging"):
        rotate_demo_identity(tmp_path)
    monkeypatch.setattr(demo_identity, "_atomic_write", original_write)
    manifest_path = tmp_path / "identity_manifest.json"
    committed_manifest = manifest_path.read_bytes()
    journal_path = tmp_path / ".identity-operation.json"
    journal = json.loads(journal_path.read_text(encoding="ascii"))
    journal["deletes"] = [f"private-{initialized.active_kid}.pem"]
    journal_path.write_text(json.dumps(journal), encoding="ascii")

    with pytest.raises(IdentityConfigurationError, match="journal is invalid"):
        demo_identity_status(tmp_path)

    assert manifest_path.read_bytes() == committed_manifest
    assert (tmp_path / f"private-{initialized.active_kid}.pem").exists()


def test_one_step_rotation_journal_cannot_bypass_snapshot_activation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    initialized = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    original_write = demo_identity._atomic_write

    def fail_first_jwks(path: Path, payload: bytes) -> None:
        if Path(path).name == "jwks.json":
            raise OSError("injected rotate staging failure")
        original_write(path, payload)

    monkeypatch.setattr(demo_identity, "_atomic_write", fail_first_jwks)
    with pytest.raises(OSError, match="rotate staging"):
        rotate_demo_identity(tmp_path)
    monkeypatch.setattr(demo_identity, "_atomic_write", original_write)

    manifest_path = tmp_path / "identity_manifest.json"
    committed_manifest = manifest_path.read_bytes()
    journal_path = tmp_path / ".identity-operation.json"
    journal = json.loads(journal_path.read_text(encoding="ascii"))
    staged_manifest = json.loads(
        base64.b64decode(
            journal["writes"]["identity_manifest.json"],
            validate=True,
        ).decode("ascii")
    )
    staged_manifest["active_kid"] = journal["subject_kid"]
    staged_manifest["retire_not_before"] = {
        initialized.active_kid: (
            demo_identity._now_epoch()
            + demo_identity._MAX_TOKEN_LIFETIME_SECONDS
            + demo_identity.IDENTITY_CLOCK_SKEW_MAX_SECONDS
        )
    }
    journal["writes"]["identity_manifest.json"] = base64.b64encode(
        demo_identity._json_bytes(staged_manifest)
    ).decode("ascii")
    journal_path.write_text(json.dumps(journal), encoding="ascii")

    with pytest.raises(IdentityConfigurationError, match="journal is invalid"):
        demo_identity_status(tmp_path)

    assert manifest_path.read_bytes() == committed_manifest
    assert json.loads(committed_manifest)["active_kid"] == initialized.active_kid


def test_completed_one_step_rotation_journal_still_fails_semantic_recovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    initialized = initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    original_write = demo_identity._atomic_write

    def fail_first_jwks(path: Path, payload: bytes) -> None:
        if Path(path).name == "jwks.json":
            raise OSError("injected rotate staging failure")
        original_write(path, payload)

    monkeypatch.setattr(demo_identity, "_atomic_write", fail_first_jwks)
    with pytest.raises(OSError, match="rotate staging"):
        rotate_demo_identity(tmp_path)
    monkeypatch.setattr(demo_identity, "_atomic_write", original_write)

    journal_path = tmp_path / ".identity-operation.json"
    journal = json.loads(journal_path.read_text(encoding="ascii"))
    staged_manifest = json.loads(
        base64.b64decode(
            journal["writes"]["identity_manifest.json"],
            validate=True,
        ).decode("ascii")
    )
    staged_manifest["active_kid"] = journal["subject_kid"]
    staged_manifest["retire_not_before"] = {
        initialized.active_kid: (
            demo_identity._now_epoch()
            + demo_identity._MAX_TOKEN_LIFETIME_SECONDS
            + demo_identity.IDENTITY_CLOCK_SKEW_MAX_SECONDS
        )
    }
    journal["writes"]["identity_manifest.json"] = base64.b64encode(
        demo_identity._json_bytes(staged_manifest)
    ).decode("ascii")
    journal_path.write_text(json.dumps(journal), encoding="ascii")

    decoded_writes = {
        name: base64.b64decode(value, validate=True)
        for name, value in journal["writes"].items()
    }
    with demo_identity._identity_lock(tmp_path):
        for name in sorted(
            item for item in decoded_writes if item != "identity_manifest.json"
        ):
            original_write(tmp_path / name, decoded_writes[name])
        original_write(
            tmp_path / "identity_manifest.json",
            decoded_writes["identity_manifest.json"],
        )
    committed_target = (tmp_path / "identity_manifest.json").read_bytes()

    with pytest.raises(IdentityConfigurationError, match="journal is invalid"):
        demo_identity_status(tmp_path)

    assert (tmp_path / "identity_manifest.json").read_bytes() == committed_target
    assert journal_path.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL regression")
def test_windows_identity_directory_acl_is_private(tmp_path: Path) -> None:
    initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )

    assert demo_identity._private_directory_permissions_are_secure(tmp_path)
