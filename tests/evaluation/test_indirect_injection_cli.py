from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.evaluation.indirect_injection_dataset import (
    build_v1_bundle,
    load_security_bundle,
)
from app.evaluation.indirect_injection_writer import R1HashPair
from scripts import eval_indirect_injection


FROZEN_AT = "2026-07-18T00:00:00Z"
FREEZE_HEAD = "a" * 40


def _bundle(tmp_path: Path) -> Path:
    root = tmp_path / "security"
    build_v1_bundle(
        root,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    return root


def test_parser_exposes_neither_force_nor_live_switch() -> None:
    parser = eval_indirect_injection.build_parser()
    options = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    assert "--force" not in options
    assert "--live" not in options
    assert "--guard-off" not in options


def test_test_manifest_mismatch_fails_before_evaluator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _bundle(tmp_path)
    (root / "indirect_injection_test_v1.json").write_text(
        "{}",
        encoding="utf-8",
    )
    called = False

    def must_not_evaluate(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("evaluator must not run after a freeze mismatch")

    monkeypatch.setattr(eval_indirect_injection, "evaluate_paired", must_not_evaluate)
    monkeypatch.setattr(
        eval_indirect_injection,
        "verify_r1_frozen_hashes",
        lambda _root: {},
    )
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        eval_indirect_injection.main(
            [
                "--split",
                "test",
                "--run-id",
                "tampered-test",
                "--data-root",
                str(root),
                "--out-dir",
                str(tmp_path / "runs"),
            ]
        )
    assert called is False


def test_r1_hash_mismatch_fails_before_evaluator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _bundle(tmp_path)
    called = False

    def must_not_evaluate(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("evaluator must not run after an R1 mismatch")

    monkeypatch.setattr(eval_indirect_injection, "evaluate_paired", must_not_evaluate)

    def mismatch(_root: Path):
        raise ValueError("R1 frozen hash mismatch: data/v2/eval/test.json")

    monkeypatch.setattr(eval_indirect_injection, "verify_r1_frozen_hashes", mismatch)
    with pytest.raises(ValueError, match="R1 frozen hash mismatch"):
        eval_indirect_injection.main(
            [
                "--split",
                "dev",
                "--run-id",
                "r1-mismatch",
                "--data-root",
                str(root),
                "--out-dir",
                str(tmp_path / "runs"),
            ]
        )
    assert called is False


def test_failed_behavior_gate_publishes_evidence_and_returns_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _bundle(tmp_path)
    real_evaluate = eval_indirect_injection.evaluate_paired

    def failed_evaluate(*args, **kwargs):
        result = real_evaluate(*args, **kwargs)
        failed_check = result.gate.checks[0].model_copy(update={"passed": False})
        checks = (failed_check, *result.gate.checks[1:])
        gate = result.gate.model_copy(
            update={
                "passed": False,
                "status": "FAILED",
                "checks": checks,
                "failures": (failed_check.name,),
            }
        )
        return result.model_copy(update={"gate": gate})

    monkeypatch.setattr(eval_indirect_injection, "evaluate_paired", failed_evaluate)
    monkeypatch.setattr(
        eval_indirect_injection,
        "verify_r1_frozen_hashes",
        lambda _root: {
            path: R1HashPair(expected=digest, actual=digest)
            for path, digest in eval_indirect_injection.R1_EXPECTED_HASHES.items()
        },
    )
    monkeypatch.setattr(
        eval_indirect_injection,
        "run_r1_regression_suite",
        lambda _root: eval_indirect_injection.RegressionRun(
            command=("python", "-m", "pytest", "-q"),
            exit_code=0,
            output="synthetic regression passed",
        ),
    )
    out = tmp_path / "runs"
    exit_code = eval_indirect_injection.main(
        [
            "--split",
            "test",
            "--run-id",
            "failed-behavior",
            "--data-root",
            str(root),
            "--out-dir",
            str(out),
        ]
    )

    assert exit_code == 1
    assert (out / "failed-behavior" / "manifest.json").is_file()
    assert (out / "failed-behavior" / "failures.csv").is_file()


def test_dirty_state_fingerprint_changes_with_untracked_file_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    untracked = tmp_path / "untracked.txt"
    untracked.write_text("first content", encoding="utf-8")

    def fake_git_bytes(_root: Path, *args: str) -> bytes:
        if args[:2] == ("status", "--porcelain=v1"):
            return b"?? untracked.txt\n"
        if args == ("diff", "--binary", "HEAD"):
            return b""
        if args == ("rev-parse", "HEAD"):
            return ("a" * 40 + "\n").encode("ascii")
        if args == ("branch", "--show-current"):
            return b"codex/test\n"
        if args == ("ls-files", "--others", "--exclude-standard", "-z"):
            return b"untracked.txt\0"
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(eval_indirect_injection, "_git_bytes", fake_git_bytes)
    before = eval_indirect_injection._git_provenance(tmp_path)
    untracked.write_text("second content", encoding="utf-8")
    after = eval_indirect_injection._git_provenance(tmp_path)

    assert before["dirty_state_sha256"] != after["dirty_state_sha256"]


def test_failed_regression_output_is_redacted_and_still_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _bundle(tmp_path)
    bundle = load_security_bundle(root, "dev")
    raw_fixture_text = bundle.fixture_manifest.cases[0].candidates[0].matched_text
    monkeypatch.setattr(
        eval_indirect_injection,
        "verify_r1_frozen_hashes",
        lambda _root: {
            path: R1HashPair(expected=digest, actual=digest)
            for path, digest in eval_indirect_injection.R1_EXPECTED_HASHES.items()
        },
    )
    monkeypatch.setattr(
        eval_indirect_injection,
        "run_r1_regression_suite",
        lambda _root: eval_indirect_injection.RegressionRun(
            command=("python", "-m", "pytest", "-q"),
            exit_code=1,
            output=(
                f"assertion failed: {raw_fixture_text}\n"
                "api_key=sk-test-1234567890abcdef\n"
            ),
        ),
    )
    out = tmp_path / "runs"

    exit_code = eval_indirect_injection.main(
        [
            "--split",
            "dev",
            "--run-id",
            "failed-regression-redacted",
            "--data-root",
            str(root),
            "--out-dir",
            str(out),
        ]
    )

    assert exit_code == 1
    run = out / "failed-regression-redacted"
    test_output = (run / "test_output.txt").read_text(encoding="utf-8")
    assert raw_fixture_text not in test_output
    assert "<redacted-synthetic-fixture>" in test_output
    assert "sk-test-1234567890abcdef" not in test_output
    assert "<redacted-sensitive-output>" in test_output
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "FAILED"


def test_successful_frozen_test_run_publishes_complete_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _bundle(tmp_path)
    monkeypatch.setattr(
        eval_indirect_injection,
        "verify_r1_frozen_hashes",
        lambda _root: {
            path: R1HashPair(expected=digest, actual=digest)
            for path, digest in eval_indirect_injection.R1_EXPECTED_HASHES.items()
        },
    )
    monkeypatch.setattr(
        eval_indirect_injection,
        "run_r1_regression_suite",
        lambda _root: eval_indirect_injection.RegressionRun(
            command=("python", "-m", "pytest", "-q"),
            exit_code=0,
            output="synthetic regression passed\n",
        ),
    )
    out = tmp_path / "runs"

    exit_code = eval_indirect_injection.main(
        [
            "--split",
            "test",
            "--run-id",
            "successful-frozen-test",
            "--data-root",
            str(root),
            "--out-dir",
            str(out),
        ]
    )

    assert exit_code == 0
    run = out / "successful-frozen-test"
    assert {path.name for path in run.iterdir()} == {
        "manifest.json",
        "summary.json",
        "per_case.jsonl",
        "failures.csv",
        "red_green_evidence.md",
        "commands.txt",
        "test_output.txt",
        "checksums.sha256",
    }
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "PASSED ON FROZEN SYNTHETIC SET"
    assert manifest["release_gate"]["passed"] is True


def test_repository_r1_frozen_hashes_match_protocol() -> None:
    evidence = eval_indirect_injection.verify_r1_frozen_hashes(
        eval_indirect_injection.BASE_DIR
    )

    assert set(evidence) == set(eval_indirect_injection.R1_EXPECTED_HASHES)
    assert all(pair.expected == pair.actual for pair in evidence.values())


def test_output_sanitizer_preserves_urls_while_redacting_local_paths() -> None:
    value = (
        "Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html\n"
        "Local: C:\\Users\\example\\private\\failure.txt\n"
    )

    sanitized = eval_indirect_injection._sanitize_output(
        value,
        eval_indirect_injection.BASE_DIR,
    )

    assert "https://docs.pytest.org/en/stable/how-to/capture-warnings.html" in sanitized
    assert "C:\\Users\\example" not in sanitized
    assert "<absolute-path>" in sanitized


def test_output_sanitizer_redacts_unc_and_device_paths() -> None:
    value = (
        "UNC: \\\\server\\share\\private\\failure.txt\n"
        "Device: \\\\?\\C:\\private\\failure.txt\n"
    )

    sanitized = eval_indirect_injection._sanitize_output(
        value,
        eval_indirect_injection.BASE_DIR,
    )

    assert "server\\share" not in sanitized
    assert "?\\C:" not in sanitized
    assert sanitized.count("<absolute-path>") == 2


@pytest.mark.parametrize(
    "run_id",
    ["CON", "con.txt", "NUL", "COM1.log", "LPT9", "trailing."],
)
def test_cli_rejects_windows_unsafe_run_ids(run_id: str) -> None:
    with pytest.raises(ValueError, match="run ID"):
        eval_indirect_injection._validate_args(SimpleNamespace(run_id=run_id))


def test_git_change_during_evaluation_aborts_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _bundle(tmp_path)
    before = {
        "head": "a" * 40,
        "branch": "codex/test",
        "dirty": True,
        "status_entry_count": 1,
        "dirty_state_sha256": "b" * 64,
    }
    after = {**before, "dirty_state_sha256": "c" * 64}
    states = iter((before, after))
    monkeypatch.setattr(
        eval_indirect_injection,
        "_git_provenance",
        lambda _root: next(states),
    )
    monkeypatch.setattr(
        eval_indirect_injection,
        "verify_r1_frozen_hashes",
        lambda _root: {
            path: R1HashPair(expected=digest, actual=digest)
            for path, digest in eval_indirect_injection.R1_EXPECTED_HASHES.items()
        },
    )
    monkeypatch.setattr(
        eval_indirect_injection,
        "run_r1_regression_suite",
        lambda _root: eval_indirect_injection.RegressionRun(
            command=("python", "-m", "pytest", "-q"),
            exit_code=0,
            output="synthetic regression passed\n",
        ),
    )
    published = False

    def must_not_publish(*args, **kwargs):
        nonlocal published
        published = True
        raise AssertionError("stale provenance must not be published")

    monkeypatch.setattr(
        eval_indirect_injection,
        "publish_security_run",
        must_not_publish,
    )

    with pytest.raises(RuntimeError, match="Git state changed during evaluation"):
        eval_indirect_injection.main(
            [
                "--split",
                "dev",
                "--run-id",
                "git-state-change",
                "--data-root",
                str(root),
                "--out-dir",
                str(tmp_path / "runs"),
            ]
        )

    assert published is False


def test_git_provenance_command_failure_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        eval_indirect_injection.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout=b"",
            stderr=b"synthetic git failure",
        ),
    )

    with pytest.raises(RuntimeError, match="Git provenance command failed"):
        eval_indirect_injection._git_bytes(
            eval_indirect_injection.BASE_DIR,
            "status",
            "--porcelain=v1",
        )


def test_installed_dependency_snapshot_is_sorted_and_content_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        eval_indirect_injection.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="z-package==2.0\na-package==1.0\n\n",
            stderr="",
        ),
    )

    snapshot = eval_indirect_injection._installed_dependency_snapshot()

    normalized = b"a-package==1.0\nz-package==2.0\n"
    assert snapshot == {
        "installed_snapshot_command": (
            "python",
            "-m",
            "pip",
            "freeze",
            "--all",
        ),
        "installed_snapshot_sha256": hashlib.sha256(normalized).hexdigest(),
        "installed_package_count": 2,
    }


def test_installed_dependency_snapshot_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        eval_indirect_injection.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="synthetic pip failure",
        ),
    )

    with pytest.raises(RuntimeError, match="dependency snapshot command failed"):
        eval_indirect_injection._installed_dependency_snapshot()
