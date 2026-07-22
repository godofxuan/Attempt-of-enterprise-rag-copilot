from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
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
from app.evaluation.publication_paths import (
    _atomic_publish_no_replace,
    _validated_absent_publication_target,
    _validated_publication_root,
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
_REPARSE_POINT_ATTRIBUTE = getattr(
    stat,
    "FILE_ATTRIBUTE_REPARSE_POINT",
    0x400,
)
_FileIdentity = tuple[int, int, int, int, int, int]
_DirectoryIdentity = tuple[int, int, int, int]


@dataclass(frozen=True)
class VerifiedLiveSecurityRunSnapshot:
    run_dir: Path
    manifest: LiveSecurityRunManifest
    manifest_bytes: bytes
    manifest_sha256: str
    _artifacts: Mapping[str, bytes] = field(default_factory=dict)
    _artifact_identities: Mapping[str, _FileIdentity] = field(default_factory=dict)
    _directory_identities: tuple[tuple[Path, _DirectoryIdentity], ...] = ()
    _manifest_identity: _FileIdentity | None = None

    def artifact_bytes(self, name: str) -> bytes:
        try:
            return self._artifacts[name]
        except KeyError as exc:
            raise KeyError(f"unknown live security artifact: {name}") from exc

    def assert_unchanged(self) -> None:
        expected_names = {*_ARTIFACT_NAMES, "manifest.json"}
        try:
            for path, expected in self._directory_identities:
                observed = path.lstat()
                if (
                    _is_redirecting_path(observed)
                    or not stat.S_ISDIR(observed.st_mode)
                    or _directory_identity(observed) != expected
                ):
                    raise ValueError(
                        "live security directory identity changed during verification"
                    )
            if not self._artifact_identities and self._manifest_identity is not None:
                observed = (self.run_dir / "manifest.json").lstat()
                if (
                    _is_redirecting_path(observed)
                    or not stat.S_ISREG(observed.st_mode)
                    or _file_identity(observed) != self._manifest_identity
                ):
                    raise ValueError(
                        "live security manifest changed during verification"
                    )
                return
            if {item.name for item in self.run_dir.iterdir()} != expected_names:
                raise ValueError(
                    "live security artifact set changed during verification"
                )
            for name, expected in self._artifact_identities.items():
                observed = (self.run_dir / name).lstat()
                if (
                    _is_redirecting_path(observed)
                    or not stat.S_ISREG(observed.st_mode)
                    or _file_identity(observed) != expected
                ):
                    raise ValueError(
                        f"live security artifact changed during verification: {name}"
                    )
        except ValueError:
            raise
        except OSError as exc:
            raise ValueError(
                "live security package changed during verification"
            ) from exc

    def assert_manifest_unchanged(self) -> None:
        self.assert_unchanged()


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


class CrossModelExperimentBinding(_StrictFrozenModel):
    plan_id: Literal["r2-s4-cross-model-dev-v1"]
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_role: Literal["baseline", "replication"]
    only_changed_variable: Literal["chat_model_identity"]


class LiveTransportProvenance(_StrictFrozenModel):
    model_request_timeout_seconds: float = Field(gt=0.0, le=300.0)
    model_max_attempts: int = Field(ge=1, le=3)
    model_retry_backoff_ms: int = Field(ge=0, le=10_000)


class LiveSecurityRunManifestV3(LiveSecurityRunManifestV2):
    schema_version: Literal[
        "indirect_injection_live_security_run_manifest_v3"
    ]
    mode: Literal["local_live_paired_counterbalanced_cross_model_dev"]
    split: Literal["dev"]
    experiment: CrossModelExperimentBinding
    transport: LiveTransportProvenance


def validate_v3_cross_model_plan_binding(
    experiment: CrossModelExperimentBinding,
    *,
    requested_chat_model: str | None = None,
    expected_chat_digest: str | None = None,
    embedding: OllamaModelIdentity | None = None,
    chat: OllamaModelIdentity | None = None,
) -> None:
    from app.evaluation.indirect_injection_cross_model import (
        load_cross_model_plan,
    )

    plan_path = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "v2"
        / "evaluation"
        / "r2_s4_cross_model_matrix_v1.json"
    )
    plan, plan_sha256 = load_cross_model_plan(plan_path)
    if (
        experiment.plan_id != plan.experiment_id
        or experiment.plan_sha256 != plan_sha256
        or experiment.only_changed_variable != plan.only_changed_variable
    ):
        raise ValueError("V3 binding contradicts the checked-in cross-model plan")
    planned_chat = plan.model_for_role(experiment.model_role)
    if (
        requested_chat_model is not None
        and requested_chat_model != planned_chat.requested_name
    ):
        raise ValueError(
            "V3 chat request contradicts the checked-in cross-model plan"
        )
    if (
        expected_chat_digest is not None
        and expected_chat_digest != planned_chat.digest
    ):
        raise ValueError(
            "V3 chat digest contradicts the checked-in cross-model plan"
        )
    if (embedding is None) != (chat is None):
        raise ValueError("V3 model identities must be validated together")
    if embedding is None or chat is None:
        return
    observed_chat = (
        chat.requested_name,
        chat.resolved_name,
        chat.digest,
        chat.family,
        chat.parameter_size,
    )
    expected_chat = (
        planned_chat.requested_name,
        planned_chat.resolved_name,
        planned_chat.digest,
        planned_chat.family,
        planned_chat.parameter_size,
    )
    observed_embedding = (
        embedding.requested_name,
        embedding.resolved_name,
        embedding.digest,
    )
    expected_embedding = (
        plan.embedding.requested_name,
        plan.embedding.resolved_name,
        plan.embedding.digest,
    )
    if observed_chat != expected_chat or observed_embedding != expected_embedding:
        raise ValueError(
            "V3 model identities contradict the checked-in cross-model plan"
        )


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
    output_root = _validated_publication_root(Path(root), "output root")
    target = _validated_absent_publication_target(
        output_root,
        manifest.run_id,
        "live security output run",
        "run ID resolves outside output root",
    )

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
        _atomic_publish_no_replace(stage, target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def _validate_consistency(
    manifest: LiveSecurityRunManifest,
    result: LivePairedResult,
) -> None:
    manifest_schema = manifest.schema_version
    manifest_is_v2_or_v3 = manifest_schema in {
        "indirect_injection_live_security_run_manifest_v2",
        "indirect_injection_live_security_run_manifest_v3",
    }
    result_is_v2 = isinstance(result, LivePairedResultV2)
    if manifest_is_v2_or_v3 != result_is_v2:
        raise ValueError("live manifest/result schema versions differ")
    if (
        manifest_is_v2_or_v3
        and result_is_v2
        and manifest.arm_order != result.arm_order
    ):
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
    raw: bytes | Path,
    manifest: LiveSecurityRunManifestV2,
) -> tuple[
    tuple[SecurityCaseResult, ...],
    tuple[SecurityCaseResult, ...],
    tuple[LiveCaseObservation, ...],
    tuple[LiveCaseObservation, ...],
]:
    try:
        payload = raw.read_bytes() if isinstance(raw, Path) else raw
        lines = _canonical_jsonl_rows(payload, "v2 per-case")
    except UnicodeDecodeError as exc:
        raise ValueError("v2 per-case evidence must be UTF-8") from exc
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
            row_payload = line
            if not isinstance(row_payload, dict) or set(row_payload) != {
                "arm_execution",
                "security",
                "live",
            }:
                raise ValueError("v2 per-case row has unexpected keys")
            arm_execution = row_payload["arm_execution"]
            security = row_payload["security"]
            live = row_payload["live"]
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


