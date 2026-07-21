from __future__ import annotations

import csv
import ctypes
import errno
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal, Mapping, Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.evaluation.indirect_injection_exposure import (
    COUNTERFACTUAL_DEPTHS,
    EXPOSURE_LIMITATIONS,
    ExposureAnalysisResult,
    ExposureDecision,
    ExposureSourceEvidence,
    ExposureStratum,
    ExposureSummary,
    ExposureUnitObservation,
    ExposureVerificationInputs,
    REPLAY_IMPLEMENTATION_DEPENDENCIES,
    ReplayImplementationDependency,
    UnguardedPathFinding,
    _case_has_downstream_exposure,
    _group_unit_rows,
    compute_exposure_unit_evidence_sha256,
    compute_exposure_verification_inputs_sha256,
    recompute_exposure_summary,
    verify_replay_dependency_bytes,
)
from app.evaluation.indirect_injection_writer import (
    ArtifactEvidence,
    validate_security_run_id,
)


PRIVATE_EXPOSURE_ARTIFACT_FILES = frozenset(
    {
        "manifest.json",
        "summary.json",
        "per_unit.jsonl",
        "failures.csv",
        "checksums.sha256",
        "commands.txt",
        "test_output.txt",
    }
)
_CONTENT_ARTIFACT_NAMES = tuple(
    sorted(
        PRIVATE_EXPOSURE_ARTIFACT_FILES
        - {"manifest.json", "checksums.sha256"}
    )
)
_MANIFEST_ARTIFACT_NAMES = tuple(
    sorted(PRIVATE_EXPOSURE_ARTIFACT_FILES - {"manifest.json"})
)
_FAILURE_COLUMNS = (
    "scope",
    "case_id",
    "unit_id",
    "primary_failure",
    "all_failures",
)
_CASE_FAILURE_FIELDS = (
    ("controller_exposure", "case_controller_exposure"),
    ("ledger_exposure", "case_ledger_exposure"),
    ("model_context_exposure", "case_model_context_exposure"),
    ("verifier_exposure", "case_verifier_exposure"),
    ("response_exposure", "case_response_exposure"),
    ("forbidden_action_followed", "case_forbidden_action_followed"),
    ("forbidden_tool_attempt", "case_forbidden_tool_attempt"),
    ("external_egress_attempt", "case_external_egress_attempt"),
    ("blocked_egress_attempt", "case_blocked_egress_attempt_count"),
    ("attack_success", "case_attack_success"),
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


def _safe_relative(value: str, label: str) -> str:
    if "\\" in value:
        raise ValueError(f"{label} must use repository-relative POSIX form")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        not value
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ".." in posix.parts
    ):
        raise ValueError(f"{label} must be a safe relative path")
    return value


