from __future__ import annotations

import csv
import hashlib
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.evaluation.indirect_injection_arm_order import (
    CounterbalancedArmOrderPlan,
)
from app.evaluation.indirect_injection_live_runner import (
    LiveCaseObservation,
    LivePairedResult,
    LivePairedResultV2,
    _summarize_live_mode,
)
from app.evaluation.indirect_injection_runner import (
    SecurityCaseResult,
    _build_behavior_gate,
    _mode_result,
)
from app.evaluation.indirect_injection_writer import (
    ArtifactEvidence,
    EvaluatorSecurityProvenance,
    GitSecurityProvenance,
    GuardSecurityProvenance,
    SecurityDataProvenance,
    _assert_content_free,
    validate_security_run_id,
)


LiveRunStatus = Literal["FAILED", "COMPLETED WITH OBSERVATIONS"]
_ARTIFACT_NAMES = {
    "summary.json",
    "per_case.jsonl",
    "failures.csv",
    "red_green_evidence.md",
    "commands.txt",
    "test_output.txt",
    "checksums.sha256",
}
_CHECKSUM_CONTENT_NAMES = tuple(sorted(_ARTIFACT_NAMES - {"checksums.sha256"}))


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


class OllamaModelIdentity(_StrictFrozenModel):
    requested_name: str = Field(min_length=1, max_length=200)
    resolved_name: str = Field(min_length=1, max_length=200)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    format: str = Field(min_length=1, max_length=100)
    family: str = Field(min_length=1, max_length=100)
    parameter_size: str = Field(min_length=1, max_length=100)
    quantization_level: str = Field(min_length=1, max_length=100)
    context_length: int | None = Field(default=None, ge=1)
    embedding_length: int | None = Field(default=None, ge=1)
    capabilities: tuple[str, ...] = Field(min_length=1, max_length=20)

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("model capabilities must be unique")
        return values


class LiveEnvironmentProvenance(_StrictFrozenModel):
    python_version: str = Field(min_length=1, max_length=100)
    platform: str = Field(min_length=1, max_length=300)
    dependency_snapshot_path: str
    dependency_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    installed_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    installed_package_count: int = Field(ge=1)
    ollama_version: str = Field(min_length=1, max_length=100)
    ollama_endpoint: str = Field(pattern=r"^http://(?:127\.0\.0\.1|localhost|\[::1\]):\d+$")

    @field_validator("dependency_snapshot_path")
    @classmethod
    def validate_dependency_path(cls, value: str) -> str:
        return _safe_relative(value, "dependency snapshot path")


class LiveModelProvenance(_StrictFrozenModel):
    embedding: OllamaModelIdentity
    chat: OllamaModelIdentity
    evidence_model: Literal["NOT_USED_D7_LIVE_PAIRED"]
    temperature: Literal[0.0]
    structured_output_variant: Literal["generation-v2-json-schema"]
    think: Literal[False]
    max_attempts: int = Field(ge=1, le=2)

    @model_validator(mode="after")
    def validate_model_capabilities(self) -> LiveModelProvenance:
        if "embedding" not in self.embedding.capabilities:
            raise ValueError("embedding model identity lacks embedding capability")
        if "completion" not in self.chat.capabilities:
            raise ValueError("chat model identity lacks completion capability")
        return self


class LiveIndexReference(_StrictFrozenModel):
    role: Literal["production_active_reference", "security_fixture_runtime"]
    run_id: str = Field(min_length=1, max_length=200)
    active_pointer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_model: str = Field(min_length=1, max_length=200)
    embedding_dimension: int = Field(ge=1)
    indexed_chunk_count: int = Field(ge=1)


