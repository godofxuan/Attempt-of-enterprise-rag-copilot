from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
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
    ExposureAnalysisResult,
    ExposureDecision,
    ExposureDepthMetrics,
    ExposureMetric,
    ExposureSourceEvidence,
    ExposureStratum,
    ExposureSummary,
    ExposureUnitObservation,
    UnguardedPathFinding,
    _build_exposure_strata,
    _case_has_downstream_exposure,
    _decide_exposure,
    _group_unit_rows,
    _validate_repeated_case_rows,
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


class ExposureVerificationInputs(_StrictFrozenModel):
    """Content-free source aggregates unavailable in attack-unit rows."""

    clean_task_success_count: int = Field(ge=0)
    clean_case_count: Literal[12]
    benign_quarantine_count: int = Field(ge=0)
    benign_unit_count: Literal[32]
    model_error_count: int = Field(ge=0)
    blocked_egress_attempt_count: int = Field(ge=0)
    consumed_tool_paths_guard_covered: Literal[True]

    @model_validator(mode="after")
    def validate_counts(self) -> ExposureVerificationInputs:
        if self.clean_task_success_count > self.clean_case_count:
            raise ValueError("clean success count cannot exceed clean case count")
        if self.benign_quarantine_count > self.benign_unit_count:
            raise ValueError(
                "benign quarantine count cannot exceed benign unit count"
            )
        return self


class ExposureRunManifest(_StrictFrozenModel):
    schema_version: Literal["indirect_injection_exposure_run_manifest_v1"]
    producer: Literal["enterprise_agentic_rag_v2"]
    run_id: str
    created_at_utc: datetime
    source: ExposureSourceEvidence
    guard_ruleset_path: str
    guard_ruleset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_path: str
    evaluator_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
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
        if any(not value for value in self.limitations) or len(
            self.limitations
        ) != len(set(self.limitations)):
            raise ValueError("limitations must be non-empty and unique")
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
    schema_version: Literal["indirect_injection_exposure_summary_v1"]
    source: ExposureSourceEvidence
    verification_inputs: ExposureVerificationInputs
    summary: ExposureSummary
    strata: tuple[ExposureStratum, ...]
    decision: ExposureDecision
    unguarded_path_findings: tuple[UnguardedPathFinding, ...]
    limitations: tuple[str, ...] = Field(min_length=1)


