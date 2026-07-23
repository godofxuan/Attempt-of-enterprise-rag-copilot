from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.security.demo_identity import DemoIdentityStatus
from scripts import manage_demo_identity


def test_identity_cli_preserves_lexical_directory_for_reparse_checks(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    requested = tmp_path / "identity"
    observed: dict[str, Path] = {}

    def reject_early_resolution(self: Path, *args, **kwargs) -> Path:
        raise AssertionError("CLI must not resolve links before the safety check")

    def fake_status(directory: Path) -> DemoIdentityStatus:
        observed["directory"] = directory
        return DemoIdentityStatus(
            active_kid="demo-20260722T000000Z-00000000",
            key_ids=("demo-20260722T000000Z-00000000",),
            persona_count=7,
            restart_required=True,
        )

    monkeypatch.setattr(Path, "resolve", reject_early_resolution)
    monkeypatch.setattr(
        manage_demo_identity,
        "get_settings",
        lambda: SimpleNamespace(identity_jwks_path=tmp_path / "default" / "jwks.json"),
    )
    monkeypatch.setattr(manage_demo_identity, "demo_identity_status", fake_status)

    manage_demo_identity.main(["--directory", str(requested), "status"])

    assert observed["directory"] == Path(os.path.abspath(requested))
    assert '"restart_required": true' in capsys.readouterr().out


def test_identity_cli_activates_only_after_loopback_snapshot_confirmation(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    requested = tmp_path / "identity"
    pending_kid = "demo-20260722T000000Z-11111111"
    observed: dict[str, object] = {}

    def fake_snapshot_check(
        *,
        base_url: str,
        token: str,
        expected_kid: str,
        timeout_seconds: float,
    ) -> bool:
        observed["snapshot"] = (
            base_url,
            token,
            expected_kid,
            timeout_seconds,
        )
        return True

    def fake_activate(
        directory: Path,
        *,
        kid: str,
        token_lifetime_seconds: int,
        snapshot_verifier,
    ) -> DemoIdentityStatus:
        observed["activation"] = (
            directory,
            kid,
            token_lifetime_seconds,
        )
        assert snapshot_verifier("pending-probe", kid) is True
        return DemoIdentityStatus(
            active_kid=kid,
            key_ids=("demo-20260722T000000Z-00000000", kid),
            persona_count=7,
            pending_kid=None,
            restart_required=False,
        )

    monkeypatch.setattr(
        manage_demo_identity,
        "get_settings",
        lambda: SimpleNamespace(
            identity_jwks_path=tmp_path / "default" / "jwks.json",
        ),
    )
    monkeypatch.setattr(
        manage_demo_identity,
        "_api_snapshot_accepts_pending_key",
        fake_snapshot_check,
    )
    monkeypatch.setattr(
        manage_demo_identity,
        "activate_demo_identity",
        fake_activate,
    )

    manage_demo_identity.main(
        [
            "--directory",
            str(requested),
            "activate",
            "--kid",
            pending_kid,
            "--api-base-url",
            "http://127.0.0.1:8123",
            "--timeout-seconds",
            "2.5",
            "--token-lifetime-seconds",
            "600",
        ]
    )

    assert observed["activation"] == (requested, pending_kid, 600)
    assert observed["snapshot"] == (
        "http://127.0.0.1:8123",
        "pending-probe",
        pending_kid,
        2.5,
    )
    output = capsys.readouterr().out
    assert f'"active_kid": "{pending_kid}"' in output
    assert '"pending_kid": null' in output
    assert '"restart_required": false' in output


def test_identity_cli_requires_exact_emergency_retirement_confirmation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("retirement must not run without confirmation")

    monkeypatch.setattr(
        manage_demo_identity,
        "get_settings",
        lambda: SimpleNamespace(
            identity_jwks_path=tmp_path / "default" / "jwks.json"
        ),
    )
    monkeypatch.setattr(
        manage_demo_identity,
        "retire_demo_identity_key",
        fail_if_called,
    )

    with pytest.raises(SystemExit):
        manage_demo_identity.main(
            [
                "--directory",
                str(tmp_path / "identity"),
                "retire",
                "--kid",
                "demo-20260722T000000Z-00000000",
                "--emergency-revoke",
                "--confirm-emergency-revoke",
                "yes",
            ]
        )

    assert called is False


def test_identity_cli_surfaces_retirement_window_and_emergency_audit_count(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    requested = tmp_path / "identity"
    old_kid = "demo-20260722T000000Z-00000000"
    active_kid = "demo-20260722T000000Z-11111111"
    observed: dict[str, object] = {}

    def fake_retire(
        directory: Path,
        *,
        kid: str,
        emergency_revoke: bool,
        emergency_confirmation: str | None,
    ) -> DemoIdentityStatus:
        observed["call"] = (
            directory,
            kid,
            emergency_revoke,
            emergency_confirmation,
        )
        return DemoIdentityStatus(
            active_kid=active_kid,
            key_ids=(active_kid,),
            persona_count=7,
            retirement_not_before=(),
            emergency_revocations=((old_kid, 1_789_000_000),),
            restart_required=True,
        )

    monkeypatch.setattr(
        manage_demo_identity,
        "get_settings",
        lambda: SimpleNamespace(
            identity_jwks_path=tmp_path / "default" / "jwks.json"
        ),
    )
    monkeypatch.setattr(
        manage_demo_identity,
        "retire_demo_identity_key",
        fake_retire,
    )

    manage_demo_identity.main(
        [
            "--directory",
            str(requested),
            "retire",
            "--kid",
            old_kid,
            "--emergency-revoke",
            "--confirm-emergency-revoke",
            "RETIRE_ACTIVE_TOKENS_NOW",
        ]
    )

    assert observed["call"] == (
        requested,
        old_kid,
        True,
        "RETIRE_ACTIVE_TOKENS_NOW",
    )
    output = capsys.readouterr().out
    assert '"emergency_revocation_count": 1' in output
    assert f'"kid": "{old_kid}"' in output
    assert '"revoked_at": 1789000000' in output
    assert '"retirement_not_before": {}' in output