def _canonical_jsonl_rows(raw: bytes, label: str) -> list[dict[str, Any]]:
    if not raw.endswith(b"\n"):
        raise ValueError(f"{label} JSONL is not canonical LF-terminated JSONL")
    decoded = raw.decode("utf-8")
    parsed: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(raw.splitlines(keepends=True), start=1):
        if not raw_line.endswith(b"\n") or raw_line.endswith(b"\r\n"):
            raise ValueError(f"{label} JSONL is not canonical LF-terminated JSONL")
        line = raw_line[:-1]
        if not line:
            raise ValueError(f"{label} JSONL contains an empty row")
        try:
            payload = _loads_json_no_duplicate_keys(
                line.decode("utf-8"),
                f"{label} row {line_number}",
            )
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} row {line_number} is invalid JSON") from exc
        if line + b"\n" != _json_bytes(payload, compact=True):
            raise ValueError(f"{label} row {line_number} is not canonical JSON")
        if not isinstance(payload, dict):
            raise ValueError(f"{label} row {line_number} must be a JSON object")
        parsed.append(payload)
    if decoded != "".join(
        _json_bytes(row, compact=True).decode("utf-8") for row in parsed
    ):
        raise ValueError(f"{label} JSONL is not canonical LF-terminated JSONL")
    return parsed