def recompute_exposure_summary(
    units: Sequence[ExposureUnitObservation],
    verification_inputs: ExposureVerificationInputs,
) -> ExposureSummary:
    """Recompute persisted metrics without raw fixtures, Guard, or a model."""

    frozen_units = tuple(units)
    identities = tuple((item.case_id, item.unit_id) for item in frozen_units)
    if len(identities) != len(set(identities)):
        raise ValueError("analysis unit identities must be unique")
    _validate_repeated_case_rows(frozen_units)
    rows_by_case = _group_unit_rows(frozen_units)
    case_rows = {case_id: rows[0] for case_id, rows in rows_by_case.items()}
    attack_unit_count = len(frozen_units)
    search_unit_count = sum(
        item.counterfactual_search_applicable for item in frozen_units
    )
    live_reached = sum(
        item.live_case_guard_reached_count for item in case_rows.values()
    )
    live_quarantined = sum(
        item.live_case_guard_quarantined_count for item in case_rows.values()
    )
    replay_reached = sum(item.replay_guard_reached for item in frozen_units)
    replay_quarantined = sum(
        item.replay_guard_quarantined for item in frozen_units
    )
    if (live_reached, live_quarantined) != (
        replay_reached,
        replay_quarantined,
    ):
        raise ValueError("replay/live aggregate mismatch")
    unreached_case_rows = tuple(
        rows[0]
        for rows in rows_by_case.values()
        if any(not item.replay_guard_reached for item in rows)
    )

    depths: list[ExposureDepthMetrics] = []
    for depth in COUNTERFACTUAL_DEPTHS:
        search_flag = f"counterfactual_search_reached_at_{depth}"
        depths.append(
            ExposureDepthMetrics(
                depth=depth,
                counterfactual_search_reach=ExposureMetric.from_counts(
                    sum(
                        getattr(item, search_flag) is True
                        for item in frozen_units
                    ),
                    search_unit_count,
                    applicable=search_unit_count > 0,
                ),
                counterfactual_total_reach=ExposureMetric.from_counts(
                    sum(
                        item.replay_guard_reached
                        or getattr(item, search_flag) is True
                        for item in frozen_units
                    ),
                    attack_unit_count,
                    applicable=attack_unit_count > 0,
                ),
                replay_additional_scan_units=sum(
                    getattr(
                        item,
                        f"case_replay_additional_scan_units_at_{depth}",
                    )
                    for item in case_rows.values()
                ),
                replay_additional_scan_input_chars=sum(
                    getattr(
                        item,
                        f"case_replay_additional_scan_input_chars_at_{depth}",
                    )
                    for item in case_rows.values()
                ),
            )
        )

    return ExposureSummary(
        attack_unit_count=attack_unit_count,
        search_addressable_attack_unit_count=search_unit_count,
        candidate_pool_presence=ExposureMetric.from_counts(
            sum(item.candidate_pool_present for item in frozen_units),
            attack_unit_count,
            applicable=attack_unit_count > 0,
        ),
        replay_selected_attack_units=ExposureMetric.from_counts(
            sum(item.replay_selected_for_evidence for item in frozen_units),
            attack_unit_count,
            applicable=attack_unit_count > 0,
        ),
        live_guard_reach=ExposureMetric.from_counts(
            live_reached,
            attack_unit_count,
            applicable=attack_unit_count > 0,
        ),
        live_guard_quarantine=ExposureMetric.from_counts(
            live_quarantined,
            attack_unit_count,
            applicable=attack_unit_count > 0,
        ),
        replay_guard_reach=ExposureMetric.from_counts(
            replay_reached,
            attack_unit_count,
            applicable=attack_unit_count > 0,
        ),
        replay_guard_quarantine=ExposureMetric.from_counts(
            replay_quarantined,
            attack_unit_count,
            applicable=attack_unit_count > 0,
        ),
        quarantine_given_live_guard_reach=ExposureMetric.from_counts(
            live_quarantined,
            live_reached,
            applicable=live_reached > 0,
        ),
        replay_live_aggregate_match=True,
        consumed_tool_paths_guard_covered=(
            verification_inputs.consumed_tool_paths_guard_covered
        ),
        unreached_attack_unit_count=attack_unit_count - replay_reached,
        unreached_case_count=len(unreached_case_rows),
        unreached_case_downstream_exposure=ExposureMetric.from_counts(
            sum(
                _case_has_downstream_exposure(item)
                for item in unreached_case_rows
            ),
            len(unreached_case_rows),
            applicable=bool(unreached_case_rows),
        ),
        unreached_case_attack_success=ExposureMetric.from_counts(
            sum(item.case_attack_success for item in unreached_case_rows),
            len(unreached_case_rows),
            applicable=bool(unreached_case_rows),
        ),
        clean_task_success=ExposureMetric.from_counts(
            verification_inputs.clean_task_success_count,
            verification_inputs.clean_case_count,
            applicable=verification_inputs.clean_case_count > 0,
        ),
        benign_quarantine=ExposureMetric.from_counts(
            verification_inputs.benign_quarantine_count,
            verification_inputs.benign_unit_count,
            applicable=verification_inputs.benign_unit_count > 0,
        ),
        model_error_count=verification_inputs.model_error_count,
        blocked_egress_attempt_count=(
            verification_inputs.blocked_egress_attempt_count
        ),
        depths=tuple(depths),
    )


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
    verification_inputs = _verification_inputs_from_result(result)
    _validate_analysis(manifest, result, verification_inputs)
    canonical_commands = _canonical_text(commands, "commands")
    canonical_test_output = _canonical_text(test_output, "test output")

    output_root = Path(root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    target = (output_root / manifest.run_id).resolve()
    if target.parent != output_root:
        raise ValueError("run ID resolves outside output root")
    if target.exists():
        raise FileExistsError(f"exposure output run already exists: {target}")
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{manifest.run_id}.staging-",
            dir=output_root,
        )
    ).resolve()
    try:
        document = ExposureSummaryDocument(
            schema_version="indirect_injection_exposure_summary_v1",
            source=result.source,
            verification_inputs=verification_inputs,
            summary=result.summary,
            strata=result.strata,
            decision=result.decision,
            unguarded_path_findings=result.unguarded_path_findings,
            limitations=result.limitations,
        )
        (stage / "summary.json").write_bytes(
            _json_bytes(document.model_dump(mode="json"))
        )
        sorted_units = tuple(
            sorted(result.units, key=lambda item: (item.case_id, item.unit_id))
        )
        (stage / "per_unit.jsonl").write_bytes(_unit_rows_bytes(sorted_units))
        (stage / "failures.csv").write_bytes(
            _failure_bytes(sorted_units, result.unguarded_path_findings)
        )
        (stage / "commands.txt").write_text(
            canonical_commands,
            encoding="utf-8",
            newline="",
        )
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
        manifest_bytes = _json_bytes(final_manifest.model_dump(mode="json"))
        _assert_content_free(manifest_bytes, forbidden_texts)
        (stage / "manifest.json").write_bytes(manifest_bytes)
        _validate_stage(stage, final_manifest)
        if target.exists():
            raise FileExistsError(
                f"exposure output run already exists: {target}"
            )
        stage.rename(target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def verify_exposure_run(run_dir: Path) -> ExposureRunManifest:
    run_dir = Path(run_dir).resolve()
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


def _verification_inputs_from_result(
    result: ExposureAnalysisResult,
) -> ExposureVerificationInputs:
    return ExposureVerificationInputs(
        clean_task_success_count=result.summary.clean_task_success.numerator,
        clean_case_count=result.summary.clean_task_success.denominator,
        benign_quarantine_count=result.summary.benign_quarantine.numerator,
        benign_unit_count=result.summary.benign_quarantine.denominator,
        model_error_count=result.summary.model_error_count,
        blocked_egress_attempt_count=(
            result.summary.blocked_egress_attempt_count
        ),
        consumed_tool_paths_guard_covered=(
            result.summary.consumed_tool_paths_guard_covered
        ),
    )


def _validate_analysis(
    manifest: ExposureRunManifest,
    result: ExposureAnalysisResult,
    verification_inputs: ExposureVerificationInputs,
) -> None:
    if manifest.source != result.source:
        raise ValueError("manifest source contradicts analysis source")
    if manifest.decision != result.decision:
        raise ValueError("manifest decision contradicts analysis decision")
    if manifest.unguarded_path_findings != result.unguarded_path_findings:
        raise ValueError("manifest findings contradict analysis findings")
    if manifest.limitations != result.limitations:
        raise ValueError("manifest limitations contradict analysis limitations")
    if len(result.units) != manifest.attack_unit_count:
        raise ValueError("manifest attack-unit count contradicts analysis")
    if len({item.case_id for item in result.units}) != manifest.attack_case_count:
        raise ValueError("manifest attack-case count contradicts analysis")
    if verification_inputs.clean_case_count != manifest.benign_case_count:
        raise ValueError("clean-case witness contradicts manifest")
    if verification_inputs.benign_unit_count != manifest.benign_unit_count:
        raise ValueError("benign-unit witness contradicts manifest")
    recomputed = recompute_exposure_summary(result.units, verification_inputs)
    if recomputed != result.summary:
        raise ValueError("analysis summary does not recompute")
    if _build_exposure_strata(result.units) != result.strata:
        raise ValueError("analysis strata do not recompute")
    if _decide_exposure(recomputed, result.unguarded_path_findings) != result.decision:
        raise ValueError("analysis decision does not recompute")


def _validate_stage(stage: Path, manifest: ExposureRunManifest) -> None:
    _validate_exact_files(stage)
    parsed_manifest = _load_canonical_model(
        stage / "manifest.json",
        ExposureRunManifest,
        label="exposure manifest",
    )
    if parsed_manifest != manifest:
        raise ValueError("exposure manifest did not round-trip")
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
    recomputed = recompute_exposure_summary(units, document.verification_inputs)
    if recomputed != document.summary:
        raise ValueError("summary does not recompute from per-unit evidence")
    recomputed_strata = _build_exposure_strata(units)
    if recomputed_strata != document.strata:
        raise ValueError("strata do not recompute from per-unit evidence")
    decision = _decide_exposure(
        recomputed,
        document.unguarded_path_findings,
    )
    if decision != document.decision or decision != manifest.decision:
        raise ValueError("decision does not recompute from exposure evidence")
    ExposureAnalysisResult(
        schema_version="indirect_injection_exposure_analysis_v1",
        source=document.source,
        units=units,
        summary=recomputed,
        strata=recomputed_strata,
        decision=decision,
        unguarded_path_findings=document.unguarded_path_findings,
        limitations=document.limitations,
    )
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
        for item in case_units:
            if item.replay_guard_reached:
                continue
            rows.append(
                {
                    "scope": "unit",
                    "case_id": case_id,
                    "unit_id": item.unit_id,
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
