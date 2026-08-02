from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa_descriptor_retriever_v1 import (
    DeterministicDescriptorRetrieverResultV1,
)
from app.external_datasets.finqa_descriptor_retriever_v5 import (
    DeterministicFinQADescriptorRetrieverV5,
)
from app.external_datasets.finqa_descriptor_shadow_protocol_v1 import (
    FinQADescriptorShadowProtocolV1,
    load_descriptor_shadow_protocol_v1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeDescriptorCatalogV3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)
from app.external_datasets.finqa_topk_ranker_protocol_v1 import (
    load_topk_ranker_protocol_v1,
)
from app.external_datasets.finqa_topk_ranker_v1 import (
    TopKBoundaryFinQADescriptorRetrieverV1,
    load_topk_ranker_artifact_v1,
)


SHADOW_OBSERVATION_VERSION = "finqa_descriptor_shadow_observation_v1"
SHADOW_METRICS_VERSION = "finqa_descriptor_shadow_metrics_v1"
ShadowModeV1 = Literal["OFF", "OBSERVE"]
ShadowOutcomeV1 = Literal[
    "DISABLED",
    "MATCH",
    "DIVERGED",
    "CHALLENGER_ERROR",
    "CHALLENGER_TIMEOUT",
    "INPUT_MISMATCH",
    "CIRCUIT_OPEN",
]
ShadowCircuitStateV1 = Literal["CLOSED", "OPEN", "HALF_OPEN"]
ShadowLatencyBucketV1 = Literal[
    "LT_1_MS",
    "1_TO_LT_5_MS",
    "5_TO_LT_20_MS",
    "20_TO_LT_100_MS",
    "GE_100_MS",
    "NOT_RUN",
]
ShadowLoadStatusV1 = Literal[
    "READY",
    "DISABLED_BY_CONFIG",
    "DISABLED_EVIDENCE_INVALID",
]

_EVIDENCE_FILES = {
    "source_e8_protocol_sha256": "finqa_retrievable_descriptor_protocol_v1.json",
    "source_e11_protocol_sha256": "finqa_topk_ranker_protocol_v1.json",
    "source_e11_cv_sha256": "finqa_topk_nested_cv_public_v1.json",
    "source_e11_artifact_file_sha256": "finqa_topk_ranker_artifact_v1.json",
    "source_e11_internal_sha256": "finqa_topk_internal_validation_public_v1.json",
    "source_e11_postmortem_sha256": (
        "finqa_topk_internal_postmortem_public_v1.json"
    ),
}


class _DescriptorRetriever(Protocol):
    def select(
        self,
        *,
        question: str,
        skeleton: SemanticProgramSkeletonV2,
        catalog: RetrievableSafeDescriptorCatalogV3,
    ) -> DeterministicDescriptorRetrieverResultV1: ...


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class FinQAShadowConfigV1(_StrictFrozenModel):
    mode: ShadowModeV1 = "OFF"
    observation_timeout_ms: float = Field(default=100.0, gt=0, le=5_000)
    consecutive_failure_threshold: int = Field(default=3, ge=1, le=20)
    cooldown_observation_count: int = Field(default=5, ge=1, le=10_000)

    @classmethod
    def from_protocol(
        cls,
        protocol: FinQADescriptorShadowProtocolV1,
        *,
        mode: ShadowModeV1,
    ) -> FinQAShadowConfigV1:
        return cls(
            mode=mode,
            observation_timeout_ms=protocol.runtime.observation_timeout_ms,
            consecutive_failure_threshold=(
                protocol.circuit_breaker.consecutive_failure_threshold
            ),
            cooldown_observation_count=(
                protocol.circuit_breaker.cooldown_observation_count
            ),
        )