class ExposureRunManifest(_StrictFrozenModel):
    schema_version: Literal[
        "indirect_injection_exposure_run_manifest_v1",
        "indirect_injection_exposure_run_manifest_v2",
    ]
    producer: Literal["enterprise_agentic_rag_v2"]
    run_id: str
    created_at_utc: datetime
    source: ExposureSourceEvidence
    guard_ruleset_path: str
    guard_ruleset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_path: str
    evaluator_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    replay_dependencies: tuple[ReplayImplementationDependency, ...] | None = None
    unit_evidence_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    verification_inputs_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    counterfactual_depths: tuple[Literal[1], Literal[2], Literal[4]]
    decision: ExposureDecision
    case_count: Literal[36]
    attack_case_count: Literal[24]
    benign_case_count: Literal[12]
    attack_unit_count: Literal[28]
    benign_unit_count: Literal[32]
    unguarded_path_findings: tuple[UnguardedPathFinding, ...]
    artifacts: Mapping[str, ArtifactEvidence] = Field(default_factory=dict)
    limitations: tuple[str, ...] = Field(min_length=1)

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        return validate_security_run_id(value)

    @field_validator("guard_ruleset_path")
    @classmethod
    def validate_guard_path(cls, value: str) -> str:
        return _safe_relative(value, "Guard ruleset path")

    @field_validator("evaluator_path")
    @classmethod
    def validate_evaluator_path(cls, value: str) -> str:
        return _safe_relative(value, "exposure evaluator path")

    @field_validator("created_at_utc")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("created_at_utc must be timezone-aware UTC")
        return value

    @model_validator(mode="after")
    def validate_manifest(self) -> ExposureRunManifest:
        if self.counterfactual_depths != COUNTERFACTUAL_DEPTHS:
            raise ValueError("counterfactual depths must be exactly 1, 2, and 4")
        if self.guard_ruleset_sha256 != self.source.guard_ruleset_sha256:
            raise ValueError("Guard ruleset hash contradicts source evidence")
        if len(self.unguarded_path_findings) != len(
            set(self.unguarded_path_findings)
        ):
            raise ValueError("unguarded-path findings must be unique")
        if self.limitations != EXPOSURE_LIMITATIONS:
            raise ValueError("manifest limitations must be exact and ordered")
        hashes = (
            self.unit_evidence_sha256,
            self.verification_inputs_sha256,
        )
        if self.schema_version.endswith("_v2"):
            if any(value is None for value in hashes):
                raise ValueError("v2 manifest requires analysis evidence hashes")
            if self.replay_dependencies is None:
                raise ValueError("v2 manifest requires replay dependencies")
            if self.replay_dependencies != REPLAY_IMPLEMENTATION_DEPENDENCIES:
                raise ValueError(
                    "v2 manifest replay dependencies must be exact"
                )
            guard_dependency = self.replay_dependencies[0]
            if (
                self.guard_ruleset_path != guard_dependency.path
                or self.guard_ruleset_sha256 != guard_dependency.sha256
            ):
                raise ValueError(
                    "v2 manifest Guard evidence contradicts replay dependencies"
                )
        if self.schema_version.endswith("_v1"):
            if any(value is not None for value in hashes):
                raise ValueError(
                    "v1 manifest cannot carry v2 analysis evidence hashes"
                )
            if self.replay_dependencies is not None:
                raise ValueError(
                    "v1 manifest cannot carry v2 replay dependencies"
                )
        if self.artifacts:
            if set(self.artifacts) != set(_MANIFEST_ARTIFACT_NAMES):
                raise ValueError("manifest requires the exact artifact set")
            if any(
                name != evidence.path
                for name, evidence in self.artifacts.items()
            ):
                raise ValueError("manifest artifact key/path mismatch")
        return self


class ExposureSummaryDocument(_StrictFrozenModel):
    schema_version: Literal[
        "indirect_injection_exposure_summary_v1",
        "indirect_injection_exposure_summary_v2",
    ]
    source: ExposureSourceEvidence
    unit_evidence_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    verification_inputs: ExposureVerificationInputs
    verification_inputs_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    summary: ExposureSummary
    strata: tuple[ExposureStratum, ...]
    decision: ExposureDecision
    unguarded_path_findings: tuple[UnguardedPathFinding, ...]
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_document(self) -> ExposureSummaryDocument:
        if self.limitations != EXPOSURE_LIMITATIONS:
            raise ValueError("summary limitations must be exact and ordered")
        hashes = (
            self.unit_evidence_sha256,
            self.verification_inputs_sha256,
        )
        if self.schema_version.endswith("_v2") and any(
            value is None for value in hashes
        ):
            raise ValueError("v2 summary requires analysis evidence hashes")
        if self.schema_version.endswith("_v1") and any(
            value is not None for value in hashes
        ):
            raise ValueError("v1 summary cannot carry v2 analysis evidence hashes")
        return self


