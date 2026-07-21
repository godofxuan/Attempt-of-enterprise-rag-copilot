from __future__ import annotations

import errno
import hashlib
import json
from pathlib import Path

import pytest

from app.evaluation.indirect_injection_exposure_writer import verify_exposure_run
from scripts import eval_indirect_injection_exposure as eval_cli
from scripts import verify_indirect_injection_exposure as verify_cli
from scripts.eval_indirect_injection_exposure import (
    main as eval_main,
)
from scripts.verify_indirect_injection_exposure import (
    main as verify_main,
)
from tests.evaluation.test_indirect_injection_exposure import source_material


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_argv(
    source_run: Path,
    security_data_root: Path,
    output: Path,
    *,
    run_id: str = "exposure-cli-test",
) -> list[str]:
    return [
        "--source-run",
        str(source_run),
        "--security-data-root",
        str(security_data_root),
        "--out-dir",
        str(output),
        "--run-id",
        run_id,
        "--expected-source-manifest-sha256",
        _sha256(source_run / "manifest.json"),
        "--created-at-utc",
        "2026-07-21T00:00:00Z",
    ]


def test_eval_cli_publishes_valid_evidence_and_returns_zero(
    source_material: tuple[Path, Path],
    tmp_path: Path,
    capsys,
) -> None:
    source_run, security_data_root = source_material
    output = tmp_path / "runs"
    run_id = "exposure-cli-test"

    assert eval_main(
        _valid_argv(source_run, security_data_root, output, run_id=run_id)
    ) == 0
    target = output / run_id
    manifest = verify_exposure_run(target)
    assert manifest.run_id == run_id
    assert manifest.created_at_utc.isoformat() == "2026-07-21T00:00:00+00:00"
    assert tuple(
        (item.dependency_id, item.path, item.sha256)
        for item in manifest.replay_dependencies
    ) == (
        (
            "guard_ruleset",
            "app/security/retrieved_content.py",
            "78ed0509144820ccd05aff61c1509357dd8fe3dbfc8a0c6df30fc304a15e9cd2",
        ),
        (
            "retrieved_admission",
            "app/security/retrieved_admission.py",
            "1f835ba3aa79b1450e8ae906946bba019c21b531fce114cd375b094411c88afb",
        ),
        (
            "search_surface_constructor",
            "app/evaluation/indirect_injection_runner.py",
            "c2c5c5e1815d8a77beebb5027384ea58dd3e73b8536533c8d7898d40668ed36c",
        ),
        (
            "source_live_evaluator",
            "app/evaluation/indirect_injection_live_runner.py",
            "a5eec5619a5ac9f44357fc6063232dca6021538ca5988aab6ae2f962d9b85958",
        ),
    )
    stdout = json.loads(capsys.readouterr().out)
    assert stdout == {
        "decision": "NO_CURRENT_BYPASS_OBSERVED",
        "output_dir": target.as_posix(),
        "run_id": run_id,
        "source_run_id": "r2-s2-s1-dev-20260719-01",
        "status": "PUBLISHED",
    }
    commands = (target / "commands.txt").read_text(encoding="utf-8")
    assert str(tmp_path) not in commands
    assert "<external>/" in commands


def test_eval_cli_invalid_source_returns_two_without_target(
    source_material: tuple[Path, Path],
    tmp_path: Path,
    capsys,
) -> None:
    source_run, security_data_root = source_material
    output = tmp_path / "runs"
    run_id = "invalid-source"
    argv = _valid_argv(
        source_run,
        security_data_root,
        output,
        run_id=run_id,
    )
    hash_index = argv.index("--expected-source-manifest-sha256") + 1
    argv[hash_index] = "0" * 64

    assert eval_main(argv) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["decision"] == "INVALID_EVIDENCE"
    assert error["error_type"] == "ExposureEvidenceError"
    assert not (output / run_id).exists()