class FinQAShadowObservationV1(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_descriptor_shadow_observation_v1"
    ] = SHADOW_OBSERVATION_VERSION
    outcome: ShadowOutcomeV1
    role_count: int = Field(ge=0, le=8)
    changed_role_count: int = Field(ge=0, le=8)
    common_descriptor_count_at_4: int = Field(ge=0, le=32)
    latency_bucket: ShadowLatencyBucketV1
    circuit_state: ShadowCircuitStateV1

    @model_validator(mode="after")
    def validate_counts(self) -> FinQAShadowObservationV1:
        if (
            self.changed_role_count > self.role_count
            or self.common_descriptor_count_at_4 > self.role_count * 4
        ):
            raise ValueError("E12 observation counts are inconsistent")
        if (self.outcome in {"DISABLED", "CIRCUIT_OPEN", "INPUT_MISMATCH"}) != (
            self.latency_bucket == "NOT_RUN"
        ):
            raise ValueError("E12 observation latency state is inconsistent")
        return self


class FinQAShadowMetricsSnapshotV1(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_descriptor_shadow_metrics_v1"
    ] = SHADOW_METRICS_VERSION
    observation_count: int = Field(ge=0)
    role_count: int = Field(ge=0)
    changed_role_count: int = Field(ge=0)
    common_descriptor_count_at_4: int = Field(ge=0)
    outcomes: dict[str, int]
    latency_buckets: dict[str, int]
    circuit_states: dict[str, int]

    @model_validator(mode="after")
    def validate_aggregate_keys(self) -> FinQAShadowMetricsSnapshotV1:
        allowed_outcomes = {
            "DISABLED",
            "MATCH",
            "DIVERGED",
            "CHALLENGER_ERROR",
            "CHALLENGER_TIMEOUT",
            "INPUT_MISMATCH",
            "CIRCUIT_OPEN",
        }
        allowed_latency = {
            "LT_1_MS",
            "1_TO_LT_5_MS",
            "5_TO_LT_20_MS",
            "20_TO_LT_100_MS",
            "GE_100_MS",
            "NOT_RUN",
        }
        if (
            not set(self.outcomes).issubset(allowed_outcomes)
            or not set(self.latency_buckets).issubset(allowed_latency)
            or not set(self.circuit_states).issubset(
                {"CLOSED", "OPEN", "HALF_OPEN"}
            )
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for counts in (
                    self.outcomes,
                    self.latency_buckets,
                    self.circuit_states,
                )
                for value in counts.values()
            )
        ):
            raise ValueError("E12 aggregate metric boundary changed")
        return self


class FinQAShadowMetricsRegistryV1:
    def __init__(self) -> None:
        self._lock = Lock()
        self._observation_count = 0
        self._role_count = 0
        self._changed_role_count = 0
        self._common_descriptor_count = 0
        self._outcomes: Counter[str] = Counter()
        self._latency_buckets: Counter[str] = Counter()
        self._circuit_states: Counter[str] = Counter()

    def record(self, observation: FinQAShadowObservationV1) -> None:
        with self._lock:
            self._observation_count += 1
            self._role_count += observation.role_count
            self._changed_role_count += observation.changed_role_count
            self._common_descriptor_count += (
                observation.common_descriptor_count_at_4
            )
            self._outcomes[observation.outcome] += 1
            self._latency_buckets[observation.latency_bucket] += 1
            self._circuit_states[observation.circuit_state] += 1

    def snapshot(self) -> FinQAShadowMetricsSnapshotV1:
        with self._lock:
            return FinQAShadowMetricsSnapshotV1(
                observation_count=self._observation_count,
                role_count=self._role_count,
                changed_role_count=self._changed_role_count,
                common_descriptor_count_at_4=self._common_descriptor_count,
                outcomes=dict(sorted(self._outcomes.items())),
                latency_buckets=dict(sorted(self._latency_buckets.items())),
                circuit_states=dict(sorted(self._circuit_states.items())),
            )


@dataclass(frozen=True)
class FinQAPrimaryDescriptorDecisionV1:
    result: DeterministicDescriptorRetrieverResultV1
    input_binding_sha256: str = field(repr=False)


@dataclass(frozen=True)
class FinQAShadowChallengerLoadV1:
    status: ShadowLoadStatusV1
    challenger: _DescriptorRetriever | None = field(default=None, repr=False)