def _loads_json_no_duplicate_keys(value: str, label: str) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"{label} contains duplicate JSON key")
            result[key] = item
        return result

    return json.loads(value, object_pairs_hook=reject_duplicate_keys)


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
        and all(item.answer_mode != "system" for item in off_security)
        and all(item.answer_mode != "system" for item in on_security)
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


def _validate_stage(
    stage: Path,
    manifest: LiveSecurityRunManifest,
    *,
    manifest_bytes: bytes | None = None,
    artifact_bytes: Mapping[str, bytes] | None = None,
) -> None:
    expected = {*_ARTIFACT_NAMES, "manifest.json"}
    if artifact_bytes is None:
        if {path.name for path in stage.iterdir()} != expected:
            raise ValueError("live security run has an unexpected artifact set")
        captured: dict[str, bytes] = {}
        for name in sorted(expected):
            path = _validated_fixed_regular_path(
                stage,
                Path(name),
                f"live security artifact {name}",
            )
            captured[name] = path.read_bytes()
        files: Mapping[str, bytes] = captured
    else:
        if set(artifact_bytes) != expected:
            raise ValueError("live security run has an unexpected artifact set")
        files = artifact_bytes
    if manifest_bytes is not None and files["manifest.json"] != manifest_bytes:
        raise ValueError("captured live manifest bytes differ")

    summary_bytes = files["summary.json"]
    summary = json.loads(summary_bytes.decode("utf-8"))
    if summary_bytes != _json_bytes(summary):
        raise ValueError("live summary is not canonical JSON")
    if isinstance(manifest, LiveSecurityRunManifestV3):
        validate_v3_cross_model_plan_binding(
            manifest.experiment,
            embedding=manifest.models.embedding,
            chat=manifest.models.chat,
        )
        parsed_rows = _validate_v2_per_case_rows(
            files["per_case.jsonl"],
            manifest,
        )
        _validate_v2_summary(summary, manifest, parsed_rows)
    elif isinstance(manifest, LiveSecurityRunManifestV2):
        parsed_rows = _validate_v2_per_case_rows(
            files["per_case.jsonl"],
            manifest,
        )
        _validate_v2_summary(summary, manifest, parsed_rows)
    else:
        for line in files["per_case.jsonl"].decode("utf-8").splitlines():
            json.loads(line)
    for name, evidence in manifest.artifacts.items():
        if (
            len(files[name]) != evidence.bytes
            or hashlib.sha256(files[name]).hexdigest() != evidence.sha256
        ):
            raise ValueError(f"live artifact evidence mismatch: {name}")
    checksum_rows = files["checksums.sha256"].decode("utf-8").splitlines()
    expected_rows = [
        f"{hashlib.sha256(files[name]).hexdigest()}  {name}"
        for name in _CHECKSUM_CONTENT_NAMES
    ]
    if checksum_rows != expected_rows:
        raise ValueError("live checksum file does not match artifacts")
    parsed = type(manifest).model_validate_json(
        manifest_bytes
        if manifest_bytes is not None
        else files["manifest.json"]
    )
    if parsed != manifest:
        raise ValueError("live manifest did not round-trip")


def load_verified_live_security_run_snapshot(
    run_dir: Path,
) -> VerifiedLiveSecurityRunSnapshot:
    run_dir, directory_identities = _validated_trusted_directory(
        Path(run_dir),
        "live security run directory",
    )
    expected = {*_ARTIFACT_NAMES, "manifest.json"}
    try:
        names = {path.name for path in run_dir.iterdir()}
    except OSError as exc:
        raise ValueError("live security run cannot be listed") from exc
    if names != expected:
        raise ValueError("live security run has an unexpected artifact set")
    artifacts: dict[str, bytes] = {}
    identities: dict[str, _FileIdentity] = {}
    for name in sorted(expected):
        payload, identity = _read_regular_file_snapshot(
            run_dir / name,
            f"live security artifact {name}",
        )
        artifacts[name] = payload
        identities[name] = identity
    manifest_bytes = artifacts["manifest.json"]
    payload = json.loads(manifest_bytes)
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
        "indirect_injection_live_security_run_manifest_v3": (
            LiveSecurityRunManifestV3
        ),
    }.get(schema_version)
    if manifest_type is None:
        raise ValueError("unsupported live security manifest schema version")
    manifest = manifest_type.model_validate_json(manifest_bytes)
    if run_dir.name != manifest.run_id:
        raise ValueError("live security run directory name contradicts manifest")
    _validate_stage(
        run_dir,
        manifest,
        manifest_bytes=manifest_bytes,
        artifact_bytes=artifacts,
    )
    snapshot = VerifiedLiveSecurityRunSnapshot(
        run_dir=run_dir,
        manifest=manifest,
        manifest_bytes=manifest_bytes,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        _artifacts=MappingProxyType(dict(artifacts)),
        _artifact_identities=MappingProxyType(dict(identities)),
        _directory_identities=directory_identities,
    )
    snapshot.assert_unchanged()
    return snapshot


