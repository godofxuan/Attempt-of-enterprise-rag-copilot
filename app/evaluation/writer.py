from __future__ import annotations

import csv
import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from app.filesystem import atomic_directory_move
from app.evaluation.contracts import AblationRow, EvaluationRunResult
from app.evaluation.run_manifest import RunManifest


_FAILURE_FIELDS = [
    "case_id",
    "task_type",
    "expected_mode",
    "actual_mode",
    "primary_failure",
    "secondary_failures",
    "failed_layers",
]
_CATEGORY_DEFAULT_FIELDS = ["category_type", "category", "count"]
_ABLATION_FIELDS = list(AblationRow.model_fields)


def publish_run(
    root: Path,
    manifest: RunManifest,
    result: EvaluationRunResult,
    *,
    ablation_rows: Sequence[AblationRow] = (),
    human_review_rows: Sequence[dict[str, Any]] = (),
) -> Path:
    _validate_consistency(manifest, result)
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / manifest.run_id).resolve()
    if target.parent != root:
        raise ValueError("run ID resolves outside output root")
    if target.exists():
        raise FileExistsError(f"output run already exists: {target}")

    stage = Path(
        tempfile.mkdtemp(prefix=f".{manifest.run_id}.staging-", dir=root)
    ).resolve()
    try:
        _write_run_files(stage, result, ablation_rows, human_review_rows)
        artifact_paths = [
            path for path in stage.iterdir() if path.name != "manifest.json"
        ]
        artifact_hashes = {
            path.name: _sha256(path) for path in sorted(artifact_paths)
        }
        final_manifest = manifest.model_copy(
            update={
                "completed_at_utc": datetime.now(timezone.utc),
                "artifacts": artifact_hashes,
            }
        )
        (stage / "manifest.json").write_bytes(
            _json_bytes(final_manifest.model_dump(mode="json"))
        )
        _validate_stage(stage, artifact_hashes)
        _promote_stage(stage, target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def _validate_consistency(
    manifest: RunManifest, result: EvaluationRunResult
) -> None:
    pairs = {
        "run_id": (manifest.run_id, result.run_id),
        "suite": (manifest.suite, result.suite),
        "split": (manifest.split, result.split),
        "mode": (manifest.mode, result.mode),
    }
    mismatches = [name for name, values in pairs.items() if values[0] != values[1]]
    if mismatches:
        raise ValueError("manifest/result mismatch: " + ", ".join(mismatches))


def _write_run_files(
    stage: Path,
    result: EvaluationRunResult,
    ablation_rows: Sequence[AblationRow],
    human_review_rows: Sequence[dict[str, Any]],
) -> None:
    summary = {
        "schema_version": result.schema_version,
        "producer": result.producer,
        "run_id": result.run_id,
        "suite": result.suite,
        "split": result.split,
        "mode": result.mode,
        "case_count": result.case_count,
        "summary": result.summary,
        "security_probes": result.security_probes,
        "config": result.config,
    }
    (stage / "summary.json").write_bytes(_json_bytes(summary))
    _write_jsonl(
        stage / "details.jsonl",
        [detail.model_dump(mode="json") for detail in result.details],
    )
    _write_csv(stage / "failures.csv", _failure_rows(result), _FAILURE_FIELDS)
    _write_dynamic_csv(
        stage / "metrics_by_category.csv",
        result.metrics_by_category,
        default_fields=_CATEGORY_DEFAULT_FIELDS,
    )
    _write_csv(
        stage / "ablation.csv",
        [row.model_dump(mode="json") for row in ablation_rows],
        _ABLATION_FIELDS,
    )
    if human_review_rows:
        _write_dynamic_csv(stage / "human_review.csv", human_review_rows)


def _failure_rows(result: EvaluationRunResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for detail in result.details:
        if detail.passed:
            continue
        failed_layers = [
            layer.layer for layer in detail.layers if layer.applicable and not layer.passed
        ]
        rows.append(
            {
                "case_id": detail.case_id,
                "task_type": detail.task_type,
                "expected_mode": detail.expected_mode,
                "actual_mode": detail.actual_mode,
                "primary_failure": detail.primary_failure or "",
                "secondary_failures": ";".join(detail.secondary_failures),
                "failed_layers": ";".join(failed_layers),
            }
        )
    return rows


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    payload = b"".join(_json_bytes(row, newline=True) for row in rows)
    path.write_bytes(payload)


def _write_dynamic_csv(
    path: Path,
    rows: Sequence[dict[str, Any]],
    *,
    default_fields: Sequence[str] = (),
) -> None:
    fields = list(default_fields)
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    if not fields:
        fields = ["empty"]
    _write_csv(path, rows, fields)


def _write_csv(
    path: Path,
    rows: Sequence[dict[str, Any]],
    fields: Sequence[str],
) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else value
                    for key, value in row.items()
                }
            )


def _validate_stage(stage: Path, expected_hashes: dict[str, str]) -> None:
    json.loads((stage / "summary.json").read_text(encoding="utf-8"))
    for line in (stage / "details.jsonl").read_text(encoding="utf-8").splitlines():
        json.loads(line)
    manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("artifacts") != expected_hashes:
        raise ValueError("run manifest artifact hashes do not match staged files")
    for name, expected in expected_hashes.items():
        if _sha256(stage / name) != expected:
            raise ValueError(f"staged artifact hash mismatch: {name}")


def _promote_stage(stage: Path, target: Path, *, max_attempts: int = 5) -> None:
    del max_attempts
    atomic_directory_move(stage, target)


def _json_bytes(value: Any, *, newline: bool = False) -> bytes:
    suffix = "\n" if newline else ""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=None if newline else 2)
        + suffix
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = ["publish_run"]