class LiveRetrievalProvenance(_StrictFrozenModel):
    production_active_index: LiveIndexReference
    security_fixture_index: LiveIndexReference
    chunking: Literal["post-parser-security-fixture-projection-v1"]
    top_k: Literal[1]
    candidate_k: Literal[4]
    max_search_calls: Literal[1]
    max_open_calls: Literal[1]
    max_steps: Literal[3]
    max_context_chars: Literal[50_000]
    index_embedding_call_count: int = Field(ge=1)
    embedding_request_count: int = Field(ge=0)
    embedding_delegate_call_count: int = Field(ge=0)
    embedding_cache_hit_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_retrieval(self) -> LiveRetrievalProvenance:
        if self.production_active_index.role != "production_active_reference":
            raise ValueError("production index has the wrong role")
        if self.security_fixture_index.role != "security_fixture_runtime":
            raise ValueError("security fixture index has the wrong role")
        if self.embedding_request_count != (
            self.embedding_delegate_call_count + self.embedding_cache_hit_count
        ):
            raise ValueError("retrieval embedding accounting is inconsistent")
        return self


class LiveObservationDecision(_StrictFrozenModel):
    status: LiveRunStatus
    protocol_complete: bool
    pair_input_consistent: bool
    deterministic_threshold_diagnostic_passed: bool

    @model_validator(mode="after")
    def validate_status(self) -> LiveObservationDecision:
        expected: LiveRunStatus = (
            "COMPLETED WITH OBSERVATIONS" if self.protocol_complete else "FAILED"
        )
        if self.status != expected:
            raise ValueError("observation status must match protocol completion")
        if self.protocol_complete and not self.pair_input_consistent:
            raise ValueError("a complete paired run requires pair consistency")
        return self


class LiveSecurityRunManifest(_StrictFrozenModel):
    schema_version: Literal["indirect_injection_live_security_run_manifest_v1"]
    producer: Literal["enterprise_agentic_rag_v2"]
    run_id: str
    suite: Literal["retrieved_content_indirect_injection"]
    split: Literal["dev", "test"]
    mode: Literal["local_live_paired"]
    started_at_utc: datetime
    completed_at_utc: datetime
    status: LiveRunStatus
    git: GitSecurityProvenance
    environment: LiveEnvironmentProvenance
    models: LiveModelProvenance
    guard: GuardSecurityProvenance
    data: SecurityDataProvenance
    evaluator: EvaluatorSecurityProvenance
    retrieval: LiveRetrievalProvenance
    observation: LiveObservationDecision
    artifacts: Mapping[str, ArtifactEvidence] = Field(default_factory=dict)
    limitations: tuple[str, ...] = Field(min_length=1, max_length=10)

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        return validate_security_run_id(value)

    @model_validator(mode="after")
    def validate_manifest(self) -> LiveSecurityRunManifest:
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("run completion cannot precede start")
        if self.status != self.observation.status:
            raise ValueError("manifest/observation statuses differ")
        expected_exit = 0 if self.status == "COMPLETED WITH OBSERVATIONS" else 1
        if self.evaluator.exit_code != expected_exit:
            raise ValueError("evaluator exit code does not match live status")
        if (
            self.retrieval.security_fixture_index.corpus_sha256
            != self.data.fixture_manifest_sha256
        ):
            raise ValueError("security index corpus hash must match fixture hash")
        if (
            self.retrieval.security_fixture_index.embedding_model
            not in {
                self.models.embedding.requested_name,
                self.models.embedding.resolved_name,
            }
        ):
            raise ValueError("security index/model embedding identities differ")
        artifact_names = set(self.artifacts)
        if artifact_names not in (set(), _ARTIFACT_NAMES):
            raise ValueError("live manifest artifacts must be empty or complete")
        if any(name != item.path for name, item in self.artifacts.items()):
            raise ValueError("artifact key and path must match")
        if len(self.limitations) != len(set(self.limitations)):
            raise ValueError("manifest limitations must be unique")
        return self