class _CircuitBreakerV1:
    def __init__(self, *, failure_threshold: int, cooldown_count: int) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_count = cooldown_count
        self._lock = Lock()
        self._state: ShadowCircuitStateV1 = "CLOSED"
        self._consecutive_failures = 0
        self._cooldown_remaining = 0

    def admit(self) -> tuple[bool, ShadowCircuitStateV1]:
        with self._lock:
            if self._state == "OPEN":
                if self._cooldown_remaining > 0:
                    self._cooldown_remaining -= 1
                    return False, "OPEN"
                self._state = "HALF_OPEN"
                return True, "HALF_OPEN"
            if self._state == "HALF_OPEN":
                return False, "OPEN"
            return True, "CLOSED"

    def success(self) -> ShadowCircuitStateV1:
        with self._lock:
            self._state = "CLOSED"
            self._consecutive_failures = 0
            self._cooldown_remaining = 0
            return self._state

    def failure(self) -> ShadowCircuitStateV1:
        with self._lock:
            self._consecutive_failures += 1
            if (
                self._state == "HALF_OPEN"
                or self._consecutive_failures >= self._failure_threshold
            ):
                self._state = "OPEN"
                self._cooldown_remaining = self._cooldown_count
            else:
                self._state = "CLOSED"
            return self._state

    def state(self) -> ShadowCircuitStateV1:
        with self._lock:
            return self._state


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("E12 evidence must be a JSON object")
    return payload


def _all_true(payload: object) -> bool:
    return (
        isinstance(payload, dict)
        and bool(payload)
        and all(value is True for value in payload.values())
    )


def load_verified_e11_shadow_challenger_v1(
    *,
    protocol: FinQADescriptorShadowProtocolV1,
    evidence_dir: Path,
) -> FinQAShadowChallengerLoadV1:
    try:
        root = evidence_dir.resolve(strict=True)
        paths = {name: root / filename for name, filename in _EVIDENCE_FILES.items()}
        if any(_sha256(paths[name]) != getattr(protocol, name) for name in paths):
            raise ValueError("E12 source evidence hash mismatch")

        e11_protocol, e11_protocol_sha256 = load_topk_ranker_protocol_v1(
            paths["source_e11_protocol_sha256"]
        )
        artifact = load_topk_ranker_artifact_v1(
            paths["source_e11_artifact_file_sha256"]
        )
        cv = _json_object(paths["source_e11_cv_sha256"])
        internal = _json_object(paths["source_e11_internal_sha256"])
        postmortem = _json_object(paths["source_e11_postmortem_sha256"])

        if not (
            e11_protocol_sha256 == protocol.source_e11_protocol_sha256
            == artifact.protocol_sha256
            and artifact.artifact_sha256 == protocol.source_e11_artifact_sha256
            and cv.get("decision")
            == "E11_OUTER_CV_AUTHORIZED_FOR_SINGLE_INTERNAL_VALIDATION"
            and cv.get("protocol_sha256") == e11_protocol_sha256
            and cv.get("artifact_sha256") == artifact.artifact_sha256
            and _all_true(cv.get("gate_checks"))
            and internal.get("decision")
            == "E11_INTERNAL_GATE_PASSED_ELIGIBLE_FOR_NEXT_STAGE"
            and internal.get("protocol_sha256") == e11_protocol_sha256
            and internal.get("artifact_file_sha256")
            == protocol.source_e11_artifact_file_sha256
            and internal.get("artifact_sha256") == artifact.artifact_sha256
            and internal.get("source_cv_evidence_sha256")
            == protocol.source_e11_cv_sha256
            and internal.get("serving_route_status") == "DISABLED"
            and internal.get("frozen_test_status") == "UNTOUCHED"
            and _all_true(internal.get("gate_checks"))
            and postmortem.get("source_internal_result_sha256")
            == protocol.source_e11_internal_sha256
            and postmortem.get("serving_route_status") == "DISABLED"
            and protocol.serving_route_status == "DISABLED"
            and protocol.frozen_test_status == "UNTOUCHED"
        ):
            raise ValueError("E12 authorization chain is incomplete")
        return FinQAShadowChallengerLoadV1(
            status="READY",
            challenger=TopKBoundaryFinQADescriptorRetrieverV1(artifact),
        )
    except Exception:
        return FinQAShadowChallengerLoadV1(
            status="DISABLED_EVIDENCE_INVALID",
        )


