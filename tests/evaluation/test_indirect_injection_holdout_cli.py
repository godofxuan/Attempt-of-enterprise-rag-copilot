from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import freeze_indirect_injection_holdout as freeze_cli
from scripts import verify_indirect_injection_holdout as verify_cli
from tests.evaluation.test_indirect_injection_holdout import (
    FROZEN_AT,
    _baseline,
    write_valid_holdout_package,
)


ATTESTATION_FLAGS = [
    "--author-independent",
    "--payload-not-shared",
    "--labels-not-tuned",
    "--single-run",
]


def test_freeze_cli_writes_content_free_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    submission = write_valid_holdout_package(tmp_path)
    monkeypatch.setattr(freeze_cli, "current_holdout_code_baseline", lambda _: _baseline())

    assert freeze_cli.main(
        [
            str(submission),
            "--frozen-at-utc",
            FROZEN_AT.isoformat().replace("+00:00", "Z"),
            *ATTESTATION_FLAGS,
        ]
    ) == 0
    receipt = json.loads(capsys.readouterr().out)

    assert receipt["state"] == "FROZEN"
    assert receipt["submission_id"] == submission.name
    assert receipt["case_count"] == 36
    assert receipt["attack_case_count"] == 24
    assert receipt["benign_case_count"] == 12
    assert set(receipt["input_sha256"]) == {
        "case_catalog.json",
        "payload.json",
        "rubric.json",
    }
    assert "payload" not in receipt


def test_freeze_cli_requires_all_separation_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission = write_valid_holdout_package(tmp_path)
    monkeypatch.setattr(freeze_cli, "current_holdout_code_baseline", lambda _: _baseline())

    with pytest.raises(ValueError, match="four separation attestations"):
        freeze_cli.main(
            [
                str(submission),
                "--frozen-at-utc",
                FROZEN_AT.isoformat().replace("+00:00", "Z"),
                *ATTESTATION_FLAGS[:-1],
            ]
        )
    assert not (submission / "freeze_manifest.json").exists()


def test_freeze_cli_rejects_dirty_tracked_baseline_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission = write_valid_holdout_package(tmp_path)

    def dirty_baseline(_):
        raise ValueError("holdout freeze requires a clean tracked worktree")

    monkeypatch.setattr(freeze_cli, "current_holdout_code_baseline", dirty_baseline)

    with pytest.raises(ValueError, match="clean tracked worktree"):
        freeze_cli.main(
            [
                str(submission),
                "--frozen-at-utc",
                FROZEN_AT.isoformat().replace("+00:00", "Z"),
                *ATTESTATION_FLAGS,
            ]
        )
    assert not (submission / "freeze_manifest.json").exists()


def test_verify_cli_recomputes_frozen_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    submission = write_valid_holdout_package(tmp_path)
    monkeypatch.setattr(freeze_cli, "current_holdout_code_baseline", lambda _: _baseline())
    freeze_cli.main(
        [
            str(submission),
            "--frozen-at-utc",
            FROZEN_AT.isoformat().replace("+00:00", "Z"),
            *ATTESTATION_FLAGS,
        ]
    )
    capsys.readouterr()
    monkeypatch.setattr(verify_cli, "current_holdout_code_baseline", lambda _: _baseline())

    assert verify_cli.main([str(submission)]) == 0
    receipt = json.loads(capsys.readouterr().out)

    assert receipt["verification"] == "VERIFIED"
    assert receipt["state"] == "FROZEN"
    assert receipt["git_head"] == "a" * 40