class LiveSecurityRunManifestV2(LiveSecurityRunManifest):
    schema_version: Literal["indirect_injection_live_security_run_manifest_v2"]
    mode: Literal["local_live_paired_counterbalanced"]
    arm_order: CounterbalancedArmOrderPlan

    @model_validator(mode="after")
    def validate_arm_order(self) -> LiveSecurityRunManifestV2:
        if self.arm_order.case_count != self.data.dataset_case_count:
            raise ValueError("live v2 manifest arm-order/data case counts differ")
        return self


def resolve_ollama_model_identity(
    tags_payload: Mapping[str, object],
    requested_name: str,
) -> OllamaModelIdentity:
    raw_models = tags_payload.get("models")
    if not isinstance(raw_models, list):
        raise ValueError("Ollama tags response has no model list")
    candidates: list[Mapping[str, object]] = []
    for item in raw_models:
        if not isinstance(item, Mapping):
            continue
        names = {str(item.get("name", "")), str(item.get("model", ""))}
        if requested_name in names:
            candidates.append(item)
            continue
        if ":" not in requested_name and f"{requested_name}:latest" in names:
            candidates.append(item)
    if len(candidates) != 1:
        raise ValueError(f"Ollama model identity is missing or ambiguous: {requested_name}")
    item = candidates[0]
    details = item.get("details")
    if not isinstance(details, Mapping):
        raise ValueError("Ollama model identity has no details")
    capabilities = item.get("capabilities")
    if not isinstance(capabilities, list):
        raise ValueError("Ollama model identity has no capabilities")
    return OllamaModelIdentity(
        requested_name=requested_name,
        resolved_name=str(item.get("name") or item.get("model") or ""),
        digest=str(item.get("digest") or ""),
        size_bytes=int(item.get("size") or 0),
        format=str(details.get("format") or ""),
        family=str(details.get("family") or ""),
        parameter_size=str(details.get("parameter_size") or ""),
        quantization_level=str(details.get("quantization_level") or ""),
        context_length=_optional_positive_int(details.get("context_length")),
        embedding_length=_optional_positive_int(details.get("embedding_length")),
        capabilities=tuple(sorted(str(value) for value in capabilities)),
    )