def test_eval_cli_rejects_false_executed_evaluator_hash_without_target(
    source_material: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    source_run, security_data_root = source_material
    output = tmp_path / "runs"
    evaluator_path = (
        eval_cli.BASE_DIR / eval_cli.EXPOSURE_EVALUATOR_PATH
    ).resolve()
    real_sha256 = eval_cli._sha256

    def false_evaluator_hash(path: Path) -> str:
        if path.resolve() == evaluator_path:
            return "0" * 64
        return real_sha256(path)

    monkeypatch.setattr(eval_cli, "_sha256", false_evaluator_hash)

    assert eval_main(
        _valid_argv(
            source_run,
            security_data_root,
            output,
            run_id="false-evaluator-hash",
        )
    ) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["decision"] == "INVALID_EVIDENCE"
    assert "exposure evaluator SHA-256 mismatch" in error["message"]
    assert not (output / "false-evaluator-hash").exists()


def test_eval_cli_existing_target_is_an_operational_error(
    source_material: tuple[Path, Path],
    tmp_path: Path,
    capsys,
) -> None:
    source_run, security_data_root = source_material
    output = tmp_path / "runs"
    argv = _valid_argv(source_run, security_data_root, output)
    assert eval_main(argv) == 0
    capsys.readouterr()

    assert eval_main(argv) == 1
    error = json.loads(capsys.readouterr().err)
    assert error["status"] == "OUTPUT_ERROR"


def test_eval_cli_rejects_non_utc_created_at_without_artifact(
    source_material: tuple[Path, Path],
    tmp_path: Path,
    capsys,
) -> None:
    source_run, security_data_root = source_material
    output = tmp_path / "runs"
    argv = _valid_argv(source_run, security_data_root, output)
    created_index = argv.index("--created-at-utc") + 1
    argv[created_index] = "2026-07-21T08:00:00+08:00"

    assert eval_main(argv) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["decision"] == "INVALID_EVIDENCE"
    assert not (output / "exposure-cli-test").exists()


def test_verify_cli_recomputes_existing_run(
    source_material: tuple[Path, Path],
    tmp_path: Path,
    capsys,
) -> None:
    source_run, security_data_root = source_material
    output = tmp_path / "runs"
    argv = _valid_argv(source_run, security_data_root, output)
    assert eval_main(argv) == 0
    capsys.readouterr()

    assert verify_main([str(output / "exposure-cli-test")]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["status"] == "VERIFIED"
    assert verified["run_id"] == "exposure-cli-test"


def test_verify_cli_rejects_tampered_run(
    source_material: tuple[Path, Path],
    tmp_path: Path,
    capsys,
) -> None:
    source_run, security_data_root = source_material
    output = tmp_path / "runs"
    argv = _valid_argv(source_run, security_data_root, output)
    assert eval_main(argv) == 0
    capsys.readouterr()
    target = output / "exposure-cli-test"
    (target / "commands.txt").write_bytes(b"tampered\n")

    assert verify_main([str(target)]) == 1
    error = json.loads(capsys.readouterr().err)
    assert error["status"] == "VERIFICATION_FAILED"


@pytest.mark.parametrize(
    ("exception_type", "error_number"),
    (
        (OSError, errno.ENOTSUP),
        (PermissionError, errno.EACCES),
    ),
    ids=("enotsup", "permission"),
)
def test_eval_cli_normalizes_general_oserror_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    source_material: tuple[Path, Path],
    tmp_path: Path,
    capsys,
    exception_type: type[OSError],
    error_number: int,
) -> None:
    source_run, security_data_root = source_material
    output = tmp_path / "runs"

    def fail_publication(*_args, **_kwargs):
        raise exception_type(error_number, "simulated publication I/O failure")

    monkeypatch.setattr(eval_cli, "publish_exposure_run", fail_publication)

    assert eval_cli.main(
        _valid_argv(source_run, security_data_root, output)
    ) == 1
    captured = capsys.readouterr()
    error = json.loads(captured.err)
    assert captured.out == ""
    assert error["status"] == "OUTPUT_ERROR"
    assert error["error_type"] == exception_type.__name__
    assert "Traceback" not in captured.err
    assert not (output / "exposure-cli-test").exists()


@pytest.mark.parametrize(
    ("exception_type", "error_number"),
    (
        (OSError, errno.ENOTSUP),
        (PermissionError, errno.EACCES),
    ),
    ids=("enotsup", "permission"),
)
def test_verify_cli_normalizes_general_oserror_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys,
    exception_type: type[OSError],
    error_number: int,
) -> None:
    def fail_verification(_run_dir: Path):
        raise exception_type(error_number, "simulated verification I/O failure")

    monkeypatch.setattr(verify_cli, "verify_exposure_run", fail_verification)

    assert verify_cli.main([str(tmp_path / "run")]) == 1
    captured = capsys.readouterr()
    error = json.loads(captured.err)
    assert captured.out == ""
    assert error["status"] == "VERIFICATION_FAILED"
    assert error["error_type"] == exception_type.__name__
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("cli_module", (eval_cli, verify_cli))
def test_private_clis_do_not_catch_programmer_errors(
    monkeypatch: pytest.MonkeyPatch,
    source_material: tuple[Path, Path],
    tmp_path: Path,
    cli_module,
) -> None:
    def fail(*_args, **_kwargs):
        raise RuntimeError("programmer defect")

    if cli_module is eval_cli:
        source_run, security_data_root = source_material
        monkeypatch.setattr(cli_module, "publish_exposure_run", fail)
        argv = _valid_argv(source_run, security_data_root, tmp_path / "runs")
    else:
        monkeypatch.setattr(cli_module, "verify_exposure_run", fail)
        argv = [str(tmp_path / "run")]

    with pytest.raises(RuntimeError, match="programmer defect"):
        cli_module.main(argv)
