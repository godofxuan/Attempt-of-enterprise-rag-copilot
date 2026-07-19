from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.evaluation.indirect_injection_public_verifier import (
    VerificationError,
    verify_package,
)
from scripts.verify_indirect_injection_public_evidence import main as verify_main
from tests.evaluation.test_indirect_injection_public_writer import (
    _export,
    private_source_run,
    writer_inputs,
)


FORMAL_METRICS = {
    "egress_violation_case": (0, 72),
    "model_call_error": (0, 68),
    "off_model_context_exposure": (7, 24),
    "off_raw_canary_or_forbidden_action_follow": (3, 24),
    "off_user_visible_attack_success": (3, 24),
    "on_attack_unit_reached_guard": (15, 28),
    "on_attack_unit_unreached": (13, 28),
    "on_benign_unit_quarantine": (0, 32),
    "on_clean_task_success": (12, 12),
    "on_mixed_task_success": (20, 20),
    "on_model_context_exposure": (0, 24),
    "on_poison_only_security_filtered_correct": (4, 4),
    "on_quarantine_recall_given_guard_exposure": (15, 15),
    "on_raw_canary_or_forbidden_action_follow": (0, 24),
    "on_user_visible_attack_success": (0, 24),
}
FORMAL_PACKAGE = (
    Path(__file__).resolve().parents[2] / "data" / "v2" / "public" / "r2_s1_d7"
)


def _rehash(package: Path, name: str) -> None:
    checksum = package / "checksums.sha256"
    rows = checksum.read_text(encoding="utf-8").splitlines()
    replacement = hashlib.sha256((package / name).read_bytes()).hexdigest()
    updated = [
        f"{replacement}  {name}" if row.endswith(f"  {name}") else row
        for row in rows
    ]
    checksum.write_text("\n".join(updated) + "\n", encoding="utf-8", newline="\n")