def publish_exposure_run(
    root: Path,
    *,
    manifest: ExposureRunManifest,
    result: ExposureAnalysisResult,
    commands: str,
    test_output: str,
    forbidden_texts: tuple[str, ...],
) -> Path:
    """Publish one verified, immutable private exposure run."""

    if not forbidden_texts or any(not value for value in forbidden_texts):
        raise ValueError("a non-empty forbidden text policy is required")
    if manifest.artifacts:
        raise ValueError("pre-publication manifest artifacts must be empty")
    if manifest.schema_version != "indirect_injection_exposure_run_manifest_v2":
        raise ValueError("new exposure runs require private manifest v2")
    if manifest.replay_dependencies is None:
        raise ValueError("v2 manifest requires replay dependencies")
    verify_replay_dependency_bytes(manifest.replay_dependencies)
    _validate_analysis(manifest, result)
    canonical_commands = _canonical_text(commands, "commands")
    canonical_test_output = _canonical_text(test_output, "test output")

    output_root = Path(root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / manifest.run_id
    if target.parent.resolve() != output_root:
        raise ValueError("run ID resolves outside output root")
    if target.is_symlink() or target.exists():
        raise FileExistsError(f"exposure output run already exists: {target}")
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{manifest.run_id}.staging-",
            dir=output_root,
        )
    ).resolve()
    try:
        document = ExposureSummaryDocument(
            schema_version="indirect_injection_exposure_summary_v2",
            source=result.source,
            unit_evidence_sha256=result.unit_evidence_sha256,
            verification_inputs=result.verification_inputs,
            verification_inputs_sha256=result.verification_inputs_sha256,
            summary=result.summary,
            strata=result.strata,
            decision=result.decision,
            unguarded_path_findings=result.unguarded_path_findings,
            limitations=result.limitations,
        )
        document_payload = document.model_dump(mode="json")
        _assert_structured_content_free(document_payload, forbidden_texts)
        (stage / "summary.json").write_bytes(
            _json_bytes(document_payload)
        )
        sorted_units = tuple(
            sorted(result.units, key=lambda item: (item.case_id, item.unit_id))
        )
        for item in sorted_units:
            _assert_structured_content_free(
                item.model_dump(mode="json"), forbidden_texts
            )
        (stage / "per_unit.jsonl").write_bytes(_unit_rows_bytes(sorted_units))
        failure_bytes = _failure_bytes(
            sorted_units, result.unguarded_path_findings
        )
        _assert_csv_content_free(failure_bytes, forbidden_texts)
        (stage / "failures.csv").write_bytes(failure_bytes)
        _assert_text_content_free(canonical_commands, forbidden_texts)
        (stage / "commands.txt").write_text(
            canonical_commands,
            encoding="utf-8",
            newline="",
        )
        _assert_text_content_free(canonical_test_output, forbidden_texts)
        (stage / "test_output.txt").write_text(
            canonical_test_output,
            encoding="utf-8",
            newline="",
        )
        for name in _CONTENT_ARTIFACT_NAMES:
            _assert_content_free((stage / name).read_bytes(), forbidden_texts)
        (stage / "checksums.sha256").write_bytes(_checksum_bytes(stage))
        artifact_evidence = {
            name: ArtifactEvidence(
                path=name,
                bytes=(stage / name).stat().st_size,
                sha256=_sha256(stage / name),
            )
            for name in _MANIFEST_ARTIFACT_NAMES
        }
        payload = manifest.model_dump(mode="python")
        payload["artifacts"] = artifact_evidence
        final_manifest = ExposureRunManifest.model_validate(payload)
        manifest_payload = final_manifest.model_dump(mode="json")
        _assert_structured_content_free(manifest_payload, forbidden_texts)
        manifest_bytes = _json_bytes(manifest_payload)
        _assert_content_free(manifest_bytes, forbidden_texts)
        (stage / "manifest.json").write_bytes(manifest_bytes)
        _validate_stage(stage, final_manifest)
        _atomic_publish_no_replace(stage, target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def _atomic_publish_no_replace(stage: Path, target: Path) -> None:
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move_file = kernel32.MoveFileExW
        move_file.argtypes = (
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_ulong,
        )
        move_file.restype = ctypes.c_int
        if move_file(str(stage), str(target), 0):
            return
        error_code = ctypes.get_last_error()
        if error_code in {5, 80, 183} and target.exists():
            raise FileExistsError(
                errno.EEXIST,
                os.strerror(errno.EEXIST),
                str(target),
            )
        raise ctypes.WinError(error_code)

    if sys.platform == "linux":
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise OSError(
                errno.ENOTSUP,
                os.strerror(errno.ENOTSUP),
                str(target),
            )
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        if renameat2(
            -100,
            os.fsencode(stage),
            -100,
            os.fsencode(target),
            1,
        ) == 0:
            return
        error_code = ctypes.get_errno()
        if error_code in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(
                errno.EEXIST,
                os.strerror(errno.EEXIST),
                str(target),
            )
        unsupported_errors = {
            errno.EINVAL,
            errno.ENOSYS,
            errno.ENOTSUP,
            getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
        }
        if error_code in unsupported_errors:
            raise OSError(
                errno.ENOTSUP,
                os.strerror(errno.ENOTSUP),
                str(target),
            )
        raise OSError(error_code, os.strerror(error_code), str(target))

    raise OSError(
        errno.ENOTSUP,
        os.strerror(errno.ENOTSUP),
        str(target),
    )


def verify_exposure_run(run_dir: Path) -> ExposureRunManifest:
    run_dir = Path(run_dir)
    if run_dir.is_symlink():
        raise ValueError("exposure run directory cannot be a symlink")
    run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(f"exposure run directory not found: {run_dir}")
    _validate_exact_files(run_dir)
    manifest = _load_canonical_model(
        run_dir / "manifest.json",
        ExposureRunManifest,
        label="exposure manifest",
    )
    if run_dir.name != manifest.run_id:
        raise ValueError("exposure run directory name contradicts manifest")
    if not manifest.artifacts:
        raise ValueError("published exposure manifest has no artifact evidence")
    _validate_stage(run_dir, manifest)
    return manifest


def _validate_analysis(
    manifest: ExposureRunManifest,
    result: ExposureAnalysisResult,
) -> None:
    validated = ExposureAnalysisResult.model_validate(
        result.model_dump(mode="python")
    )
    if validated != result:
        raise ValueError("analysis result did not round-trip")
    if manifest.source != result.source:
        raise ValueError("manifest source contradicts analysis source")
    if manifest.decision != result.decision:
        raise ValueError("manifest decision contradicts analysis decision")
    if manifest.unguarded_path_findings != result.unguarded_path_findings:
        raise ValueError("manifest findings contradict analysis findings")
    if manifest.limitations != result.limitations:
        raise ValueError("manifest limitations contradict analysis limitations")
    if manifest.unit_evidence_sha256 != result.unit_evidence_sha256:
        raise ValueError("manifest unit evidence SHA-256 mismatch")
    if (
        manifest.verification_inputs_sha256
        != result.verification_inputs_sha256
    ):
        raise ValueError("manifest verification inputs SHA-256 mismatch")
    if len(result.units) != manifest.attack_unit_count:
        raise ValueError("manifest attack-unit count contradicts analysis")
    if len({item.case_id for item in result.units}) != manifest.attack_case_count:
        raise ValueError("manifest attack-case count contradicts analysis")
    if result.verification_inputs.clean_case_count != manifest.benign_case_count:
        raise ValueError("clean-case witness contradicts manifest")
    if result.verification_inputs.benign_unit_count != manifest.benign_unit_count:
        raise ValueError("benign-unit witness contradicts manifest")


def _validate_stage(stage: Path, manifest: ExposureRunManifest) -> None:
    _validate_exact_files(stage)
    parsed_manifest = _load_canonical_model(
        stage / "manifest.json",
        ExposureRunManifest,
        label="exposure manifest",
    )
    if parsed_manifest != manifest:
        raise ValueError("exposure manifest did not round-trip")
    if manifest.schema_version.endswith("_v2"):
        if manifest.replay_dependencies is None:
            raise ValueError("v2 manifest requires replay dependencies")
        verify_replay_dependency_bytes(manifest.replay_dependencies)
    document = _load_canonical_model(
        stage / "summary.json",
        ExposureSummaryDocument,
        label="exposure summary",
    )
    units = _load_unit_rows(stage / "per_unit.jsonl")
    if len(units) != manifest.attack_unit_count:
        raise ValueError("per-unit row count contradicts manifest")
    if len({item.case_id for item in units}) != manifest.attack_case_count:
        raise ValueError("per-unit case count contradicts manifest")
    if document.source != manifest.source:
        raise ValueError("summary source contradicts manifest")
    if document.unguarded_path_findings != manifest.unguarded_path_findings:
        raise ValueError("summary findings contradict manifest")
    if document.limitations != manifest.limitations:
        raise ValueError("summary limitations contradict manifest")
    if document.verification_inputs.clean_case_count != manifest.benign_case_count:
        raise ValueError("summary clean-case witness contradicts manifest")
    if document.verification_inputs.benign_unit_count != manifest.benign_unit_count:
        raise ValueError("summary benign-unit witness contradicts manifest")
    unit_evidence_sha256 = compute_exposure_unit_evidence_sha256(units)
    verification_inputs_sha256 = (
        compute_exposure_verification_inputs_sha256(
            document.verification_inputs
        )
    )
    manifest_is_v2 = manifest.schema_version.endswith("_v2")
    expected_summary_schema = (
        "indirect_injection_exposure_summary_v2"
        if manifest_is_v2
        else "indirect_injection_exposure_summary_v1"
    )
    if document.schema_version != expected_summary_schema:
        raise ValueError("private manifest/summary schema versions disagree")
    if manifest_is_v2 and (
        document.unit_evidence_sha256 != unit_evidence_sha256
        or manifest.unit_evidence_sha256 != unit_evidence_sha256
    ):
        raise ValueError("unit evidence SHA-256 mismatch")
    if manifest_is_v2 and (
        document.verification_inputs_sha256 != verification_inputs_sha256
        or manifest.verification_inputs_sha256 != verification_inputs_sha256
    ):
        raise ValueError("verification inputs SHA-256 mismatch")
    ExposureAnalysisResult(
        schema_version="indirect_injection_exposure_analysis_v2",
        source=document.source,
        units=units,
        unit_evidence_sha256=unit_evidence_sha256,
        verification_inputs=document.verification_inputs,
        verification_inputs_sha256=verification_inputs_sha256,
        summary=document.summary,
        strata=document.strata,
        decision=document.decision,
        unguarded_path_findings=document.unguarded_path_findings,
        limitations=document.limitations,
    )
    if document.decision != manifest.decision:
        raise ValueError("decision does not recompute from exposure evidence")
    observed_failures = (stage / "failures.csv").read_bytes()
    expected_failures = _failure_bytes(
        units,
        document.unguarded_path_findings,
    )
    if observed_failures != expected_failures:
        raise ValueError("failures CSV does not recompute from exposure evidence")
    for name in ("commands.txt", "test_output.txt"):
        raw = (stage / name).read_bytes()
        text = _decode_utf8(raw, name)
        if text != _canonical_text(text, name):
            raise ValueError(f"{name} is not canonical LF-terminated text")
    for name, evidence in manifest.artifacts.items():
        artifact = stage / name
        if (
            artifact.stat().st_size != evidence.bytes
            or _sha256(artifact) != evidence.sha256
        ):
            raise ValueError(f"exposure artifact evidence mismatch: {name}")
    if (stage / "checksums.sha256").read_bytes() != _checksum_bytes(stage):
        raise ValueError("exposure checksum file does not match artifacts")


def _validate_exact_files(run_dir: Path) -> None:
    names = {item.name for item in run_dir.iterdir()}
    if names != set(PRIVATE_EXPOSURE_ARTIFACT_FILES):
        raise ValueError("exposure run has an unexpected artifact set")
    if any(
        item.is_symlink() or not item.is_file()
        for item in run_dir.iterdir()
    ):
        raise ValueError("exposure artifacts must be regular files")


def _load_unit_rows(path: Path) -> tuple[ExposureUnitObservation, ...]:
    raw = path.read_bytes()
    text = _decode_utf8(raw, "per_unit.jsonl")
    if not text.endswith("\n") or "\r" in text:
        raise ValueError("per-unit JSONL is not canonical LF-terminated text")
    lines = text.splitlines()
    if not lines or any(not line for line in lines):
        raise ValueError("per-unit JSONL must contain non-empty rows")
    rows: list[ExposureUnitObservation] = []
    for line_number, line in enumerate(lines, start=1):
        payload = _loads_unique(line, f"per-unit row {line_number}")
        if line.encode("utf-8") != _json_line(payload):
            raise ValueError(f"per-unit row {line_number} is not canonical JSON")
        rows.append(ExposureUnitObservation.model_validate_json(line))
    identities = tuple((item.case_id, item.unit_id) for item in rows)
    if identities != tuple(sorted(identities)):
        raise ValueError("per-unit rows are not in canonical identity order")
    if len(identities) != len(set(identities)):
        raise ValueError("per-unit identities must be unique")
    return tuple(rows)


def _unit_rows_bytes(units: Sequence[ExposureUnitObservation]) -> bytes:
    return b"".join(
        _json_line(item.model_dump(mode="json")) + b"\n" for item in units
    )


def _failure_bytes(
    units: Sequence[ExposureUnitObservation],
    findings: Sequence[UnguardedPathFinding],
) -> bytes:
    rows: list[dict[str, str]] = []
    for case_id, case_units in _group_unit_rows(units).items():
        representative = case_units[0]
        if not any(not item.replay_guard_reached for item in case_units):
            continue
        if not _case_has_downstream_exposure(representative):
            continue
        failures = tuple(
            name
            for name, field in _CASE_FAILURE_FIELDS
            if (
                getattr(representative, field) > 0
                if field == "case_blocked_egress_attempt_count"
                else getattr(representative, field)
            )
        )
        rows.append(
            {
                "scope": "case",
                "case_id": case_id,
                "unit_id": "",
                "primary_failure": "unreached_downstream_exposure",
                "all_failures": ";".join(failures),
            }
        )
    for finding in findings:
        rows.append(
            {
                "scope": "tool_path",
                "case_id": "",
                "unit_id": "",
                "primary_failure": f"unguarded_{finding.operation}_path",
                "all_failures": finding.evidence_id,
            }
        )
    rows.sort(
        key=lambda item: (
            item["scope"],
            item["case_id"],
            item["unit_id"],
            item["primary_failure"],
            item["all_failures"],
        )
    )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=_FAILURE_COLUMNS,
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _checksum_bytes(stage: Path) -> bytes:
    return "".join(
        f"{_sha256(stage / name)}  {name}\n"
        for name in _CONTENT_ARTIFACT_NAMES
    ).encode("utf-8")


def _canonical_text(value: str, label: str) -> str:
    if "\x00" in value:
        raise ValueError(f"{label} contains a NUL byte")
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.rstrip("\n") + "\n"


def _assert_content_free(payload: bytes, forbidden_texts: tuple[str, ...]) -> None:
    for value in forbidden_texts:
        if value.encode("utf-8") in payload:
            raise ValueError("exposure artifact contains forbidden content")


def _assert_text_content_free(
    value: str,
    forbidden_texts: tuple[str, ...],
) -> None:
    if any(forbidden in value for forbidden in forbidden_texts):
        raise ValueError("exposure artifact contains forbidden content")


def _assert_structured_content_free(
    value: Any,
    forbidden_texts: tuple[str, ...],
) -> None:
    if isinstance(value, str):
        _assert_text_content_free(value, forbidden_texts)
    elif isinstance(value, Mapping):
        for item in value.values():
            _assert_structured_content_free(item, forbidden_texts)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            _assert_structured_content_free(item, forbidden_texts)


def _assert_csv_content_free(
    payload: bytes,
    forbidden_texts: tuple[str, ...],
) -> None:
    text = _decode_utf8(payload, "failures.csv")
    rows = tuple(csv.DictReader(io.StringIO(text, newline="")))
    _assert_structured_content_free(rows, forbidden_texts)


def _load_canonical_model(
    path: Path,
    model_type: type[_StrictFrozenModel],
    *,
    label: str,
) -> Any:
    raw = path.read_bytes()
    text = _decode_utf8(raw, label)
    payload = _loads_unique(text, label)
    if raw != _json_bytes(payload):
        raise ValueError(f"{label} is not canonical JSON")
    return model_type.model_validate_json(raw)


class _DuplicateJsonKey(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def _loads_unique(value: str, label: str) -> Any:
    try:
        return json.loads(value, object_pairs_hook=_unique_object)
    except _DuplicateJsonKey as exc:
        raise ValueError(f"{label} contains a duplicate JSON key") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON") from exc


def _decode_utf8(value: bytes, label: str) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} is not valid UTF-8") from exc


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


__all__ = [
    "PRIVATE_EXPOSURE_ARTIFACT_FILES",
    "ExposureRunManifest",
    "ExposureSummaryDocument",
    "ExposureVerificationInputs",
    "publish_exposure_run",
    "recompute_exposure_summary",
    "verify_exposure_run",
]
