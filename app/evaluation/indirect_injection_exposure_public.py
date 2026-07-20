from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from app.evaluation import indirect_injection_exposure_public_verifier as verifier
from app.evaluation.indirect_injection_exposure import ExposureUnitObservation
from app.evaluation.indirect_injection_exposure_public_verifier import (
    CHECKSUM_CONTENT_NAMES,
    METRIC_DEFINITIONS,
    PUBLIC_EXPOSURE_FILES,
    PUBLIC_UNIT_ROW_KEYS,
    build_public_readme,
    verify_exposure_public_package,
)
from app.evaluation.indirect_injection_exposure_writer import (
    _assert_content_free,
    _assert_structured_content_free,
    _atomic_publish_no_replace,
    verify_exposure_run,
)
from app.evaluation.indirect_injection_writer import validate_security_run_id


_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/]"),
    re.compile(r"\\\\[A-Za-z0-9._$-]+[\\/]"),
    re.compile(r"(?<![A-Za-z0-9])/(?:home|Users|tmp|var/tmp)/"),
)


def export_exposure_public_evidence(
    source_run: Path,
    output_root: Path,
    *,
    package_name: str = "r2_s3_exposure",
    expected_source_manifest_sha256: str,
    expected_source_run_id: str,
    forbidden_texts: tuple[str, ...],
) -> Path:
    """Verify, project, scan, and atomically publish public evidence."""

    validate_security_run_id(package_name)
    validate_security_run_id(expected_source_run_id)
    if not _HASH_PATTERN.fullmatch(expected_source_manifest_sha256):
        raise ValueError("expected source manifest hash must be lowercase SHA-256")
    if not forbidden_texts or any(not value for value in forbidden_texts):
        raise ValueError("a non-empty forbidden text policy is required")
    source_run = Path(source_run).resolve()
    source_manifest = verify_exposure_run(source_run)
    observed_source_hash = _sha256(source_run / "manifest.json")
    if observed_source_hash != expected_source_manifest_sha256:
        raise ValueError("source private manifest hash mismatch")
    if source_manifest.run_id != expected_source_run_id:
        raise ValueError("source private run ID mismatch")

    private_summary = json.loads(
        (source_run / "summary.json").read_text(encoding="utf-8")
    )
    private_units = tuple(
        ExposureUnitObservation.model_validate_json(line)
        for line in (source_run / "per_unit.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    public_rows = tuple(
        sorted(
            (
                _project_unit(source_manifest.run_id, item)
                for item in private_units
            ),
            key=lambda item: (
                item["case_fingerprint"],
                item["unit_fingerprint"],
            ),
        )
    )
    verifier_bytes = Path(verifier.__file__).read_bytes()
    definitions_bytes = _json_bytes(METRIC_DEFINITIONS)
    public_summary = {
        "schema_version": "indirect_injection_exposure_public_summary_v1",
        "source": private_summary["source"],
        "verification_inputs": private_summary["verification_inputs"],
        "summary": private_summary["summary"],
        "strata": private_summary["strata"],
        "decision": private_summary["decision"],
        "unguarded_path_findings": private_summary[
            "unguarded_path_findings"
        ],
        "limitations": private_summary["limitations"],
    }
    public_manifest = {
        "schema_version": "indirect_injection_exposure_public_manifest_v1",
        "producer": "enterprise_agentic_rag_v2",
        "package_name": package_name,
        "source_private_run_id": source_manifest.run_id,
        "source_private_manifest_sha256": observed_source_hash,
        "source": source_manifest.source.model_dump(mode="json"),
        "counterfactual_depths": list(source_manifest.counterfactual_depths),
        "decision": source_manifest.decision,
        "case_count": source_manifest.case_count,
        "attack_case_count": source_manifest.attack_case_count,
        "benign_case_count": source_manifest.benign_case_count,
        "attack_unit_count": source_manifest.attack_unit_count,
        "benign_unit_count": source_manifest.benign_unit_count,
        "row_count": len(public_rows),
        "unguarded_path_findings": [
            item.model_dump(mode="json")
            for item in source_manifest.unguarded_path_findings
        ],
        "limitations": list(source_manifest.limitations),
        "metric_definitions_sha256": hashlib.sha256(
            definitions_bytes
        ).hexdigest(),
        "verifier_sha256": hashlib.sha256(verifier_bytes).hexdigest(),
    }
    readme = build_public_readme(public_manifest)
    source_hash_text = f"{observed_source_hash}  manifest.json\n"
    private_ids = tuple(
        sorted(
            {
                value
                for item in private_units
                for value in (item.case_id, item.unit_id)
            }
        )
    )
    forbidden_policy = tuple(sorted({*forbidden_texts, *private_ids}))
    for value in (public_manifest, public_summary, public_rows, METRIC_DEFINITIONS):
        _assert_structured_content_free(value, forbidden_policy)
    for value in (readme, source_hash_text):
        _assert_structured_content_free(value, forbidden_policy)

    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    target = (output_root / package_name).resolve()
    if target.parent != output_root:
        raise ValueError("package name resolves outside output root")
    if target.exists():
        raise FileExistsError(f"public exposure package already exists: {target}")
    stage_root = Path(
        tempfile.mkdtemp(prefix=f".{package_name}.staging-", dir=output_root)
    ).resolve()
    stage = stage_root / package_name
    stage.mkdir()
    try:
        (stage / "verify.py").write_bytes(verifier_bytes)
        (stage / "metric_definitions.json").write_bytes(definitions_bytes)
        (stage / "manifest.redacted.json").write_bytes(
            _json_bytes(public_manifest)
        )
        (stage / "summary.json").write_bytes(_json_bytes(public_summary))
        (stage / "per_unit.redacted.jsonl").write_bytes(
            b"".join(_json_line(item) + b"\n" for item in public_rows)
        )
        (stage / "README.md").write_text(
            readme, encoding="utf-8", newline=""
        )
        (stage / "source_run.sha256").write_text(
            source_hash_text, encoding="utf-8", newline=""
        )
        for name in CHECKSUM_CONTENT_NAMES:
            if name == "checksums.sha256":
                continue
            payload = (stage / name).read_bytes()
            _assert_content_free(payload, forbidden_policy)
            _assert_no_absolute_paths(payload, name)
        (stage / "checksums.sha256").write_bytes(_checksum_bytes(stage))
        if {item.name for item in stage.iterdir()} != set(PUBLIC_EXPOSURE_FILES):
            raise ValueError("public exposure package has an unexpected artifact set")
        verify_exposure_public_package(stage)
        _atomic_publish_no_replace(stage, target)
        stage_root.rmdir()
    except Exception:
        shutil.rmtree(stage_root, ignore_errors=True)
        raise
    return target


def _project_unit(
    source_run_id: str,
    item: ExposureUnitObservation,
) -> dict[str, Any]:
    payload = item.model_dump(mode="json")
    case_id = payload.pop("case_id")
    unit_id = payload.pop("unit_id")
    projected = {
        "schema_version": "indirect_injection_exposure_public_unit_v1",
        "case_fingerprint": _fingerprint(
            "r2-s3-case-v1", source_run_id, case_id
        ),
        "unit_fingerprint": _fingerprint(
            "r2-s3-unit-v1", source_run_id, case_id, unit_id
        ),
        **payload,
    }
    if set(projected) != set(PUBLIC_UNIT_ROW_KEYS):
        raise ValueError("public unit projection keys are not exact")
    return projected


def _fingerprint(domain: str, *values: str) -> str:
    framed = "\0".join((domain, *values)).encode("utf-8")
    return hashlib.sha256(framed).hexdigest()


def _assert_no_absolute_paths(payload: bytes, label: str) -> None:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} is not UTF-8") from exc
    if any(pattern.search(text) for pattern in _ABSOLUTE_PATH_PATTERNS):
        raise ValueError(f"{label} contains an absolute local path")


def _checksum_bytes(stage: Path) -> bytes:
    return "".join(
        f"{_sha256(stage / name)}  {name}\n"
        for name in CHECKSUM_CONTENT_NAMES
    ).encode("utf-8")


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _json_line(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = ["export_exposure_public_evidence"]