def _read_rows(package: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (package / "per_case.redacted.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]


def _write_rows(package: Path, rows: list[dict[str, object]]) -> None:
    content = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for row in rows
    )
    (package / "per_case.redacted.jsonl").write_text(
        content,
        encoding="utf-8",
        newline="\n",
    )
    _rehash(package, "per_case.redacted.jsonl")


def _write_pretty_json(package: Path, name: str, payload: object) -> None:
    (package / name).write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _rehash(package, name)


def _verify_test_package(package: Path):
    return verify_package(package, require_formal=False)


def test_verifier_accepts_writer_package_and_repository_cli(
    tmp_path: Path,
    private_source_run,
    capsys: pytest.CaptureFixture[str],
) -> None:
    package = _export(tmp_path, private_source_run)

    result = _verify_test_package(package)
    assert result.case_pair_count == 36
    assert result.row_count == 72
    assert verify_main([str(FORMAL_PACKAGE)]) == 0
    assert "VERIFIED" in capsys.readouterr().out


def test_standalone_verifier_runs_with_only_public_package_files(
    tmp_path: Path,
) -> None:
    isolated = tmp_path / "isolated" / "r2_s1_d7"
    shutil.copytree(FORMAL_PACKAGE, isolated)

    completed = subprocess.run(
        [sys.executable, "-I", "verify.py"],
        cwd=isolated,
        check=False,
        capture_output=True,
        text=True,
    )

    assert {path.name for path in isolated.iterdir()} == {
        "README.md",
        "manifest.redacted.json",
        "summary.json",
        "per_case.redacted.jsonl",
        "metric_definitions.json",
        "source_run.sha256",
        "checksums.sha256",
        "verify.py",
    }
    assert completed.returncode == 0, completed.stderr
    assert "VERIFIED" in completed.stdout


def test_verifier_rejects_plain_checksum_tampering(
    tmp_path: Path,
    private_source_run,
) -> None:
    package = _export(tmp_path, private_source_run)
    (package / "README.md").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(VerificationError, match="checksum"):
        _verify_test_package(package)


def test_verifier_recomputes_metrics_after_attacker_updates_checksum(
    tmp_path: Path,
    private_source_run,
) -> None:
    package = _export(tmp_path, private_source_run)
    rows = _read_rows(package)
    target = next(
        row
        for row in rows
        if row["guard_mode"] == "on"
        and row["utility_bucket"] == "mixed"
        and row["task_success"] is True
    )
    target["task_success"] = False
    _write_rows(package, rows)

    with pytest.raises(VerificationError, match="summary metric mismatch"):
        _verify_test_package(package)


def test_verifier_rejects_pair_fingerprint_tampering_with_fresh_checksum(
    tmp_path: Path,
    private_source_run,
) -> None:
    package = _export(tmp_path, private_source_run)
    rows = _read_rows(package)
    rows[0]["pair_input_fingerprint"] = "0" * 64
    _write_rows(package, rows)

    with pytest.raises(VerificationError, match="pair provenance"):
        _verify_test_package(package)


def test_verifier_rejects_extra_row_field_even_with_fresh_checksum(
    tmp_path: Path,
    private_source_run,
) -> None:
    package = _export(tmp_path, private_source_run)
    rows = _read_rows(package)
    rows[0]["question"] = "redaction bypass"
    _write_rows(package, rows)

    with pytest.raises(VerificationError, match="row keys"):
        _verify_test_package(package)


def test_verifier_rejects_source_hash_disagreement_with_fresh_checksum(
    tmp_path: Path,
    private_source_run,
) -> None:
    package = _export(tmp_path, private_source_run)
    (package / "source_run.sha256").write_text(
        f"{'0' * 64}  source-manifest\n",
        encoding="utf-8",
        newline="\n",
    )
    _rehash(package, "source_run.sha256")

    with pytest.raises(VerificationError, match="source manifest"):
        _verify_test_package(package)


def test_verifier_rejects_unexpected_file(
    tmp_path: Path,
    private_source_run,
) -> None:
    package = _export(tmp_path, private_source_run)
    (package / "private-output.txt").write_text("should not exist", encoding="utf-8")

    with pytest.raises(VerificationError, match="file set"):
        _verify_test_package(package)


def test_formal_verifier_rejects_rewritten_source_identity_with_fresh_checksums(
    tmp_path: Path,
) -> None:
    package = tmp_path / "r2_s1_d7"
    shutil.copytree(FORMAL_PACKAGE, package)
    old_hash = "5bf058cfa56c2b5034e6f204dc3619833b55b3c30277c5222e7415f97865e14e"
    new_hash = "0" * 64
    manifest = json.loads(
        (package / "manifest.redacted.json").read_text(encoding="utf-8")
    )
    manifest["source"]["run_id"] = "rewritten-source-run"
    manifest["source"]["manifest_sha256"] = new_hash
    _write_pretty_json(package, "manifest.redacted.json", manifest)
    summary = json.loads((package / "summary.json").read_text(encoding="utf-8"))
    summary["source_run_id"] = "rewritten-source-run"
    _write_pretty_json(package, "summary.json", summary)
    readme = (package / "README.md").read_text(encoding="utf-8")
    (package / "README.md").write_text(
        readme.replace("r2-s1-d7-test-20260718-01", "rewritten-source-run").replace(
            old_hash,
            new_hash,
        ),
        encoding="utf-8",
        newline="\n",
    )
    _rehash(package, "README.md")
    (package / "source_run.sha256").write_text(
        f"{new_hash}  source-manifest\n",
        encoding="utf-8",
        newline="\n",
    )
    _rehash(package, "source_run.sha256")

    with pytest.raises(VerificationError, match="formal source"):
        verify_package(package)


def test_formal_verifier_rejects_nonmetric_row_rewrite_with_fresh_checksum(
    tmp_path: Path,
) -> None:
    package = tmp_path / "r2_s1_d7"
    shutil.copytree(FORMAL_PACKAGE, package)
    rows = _read_rows(package)
    rows[0]["guard_latency_ms"] = float(rows[0]["guard_latency_ms"]) + 1.0
    _write_rows(package, rows)

    with pytest.raises(VerificationError, match="formal artifact"):
        verify_package(package)


def test_checked_in_formal_d7_package_recomputes_exact_frozen_metrics() -> None:
    result = verify_package(FORMAL_PACKAGE)
    summary = json.loads(
        (FORMAL_PACKAGE / "summary.json").read_text(encoding="utf-8")
    )

    assert result.case_pair_count == 36
    assert result.row_count == 72
    assert set(summary["metrics"]) == set(FORMAL_METRICS)
    for name, (numerator, denominator) in FORMAL_METRICS.items():
        metric = summary["metrics"][name]
        assert (metric["numerator"], metric["denominator"]) == (
            numerator,
            denominator,
        )
        assert metric["rate"] == (
            None if denominator == 0 else numerator / denominator
        )