def publish_live_security_run(
    root: Path,
    manifest: LiveSecurityRunManifest,
    result: LivePairedResult,
    *,
    paired_evidence: str,
    commands: str,
    test_output: str,
    forbidden_texts: tuple[str, ...],
) -> Path:
    if not forbidden_texts or any(not value for value in forbidden_texts):
        raise ValueError("a non-empty forbidden text policy is required")
    _validate_consistency(manifest, result)
    output_root = Path(root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    target = (output_root / manifest.run_id).resolve()
    if target.parent != output_root:
        raise ValueError("run ID resolves outside output root")
    if target.exists():
        raise FileExistsError(f"live security output run already exists: {target}")

    stage = Path(
        tempfile.mkdtemp(prefix=f".{manifest.run_id}.staging-", dir=output_root)
    ).resolve()
    try:
        _write_content_artifacts(
            stage,
            manifest,
            result,
            paired_evidence=paired_evidence,
            commands=commands,
            test_output=test_output,
        )
        for name in _CHECKSUM_CONTENT_NAMES:
            _assert_content_free((stage / name).read_bytes(), forbidden_texts)
        checksum_payload = "".join(
            f"{_sha256(stage / name)}  {name}\n"
            for name in _CHECKSUM_CONTENT_NAMES
        ).encode("utf-8")
        (stage / "checksums.sha256").write_bytes(checksum_payload)
        artifact_evidence = {
            name: ArtifactEvidence(
                path=name,
                bytes=(stage / name).stat().st_size,
                sha256=_sha256(stage / name),
            )
            for name in sorted(_ARTIFACT_NAMES)
        }
        final_payload = manifest.model_dump(mode="python")
        final_payload["artifacts"] = {
            name: item.model_dump(mode="json")
            for name, item in artifact_evidence.items()
        }
        final_manifest = type(manifest).model_validate(final_payload)
        manifest_bytes = _json_bytes(final_manifest.model_dump(mode="json"))
        _assert_content_free(manifest_bytes, forbidden_texts)
        (stage / "manifest.json").write_bytes(manifest_bytes)
        _validate_stage(stage, final_manifest)
        stage.rename(target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def _validate_consistency(
    manifest: LiveSecurityRunManifest,
    result: LivePairedResult,
) -> None:
    manifest_is_v2 = isinstance(manifest, LiveSecurityRunManifestV2)
    result_is_v2 = isinstance(result, LivePairedResultV2)
    if manifest_is_v2 != result_is_v2:
        raise ValueError("live manifest/result schema versions differ")
    if manifest_is_v2 and result_is_v2 and manifest.arm_order != result.arm_order:
        raise ValueError("live manifest/result arm-order plans differ")
    if manifest.split != result.split:
        raise ValueError("live manifest/result split mismatch")
    if manifest.status != result.status:
        raise ValueError("live manifest/result status mismatch")
    if manifest.observation.protocol_complete != result.protocol_complete:
        raise ValueError("live manifest/result protocol completion mismatch")
    if manifest.observation.pair_input_consistent != result.pair_input_consistent:
        raise ValueError("live manifest/result pair consistency mismatch")
    if (
        manifest.observation.deterministic_threshold_diagnostic_passed
        != result.security.gate.passed
    ):
        raise ValueError("live manifest/result threshold diagnostic mismatch")
    if manifest.data.dataset_case_count != len(result.guard_on):
        raise ValueError("live manifest/result case count mismatch")
    for field in (
        "embedding_request_count",
        "embedding_delegate_call_count",
        "embedding_cache_hit_count",
    ):
        if getattr(manifest.retrieval, field) != getattr(result, field):
            raise ValueError(f"live manifest/result {field} mismatch")


def _write_content_artifacts(
    stage: Path,
    manifest: LiveSecurityRunManifest,
    result: LivePairedResult,
    *,
    paired_evidence: str,
    commands: str,
    test_output: str,
) -> None:
    summary = _summary_from_result(manifest, result)
    (stage / "summary.json").write_bytes(_json_bytes(summary))
    rows = (
        _v2_per_case_rows(result)
        if isinstance(result, LivePairedResultV2)
        else _v1_per_case_rows(result)
    )
    (stage / "per_case.jsonl").write_bytes(b"".join(rows))
    _write_failures(stage / "failures.csv", result)
    (stage / "red_green_evidence.md").write_text(
        _ensure_newline(paired_evidence),
        encoding="utf-8",
    )
    (stage / "commands.txt").write_text(
        _ensure_newline(commands),
        encoding="utf-8",
    )
    (stage / "test_output.txt").write_text(
        _ensure_newline(test_output),
        encoding="utf-8",
    )


def _summary_from_result(
    manifest: LiveSecurityRunManifest,
    result: LivePairedResult,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "schema_version": result.schema_version,
        "producer": manifest.producer,
        "run_id": manifest.run_id,
        "split": result.split,
        "mode": manifest.mode,
        "status": result.status,
        "protocol_complete": result.protocol_complete,
        "pair_input_consistent": result.pair_input_consistent,
        "embedding": {
            "request_count": result.embedding_request_count,
            "delegate_call_count": result.embedding_delegate_call_count,
            "cache_hit_count": result.embedding_cache_hit_count,
        },
        "guard_off_security": result.security.guard_off.summary.model_dump(
            mode="json"
        ),
        "guard_on_security": result.security.guard_on.summary.model_dump(
            mode="json"
        ),
        "guard_off_live": result.guard_off_summary.model_dump(mode="json"),
        "guard_on_live": result.guard_on_summary.model_dump(mode="json"),
        "deterministic_threshold_diagnostic": result.security.gate.model_dump(
            mode="json"
        ),
    }
    if isinstance(result, LivePairedResultV2):
        summary["arm_order"] = {
            "schema_version": result.arm_order.schema_version,
            "protocol_id": result.arm_order.protocol_id,
            "hash_algorithm": result.arm_order.hash_algorithm,
            "allocation_method": result.arm_order.allocation_method,
            "case_count": result.arm_order.case_count,
            "off_then_on_count": result.arm_order.off_then_on_count,
            "on_then_off_count": result.arm_order.on_then_off_count,
        }
    return summary


def _v1_per_case_rows(result: LivePairedResult) -> list[bytes]:
    rows: list[bytes] = []
    for mode_security, mode_live in (
        (result.security.guard_off.cases, result.guard_off),
        (result.security.guard_on.cases, result.guard_on),
    ):
        for security, live in zip(mode_security, mode_live):
            rows.append(
                _json_bytes(
                    {
                        "security": security.model_dump(mode="json"),
                        "live": live.model_dump(mode="json"),
                    },
                    compact=True,
                )
            )
    return rows


def _v2_per_case_rows(result: LivePairedResultV2) -> list[bytes]:
    security_by_mode = {
        "off": {item.case_id: item for item in result.security.guard_off.cases},
        "on": {item.case_id: item for item in result.security.guard_on.cases},
    }
    live_by_mode = {
        "off": {item.case_id: item for item in result.guard_off},
        "on": {item.case_id: item for item in result.guard_on},
    }
    execution_by_case_mode = {
        (event.case_id, event.guard_mode): event
        for event in result.arm_execution
    }
    rows: list[bytes] = []
    for assignment in result.arm_order.assignments:
        for position, guard_mode in enumerate(assignment.modes(), start=1):
            security = security_by_mode[guard_mode][assignment.case_id]
            live = live_by_mode[guard_mode][assignment.case_id]
            execution = execution_by_case_mode[(assignment.case_id, guard_mode)]
            rows.append(
                _json_bytes(
                    {
                        "arm_execution": {
                            "protocol_id": result.arm_order.protocol_id,
                            "case_hash": assignment.case_hash,
                            "hash_rank": assignment.hash_rank,
                            "arm_order": assignment.arm_order,
                            "execution_index": execution.execution_index,
                            "arm_position": execution.arm_position,
                        },
                        "security": security.model_dump(mode="json"),
                        "live": live.model_dump(mode="json"),
                    },
                    compact=True,
                )
            )
    return rows


def _write_failures(path: Path, result: LivePairedResult) -> None:
    fields = ("scope", "guard_mode", "case_id", "primary_failure", "all_failures")
    rows: list[dict[str, str]] = []
    security_by_mode = {
        "off": {item.case_id: item for item in result.security.guard_off.cases},
        "on": {item.case_id: item for item in result.security.guard_on.cases},
    }
    for guard_mode, observations in (
        ("off", result.guard_off),
        ("on", result.guard_on),
    ):
        for item in observations:
            failures: list[str] = []
            if not item.retrieval_completed:
                failures.append("retrieval_incomplete")
            failures.extend(item.model_error_codes)
            if item.blocked_egress_attempt_count:
                failures.append("blocked_external_egress_attempt")
            if guard_mode == "on":
                security = security_by_mode[guard_mode][item.case_id]
                failures.extend(
                    _v2_case_failure_codes(security, item)
                    if isinstance(result, LivePairedResultV2)
                    else security.failure_codes
                )
            if failures:
                rows.append(
                    {
                        "scope": "case",
                        "guard_mode": guard_mode,
                        "case_id": item.case_id,
                        "primary_failure": failures[0],
                        "all_failures": ";".join(dict.fromkeys(failures)),
                    }
                )
    if not result.pair_input_consistent:
        rows.append(
            {
                "scope": "protocol",
                "guard_mode": "paired",
                "case_id": "",
                "primary_failure": "pair_input_mismatch",
                "all_failures": "pair_input_mismatch",
            }
        )
    for failure in result.security.gate.failures:
        rows.append(
            {
                "scope": "deterministic_threshold_diagnostic",
                "guard_mode": "paired",
                "case_id": "",
                "primary_failure": failure,
                "all_failures": failure,
            }
        )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _v2_case_failure_codes(
    security: SecurityCaseResult,
    observation: LiveCaseObservation,
) -> tuple[str, ...]:
    failures = [
        code for code in security.failure_codes if code != "attack_unit_admitted"
    ]
    if "attack_unit_admitted" not in security.failure_codes:
        return tuple(failures)

    missed = (
        observation.attack_unit_reached_guard_count
        - observation.attack_unit_quarantined_count
    )
    unreached = (
        observation.attack_unit_count
        - observation.attack_unit_reached_guard_count
    )
    if missed:
        failures.append("attack_unit_missed_by_guard")
    if unreached:
        failures.append("attack_unit_unreached")
    if not missed and not unreached:
        raise ValueError("v2 attack-unit failure contradicts live reach evidence")
    return tuple(failures)


def _validate_v2_per_case_rows(
    path: Path,
    manifest: LiveSecurityRunManifestV2,
) -> tuple[
    tuple[SecurityCaseResult, ...],
    tuple[SecurityCaseResult, ...],
    tuple[LiveCaseObservation, ...],
    tuple[LiveCaseObservation, ...],
]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) != manifest.arm_order.case_count * 2:
        raise ValueError("v2 per-case row count does not match the arm-order plan")

    execution_indexes: list[int] = []
    security_by_mode: dict[str, dict[str, SecurityCaseResult]] = {
        "off": {},
        "on": {},
    }
    live_by_mode: dict[str, dict[str, LiveCaseObservation]] = {
        "off": {},
        "on": {},
    }
    for pair_index, assignment in enumerate(manifest.arm_order.assignments):
        pair_lines = lines[pair_index * 2 : pair_index * 2 + 2]
        pair_execution_indexes: list[int] = []
        for position, (guard_mode, line) in enumerate(
            zip(assignment.modes(), pair_lines),
            start=1,
        ):
            payload = json.loads(line)
            if not isinstance(payload, dict) or set(payload) != {
                "arm_execution",
                "security",
                "live",
            }:
                raise ValueError("v2 per-case row has unexpected keys")
            arm_execution = payload["arm_execution"]
            security = payload["security"]
            live = payload["live"]
            if not isinstance(arm_execution, dict) or set(arm_execution) != {
                "protocol_id",
                "case_hash",
                "hash_rank",
                "arm_order",
                "execution_index",
                "arm_position",
            }:
                raise ValueError("v2 per-case arm execution has unexpected keys")
            execution_index = arm_execution["execution_index"]
            if (
                not isinstance(execution_index, int)
                or isinstance(execution_index, bool)
                or execution_index < 1
            ):
                raise ValueError("v2 per-case execution index is invalid")
            execution_indexes.append(execution_index)
            pair_execution_indexes.append(execution_index)
            if arm_execution["arm_position"] != position:
                raise ValueError("v2 per-case arm position contradicts row order")
            expected_arm_execution = {
                "protocol_id": manifest.arm_order.protocol_id,
                "case_hash": assignment.case_hash,
                "hash_rank": assignment.hash_rank,
                "arm_order": assignment.arm_order,
                "execution_index": execution_index,
                "arm_position": position,
            }
            if arm_execution != expected_arm_execution:
                raise ValueError("v2 per-case arm evidence contradicts the manifest")
            if not isinstance(security, dict) or not isinstance(live, dict):
                raise ValueError("v2 per-case security/live evidence must be objects")
            typed_security = SecurityCaseResult.model_validate_json(
                json.dumps(security, ensure_ascii=False)
            )
            typed_live = LiveCaseObservation.model_validate_json(
                json.dumps(live, ensure_ascii=False)
            )
            if typed_security.case_id != assignment.case_id or (
                typed_live.case_id != assignment.case_id
            ):
                raise ValueError("v2 per-case case ID contradicts the manifest")
            if (
                typed_security.guard_mode != guard_mode
                or typed_live.guard_mode != guard_mode
            ):
                raise ValueError("v2 per-case guard mode contradicts arm order")
            if len(typed_security.candidate_order) != (
                typed_live.retrieval_candidate_count
            ):
                raise ValueError("v2 per-case retrieval candidate counts differ")
            if len(typed_security.attack_unit_ids) != typed_live.attack_unit_count:
                raise ValueError("v2 per-case attack unit counts differ")
            security_by_mode[guard_mode][assignment.case_id] = typed_security
            live_by_mode[guard_mode][assignment.case_id] = typed_live
        if pair_execution_indexes[1] != pair_execution_indexes[0] + 1:
            raise ValueError("v2 per-case paired execution indexes are not adjacent")
    if sorted(execution_indexes) != list(range(1, len(lines) + 1)):
        raise ValueError("v2 per-case execution indexes are not exact")
    case_ids = manifest.arm_order.case_ids()
    return (
        tuple(security_by_mode["off"][case_id] for case_id in case_ids),
        tuple(security_by_mode["on"][case_id] for case_id in case_ids),
        tuple(live_by_mode["off"][case_id] for case_id in case_ids),
        tuple(live_by_mode["on"][case_id] for case_id in case_ids),
    )


def _validate_v2_summary(
    summary: object,
    manifest: LiveSecurityRunManifestV2,
    parsed_rows: tuple[
        tuple[SecurityCaseResult, ...],
        tuple[SecurityCaseResult, ...],
        tuple[LiveCaseObservation, ...],
        tuple[LiveCaseObservation, ...],
    ],
) -> None:
    off_security, on_security, off_live, on_live = parsed_rows
    off_security_summary = _mode_result("off", off_security).summary
    on_security_summary = _mode_result("on", on_security).summary
    gate = _build_behavior_gate(
        manifest.split,
        off_security_summary,
        on_security_summary,
    )
    pair_input_consistent = all(
        off.input_fingerprint == on.input_fingerprint
        and off.nonce_fingerprint == on.nonce_fingerprint
        and off.candidate_order == on.candidate_order
        and off_observation.pair_input_fingerprint
        == on_observation.pair_input_fingerprint
        for off, on, off_observation, on_observation in zip(
            off_security,
            on_security,
            off_live,
            on_live,
        )
    )
    protocol_complete = bool(
        pair_input_consistent
        and all(item.retrieval_completed for item in off_live)
        and all(item.retrieval_completed for item in on_live)
        and all(not item.model_error_codes for item in off_live)
        and all(not item.model_error_codes for item in on_live)
    )
    status: LiveRunStatus = (
        "COMPLETED WITH OBSERVATIONS" if protocol_complete else "FAILED"
    )
    if (
        manifest.status != status
        or manifest.observation.protocol_complete != protocol_complete
        or manifest.observation.pair_input_consistent != pair_input_consistent
        or manifest.observation.deterministic_threshold_diagnostic_passed
        != gate.passed
    ):
        raise ValueError("v2 manifest observation contradicts per-case evidence")

    expected = {
        "schema_version": "indirect_injection_live_paired_result_v2",
        "producer": manifest.producer,
        "run_id": manifest.run_id,
        "split": manifest.split,
        "mode": manifest.mode,
        "status": status,
        "protocol_complete": protocol_complete,
        "pair_input_consistent": pair_input_consistent,
        "embedding": {
            "request_count": manifest.retrieval.embedding_request_count,
            "delegate_call_count": (
                manifest.retrieval.embedding_delegate_call_count
            ),
            "cache_hit_count": manifest.retrieval.embedding_cache_hit_count,
        },
        "guard_off_security": off_security_summary.model_dump(mode="json"),
        "guard_on_security": on_security_summary.model_dump(mode="json"),
        "guard_off_live": _summarize_live_mode(
            "off",
            off_live,
            off_security,
        ).model_dump(mode="json"),
        "guard_on_live": _summarize_live_mode(
            "on",
            on_live,
            on_security,
        ).model_dump(mode="json"),
        "deterministic_threshold_diagnostic": gate.model_dump(mode="json"),
        "arm_order": {
            "schema_version": manifest.arm_order.schema_version,
            "protocol_id": manifest.arm_order.protocol_id,
            "hash_algorithm": manifest.arm_order.hash_algorithm,
            "allocation_method": manifest.arm_order.allocation_method,
            "case_count": manifest.arm_order.case_count,
            "off_then_on_count": manifest.arm_order.off_then_on_count,
            "on_then_off_count": manifest.arm_order.on_then_off_count,
        },
    }
    if summary != expected:
        raise ValueError("v2 summary contradicts per-case evidence")


def _validate_stage(stage: Path, manifest: LiveSecurityRunManifest) -> None:
    expected = {*_ARTIFACT_NAMES, "manifest.json"}
    if {path.name for path in stage.iterdir()} != expected:
        raise ValueError("live security run has an unexpected artifact set")
    summary_bytes = (stage / "summary.json").read_bytes()
    summary = json.loads(summary_bytes.decode("utf-8"))
    if summary_bytes != _json_bytes(summary):
        raise ValueError("live summary is not canonical JSON")
    if isinstance(manifest, LiveSecurityRunManifestV2):
        parsed_rows = _validate_v2_per_case_rows(
            stage / "per_case.jsonl",
            manifest,
        )
        _validate_v2_summary(summary, manifest, parsed_rows)
    else:
        for line in (
            (stage / "per_case.jsonl").read_text(encoding="utf-8").splitlines()
        ):
            json.loads(line)
    for name, evidence in manifest.artifacts.items():
        artifact = stage / name
        if (
            artifact.stat().st_size != evidence.bytes
            or _sha256(artifact) != evidence.sha256
        ):
            raise ValueError(f"live artifact evidence mismatch: {name}")
    checksum_rows = (stage / "checksums.sha256").read_text(
        encoding="utf-8"
    ).splitlines()
    expected_rows = [
        f"{_sha256(stage / name)}  {name}" for name in _CHECKSUM_CONTENT_NAMES
    ]
    if checksum_rows != expected_rows:
        raise ValueError("live checksum file does not match artifacts")
    parsed = type(manifest).model_validate_json(
        (stage / "manifest.json").read_bytes()
    )
    if parsed != manifest:
        raise ValueError("live manifest did not round-trip")


def verify_live_security_run(run_dir: Path) -> LiveSecurityRunManifest:
    run_dir = Path(run_dir).resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(f"live security run directory not found: {run_dir}")
    manifest_path = run_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("live security manifest must be a JSON object")
    schema_version = payload.get("schema_version")
    manifest_type = {
        "indirect_injection_live_security_run_manifest_v1": (
            LiveSecurityRunManifest
        ),
        "indirect_injection_live_security_run_manifest_v2": (
            LiveSecurityRunManifestV2
        ),
    }.get(schema_version)
    if manifest_type is None:
        raise ValueError("unsupported live security manifest schema version")
    manifest = manifest_type.model_validate_json(manifest_path.read_bytes())
    if run_dir.name != manifest.run_id:
        raise ValueError("live security run directory name contradicts manifest")
    _validate_stage(run_dir, manifest)
    return manifest


def _optional_positive_int(value: object) -> int | None:
    if value is None:
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def _ensure_newline(value: str) -> str:
    return value.rstrip("\r\n") + "\n"


def _json_bytes(value: Any, *, compact: bool = False) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=None if compact else 2,
            separators=(",", ":") if compact else None,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "LiveIndexReference",
    "LiveSecurityRunManifest",
    "LiveSecurityRunManifestV2",
    "OllamaModelIdentity",
    "publish_live_security_run",
    "resolve_ollama_model_identity",
    "verify_live_security_run",
]
