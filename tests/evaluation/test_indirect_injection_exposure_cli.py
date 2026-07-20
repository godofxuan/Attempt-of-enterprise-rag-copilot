from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.evaluation.indirect_injection_exposure_writer import verify_exposure_run
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