def _input_binding_sha256(
    *,
    question: str,
    skeleton: SemanticProgramSkeletonV2,
    catalog: RetrievableSafeDescriptorCatalogV3,
) -> str:
    payload = {
        "question": question,
        "skeleton": skeleton.model_dump(mode="json"),
        "catalog": catalog.model_dump(mode="json"),
    }
    content = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(content).hexdigest()


def _latency_bucket(duration_ms: float) -> ShadowLatencyBucketV1:
    if duration_ms < 1:
        return "LT_1_MS"
    if duration_ms < 5:
        return "1_TO_LT_5_MS"
    if duration_ms < 20:
        return "5_TO_LT_20_MS"
    if duration_ms < 100:
        return "20_TO_LT_100_MS"
    return "GE_100_MS"


class FinQADescriptorShadowRuntimeV1:
    def __init__(
        self,
        *,
        config: FinQAShadowConfigV1 | None = None,
        champion: _DescriptorRetriever | None = None,
        challenger: _DescriptorRetriever | None = None,
        challenger_load_status: ShadowLoadStatusV1 = "DISABLED_BY_CONFIG",
        metrics: FinQAShadowMetricsRegistryV1 | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.config = config or FinQAShadowConfigV1()
        self._champion = champion or DeterministicFinQADescriptorRetrieverV5()
        self._challenger = challenger
        self.challenger_load_status = challenger_load_status
        self.metrics = metrics or FinQAShadowMetricsRegistryV1()
        self._clock = clock
        self._circuit = _CircuitBreakerV1(
            failure_threshold=self.config.consecutive_failure_threshold,
            cooldown_count=self.config.cooldown_observation_count,
        )

    def select_primary(
        self,
        *,
        question: str,
        skeleton: SemanticProgramSkeletonV2,
        catalog: RetrievableSafeDescriptorCatalogV3,
    ) -> FinQAPrimaryDescriptorDecisionV1:
        result = self._champion.select(
            question=question,
            skeleton=skeleton,
            catalog=catalog,
        )
        return FinQAPrimaryDescriptorDecisionV1(
            result=result,
            input_binding_sha256=_input_binding_sha256(
                question=question,
                skeleton=skeleton,
                catalog=catalog,
            ),
        )

    def _record(
        self,
        *,
        outcome: ShadowOutcomeV1,
        role_count: int,
        changed_role_count: int = 0,
        common_descriptor_count_at_4: int = 0,
        latency_bucket: ShadowLatencyBucketV1 = "NOT_RUN",
        circuit_state: ShadowCircuitStateV1 | None = None,
    ) -> FinQAShadowObservationV1:
        observation = FinQAShadowObservationV1(
            outcome=outcome,
            role_count=role_count,
            changed_role_count=changed_role_count,
            common_descriptor_count_at_4=common_descriptor_count_at_4,
            latency_bucket=latency_bucket,
            circuit_state=circuit_state or self._circuit.state(),
        )
        self.metrics.record(observation)
        return observation

    def observe(
        self,
        *,
        primary: FinQAPrimaryDescriptorDecisionV1,
        question: str,
        skeleton: SemanticProgramSkeletonV2,
        catalog: RetrievableSafeDescriptorCatalogV3,
    ) -> FinQAShadowObservationV1:
        role_count = len(primary.result.selections.selections)
        if self.config.mode == "OFF":
            return self._record(outcome="DISABLED", role_count=role_count)

        binding = _input_binding_sha256(
            question=question,
            skeleton=skeleton,
            catalog=catalog,
        )
        if binding != primary.input_binding_sha256:
            return self._record(
                outcome="INPUT_MISMATCH",
                role_count=role_count,
                circuit_state=self._circuit.failure(),
            )

        admitted, state = self._circuit.admit()
        if not admitted:
            return self._record(
                outcome="CIRCUIT_OPEN",
                role_count=role_count,
                circuit_state=state,
            )
        if self._challenger is None:
            return self._record(
                outcome="CHALLENGER_ERROR",
                role_count=role_count,
                latency_bucket="LT_1_MS",
                circuit_state=self._circuit.failure(),
            )

        started = self._clock()
        try:
            challenger = self._challenger.select(
                question=question,
                skeleton=skeleton,
                catalog=catalog,
            )
            duration_ms = max(0.0, (self._clock() - started) * 1_000)
            bucket = _latency_bucket(duration_ms)
            if duration_ms > self.config.observation_timeout_ms:
                return self._record(
                    outcome="CHALLENGER_TIMEOUT",
                    role_count=role_count,
                    latency_bucket=bucket,
                    circuit_state=self._circuit.failure(),
                )
            if challenger.generation_calls != 0:
                raise ValueError("E12 challenger made a model call")
            champion_roles = primary.result.selections.selections
            challenger_roles = challenger.selections.selections
            if tuple(item.role_id for item in challenger_roles) != tuple(
                item.role_id for item in champion_roles
            ):
                raise ValueError("E12 challenger role contract changed")
            changed = 0
            common = 0
            for champion_role, challenger_role in zip(
                champion_roles,
                challenger_roles,
                strict=True,
            ):
                if champion_role.descriptor_ids != challenger_role.descriptor_ids:
                    changed += 1
                common += len(
                    set(champion_role.descriptor_ids)
                    & set(challenger_role.descriptor_ids)
                )
            outcome: ShadowOutcomeV1 = "DIVERGED" if changed else "MATCH"
            return self._record(
                outcome=outcome,
                role_count=role_count,
                changed_role_count=changed,
                common_descriptor_count_at_4=common,
                latency_bucket=bucket,
                circuit_state=self._circuit.success(),
            )
        except Exception:
            duration_ms = max(0.0, (self._clock() - started) * 1_000)
            return self._record(
                outcome="CHALLENGER_ERROR",
                role_count=role_count,
                latency_bucket=_latency_bucket(duration_ms),
                circuit_state=self._circuit.failure(),
            )


def build_verified_finqa_shadow_runtime_v1(
    *,
    protocol_path: Path,
    evidence_dir: Path,
    mode: ShadowModeV1 = "OFF",
    champion: _DescriptorRetriever | None = None,
    metrics: FinQAShadowMetricsRegistryV1 | None = None,
) -> FinQADescriptorShadowRuntimeV1:
    try:
        protocol, _ = load_descriptor_shadow_protocol_v1(protocol_path)
    except Exception:
        return FinQADescriptorShadowRuntimeV1(
            config=FinQAShadowConfigV1(mode="OFF"),
            champion=champion,
            challenger_load_status="DISABLED_EVIDENCE_INVALID",
            metrics=metrics,
        )
    config = FinQAShadowConfigV1.from_protocol(protocol, mode=mode)
    if mode == "OFF":
        return FinQADescriptorShadowRuntimeV1(
            config=config,
            champion=champion,
            challenger_load_status="DISABLED_BY_CONFIG",
            metrics=metrics,
        )
    loaded = load_verified_e11_shadow_challenger_v1(
        protocol=protocol,
        evidence_dir=evidence_dir,
    )
    return FinQADescriptorShadowRuntimeV1(
        config=config,
        champion=champion,
        challenger=loaded.challenger,
        challenger_load_status=loaded.status,
        metrics=metrics,
    )


__all__ = [
    "FinQADescriptorShadowRuntimeV1",
    "FinQAPrimaryDescriptorDecisionV1",
    "FinQAShadowConfigV1",
    "FinQAShadowMetricsRegistryV1",
    "FinQAShadowMetricsSnapshotV1",
    "FinQAShadowObservationV1",
    "build_verified_finqa_shadow_runtime_v1",
    "load_verified_e11_shadow_challenger_v1",
]