def verify_live_security_run(run_dir: Path) -> LiveSecurityRunManifest:
    return load_verified_live_security_run_snapshot(run_dir).manifest


def _read_regular_file_snapshot(
    path: Path,
    label: str,
) -> tuple[bytes, _FileIdentity]:
    descriptor = -1
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        path_before = path.lstat()
        if _is_redirecting_path(path_before) or not stat.S_ISREG(path_before.st_mode):
            raise ValueError(f"{label} must be a regular non-symlink file")
        descriptor = os.open(path, flags)
        descriptor_before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(descriptor_before.st_mode)
            or _file_identity(descriptor_before) != _file_identity(path_before)
        ):
            raise ValueError(f"{label} identity changed before descriptor read")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        descriptor_after = os.fstat(descriptor)
        path_after = path.lstat()
    except ValueError:
        raise
    except OSError as exc:
        raise ValueError(f"{label} must be a regular non-symlink file") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    identity = _file_identity(path_before)
    payload = b"".join(chunks)
    if (
        _is_redirecting_path(path_after)
        or not stat.S_ISREG(path_after.st_mode)
        or _file_identity(descriptor_before) != identity
        or _file_identity(descriptor_after) != identity
        or _file_identity(path_after) != identity
        or len(payload) != path_before.st_size
    ):
        raise ValueError(f"{label} identity changed during descriptor read")
    return payload, identity


def _validated_trusted_directory(
    path: Path,
    label: str,
) -> tuple[Path, tuple[tuple[Path, _DirectoryIdentity], ...]]:
    lexical = Path(os.path.abspath(os.fspath(path)))
    chain = tuple(reversed((lexical, *lexical.parents)))
    identities: list[tuple[Path, _DirectoryIdentity]] = []
    try:
        for current in chain:
            observed = current.lstat()
            if _is_redirecting_path(observed):
                if current == lexical:
                    raise ValueError(
                        f"{label} cannot be a symlink or redirecting reparse point"
                    )
                raise ValueError(
                    f"{label} has a redirecting lexical path component"
                )
            if not stat.S_ISDIR(observed.st_mode):
                raise FileNotFoundError(f"{label} not found: {path}")
            identities.append((current, _directory_identity(observed)))
    except ValueError:
        raise
    except OSError as exc:
        raise FileNotFoundError(f"{label} not found: {path}") from exc
    return lexical, tuple(identities)


def _validated_fixed_regular_path(
    root: Path,
    relative: Path,
    label: str,
) -> Path:
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        observed = current.lstat()
        final = index == len(relative.parts) - 1
        if _is_redirecting_path(observed):
            raise ValueError(f"{label} has a redirecting path component")
        if final:
            if not stat.S_ISREG(observed.st_mode):
                raise ValueError(f"{label} must be a regular file")
        elif not stat.S_ISDIR(observed.st_mode):
            raise ValueError(f"{label} path component must be a directory")
    return current


def _is_redirecting_path(value) -> bool:
    return stat.S_ISLNK(value.st_mode) or bool(
        getattr(value, "st_file_attributes", 0)
        & _REPARSE_POINT_ATTRIBUTE
    )


def _file_identity(value) -> _FileIdentity:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _directory_identity(value) -> _DirectoryIdentity:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        getattr(value, "st_file_attributes", 0),
    )


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
    "CrossModelExperimentBinding",
    "LiveIndexReference",
    "LiveSecurityRunManifest",
    "LiveSecurityRunManifestV2",
    "LiveSecurityRunManifestV3",
    "LiveTransportProvenance",
    "OllamaModelIdentity",
    "VerifiedLiveSecurityRunSnapshot",
    "load_verified_live_security_run_snapshot",
    "publish_live_security_run",
    "resolve_ollama_model_identity",
    "validate_v3_cross_model_plan_binding",
    "verify_live_security_run",
]
