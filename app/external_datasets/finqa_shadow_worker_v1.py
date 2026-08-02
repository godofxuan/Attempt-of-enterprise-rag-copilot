from __future__ import annotations

import hashlib
import json
import multiprocessing
import time
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.connection import Connection
from pathlib import Path
from threading import Lock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa_descriptor_selector_v1 import (
    DescriptorSelectionsV1,
)
from app.external_datasets.finqa_descriptor_shadow_protocol_v1 import (
    load_descriptor_shadow_protocol_v1,
)
from app.external_datasets.finqa_descriptor_shadow_v1 import (
    FinQAPrimaryDescriptorDecisionV1,
    load_verified_e11_shadow_challenger_v1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeDescriptorCatalogV3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)
from app.external_datasets.finqa_shadow_worker_protocol_v1 import (
    FinQAShadowWorkerReplayProtocolV1,
)
from app.observability.metrics import process_peak_rss_bytes


WORKER_REQUEST_VERSION = "finqa_shadow_worker_request_v1"
WORKER_RESPONSE_VERSION = "finqa_shadow_worker_response_v1"
WORKER_OBSERVATION_VERSION = "finqa_isolated_shadow_observation_v1"
WorkerOutcomeV1 = Literal[
    "MATCH",
    "DIVERGED",
    "INPUT_MISMATCH",
    "PAYLOAD_REJECTED",
    "WORKER_ERROR",
    "WORKER_TIMEOUT",
    "WORKER_CRASH",
]
WorkerEntryV1 = Callable[[Connection, str, int, int], None]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class FinQAShadowWorkerConfigV1(_StrictFrozenModel):
    startup_timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    observation_timeout_seconds: float = Field(default=1.0, gt=0, le=30)
    termination_grace_seconds: float = Field(default=1.0, gt=0, le=10)
    max_request_bytes: int = Field(default=1024 * 1024, ge=64, le=16 * 1024 * 1024)
    max_response_bytes: int = Field(default=64 * 1024, ge=64, le=1024 * 1024)

    @classmethod
    def from_protocol(
        cls,
        protocol: FinQAShadowWorkerReplayProtocolV1,
    ) -> FinQAShadowWorkerConfigV1:
        return cls(
            startup_timeout_seconds=protocol.worker.startup_timeout_seconds,
            observation_timeout_seconds=(
                protocol.worker.observation_timeout_seconds
            ),
            termination_grace_seconds=protocol.worker.termination_grace_seconds,
            max_request_bytes=protocol.worker.max_request_bytes,
            max_response_bytes=protocol.worker.max_response_bytes,
        )


class FinQAShadowWorkerRequestV1(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_shadow_worker_request_v1"
    ] = WORKER_REQUEST_VERSION
    question: str = Field(min_length=1, max_length=2_000)
    skeleton: SemanticProgramSkeletonV2
    catalog: RetrievableSafeDescriptorCatalogV3
    primary_selections: DescriptorSelectionsV1


class FinQAShadowWorkerResponseV1(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_shadow_worker_response_v1"
    ] = WORKER_RESPONSE_VERSION
    outcome: Literal["MATCH", "DIVERGED"]
    role_count: int = Field(ge=1, le=8)
    changed_role_count: int = Field(ge=0, le=8)
    common_descriptor_count_at_4: int = Field(ge=0, le=32)
    generation_calls: Literal[0]
    worker_peak_rss_bytes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> FinQAShadowWorkerResponseV1:
        if (
            self.changed_role_count > self.role_count
            or self.common_descriptor_count_at_4 > self.role_count * 4
            or (self.outcome == "MATCH") != (self.changed_role_count == 0)
        ):
            raise ValueError("E13 worker response counts are inconsistent")
        return self


class FinQAIsolatedShadowObservationV1(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_isolated_shadow_observation_v1"
    ] = WORKER_OBSERVATION_VERSION
    outcome: WorkerOutcomeV1
    role_count: int = Field(ge=0, le=8)
    changed_role_count: int = Field(ge=0, le=8)
    common_descriptor_count_at_4: int = Field(ge=0, le=32)
    latency_ms: float = Field(ge=0)
    worker_peak_rss_bytes: int | None = Field(default=None, ge=0)
    worker_restarted: bool

    @model_validator(mode="after")
    def validate_counts(self) -> FinQAIsolatedShadowObservationV1:
        if (
            self.changed_role_count > self.role_count
            or self.common_descriptor_count_at_4 > self.role_count * 4
        ):
            raise ValueError("E13 isolated observation counts are inconsistent")
        return self


class _WorkerHandshakeV1(_StrictFrozenModel):
    status: Literal["READY", "EVIDENCE_INVALID"]


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _input_binding_sha256(
    *,
    question: str,
    skeleton: SemanticProgramSkeletonV2,
    catalog: RetrievableSafeDescriptorCatalogV3,
) -> str:
    return hashlib.sha256(
        _canonical_bytes(
            {
                "question": question,
                "skeleton": skeleton.model_dump(mode="json"),
                "catalog": catalog.model_dump(mode="json"),
            }
        )
    ).hexdigest()


def _response_bytes(response: FinQAShadowWorkerResponseV1) -> bytes:
    return _canonical_bytes(response.model_dump(mode="json"))


def _shadow_worker_main(
    connection: Connection,
    evidence_dir: str,
    max_request_bytes: int,
    max_response_bytes: int,
) -> None:
    try:
        evidence = Path(evidence_dir).resolve(strict=True)
        protocol, _ = load_descriptor_shadow_protocol_v1(
            evidence / "finqa_descriptor_shadow_protocol_v1.json"
        )
        loaded = load_verified_e11_shadow_challenger_v1(
            protocol=protocol,
            evidence_dir=evidence,
        )
        if loaded.challenger is None:
            connection.send_bytes(_canonical_bytes({"status": "EVIDENCE_INVALID"}))
            return
        connection.send_bytes(_canonical_bytes({"status": "READY"}))
        while True:
            try:
                content = connection.recv_bytes(maxlength=max_request_bytes)
            except (EOFError, OSError):
                return
            if content == b'{"kind":"STOP"}':
                return
            try:
                request = FinQAShadowWorkerRequestV1.model_validate_json(content)
                result = loaded.challenger.select(
                    question=request.question,
                    skeleton=request.skeleton,
                    catalog=request.catalog,
                )
                if result.generation_calls != 0:
                    raise ValueError("E13 worker challenger made a model call")
                primary_roles = request.primary_selections.selections
                challenger_roles = result.selections.selections
                if tuple(item.role_id for item in challenger_roles) != tuple(
                    item.role_id for item in primary_roles
                ):
                    raise ValueError("E13 worker role order changed")
                changed = 0
                common = 0
                for primary_role, challenger_role in zip(
                    primary_roles,
                    challenger_roles,
                    strict=True,
                ):
                    if primary_role.descriptor_ids != challenger_role.descriptor_ids:
                        changed += 1
                    common += len(
                        set(primary_role.descriptor_ids)
                        & set(challenger_role.descriptor_ids)
                    )
                response = FinQAShadowWorkerResponseV1(
                    outcome="DIVERGED" if changed else "MATCH",
                    role_count=len(primary_roles),
                    changed_role_count=changed,
                    common_descriptor_count_at_4=common,
                    generation_calls=0,
                    worker_peak_rss_bytes=process_peak_rss_bytes(),
                )
                serialized = _response_bytes(response)
                if len(serialized) > max_response_bytes:
                    raise ValueError("E13 worker response exceeds byte budget")
                connection.send_bytes(serialized)
            except Exception:
                connection.send_bytes(_canonical_bytes({"status": "ERROR"}))
    finally:
        connection.close()


@dataclass(frozen=True)
class FinQAShadowWorkerDiagnosticsV1:
    worker_pid: int | None
    last_terminated_pid: int | None
    last_terminated_exitcode: int | None
    restart_count: int


class FinQAIsolatedShadowWorkerV1:
    def __init__(
        self,
        *,
        evidence_dir: Path,
        config: FinQAShadowWorkerConfigV1 | None = None,
        worker_entry: WorkerEntryV1 = _shadow_worker_main,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.evidence_dir = evidence_dir.resolve()
        self.config = config or FinQAShadowWorkerConfigV1()
        self._worker_entry = worker_entry
        self._clock = clock
        self._context = multiprocessing.get_context("spawn")
        self._lock = Lock()
        self._process: multiprocessing.Process | None = None
        self._connection: Connection | None = None
        self._last_terminated_pid: int | None = None
        self._last_terminated_exitcode: int | None = None
        self._restart_count = 0

    def __enter__(self) -> FinQAIsolatedShadowWorkerV1:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def diagnostics(self) -> FinQAShadowWorkerDiagnosticsV1:
        with self._lock:
            return FinQAShadowWorkerDiagnosticsV1(
                worker_pid=(self._process.pid if self._process else None),
                last_terminated_pid=self._last_terminated_pid,
                last_terminated_exitcode=self._last_terminated_exitcode,
                restart_count=self._restart_count,
            )

    def _terminate_locked(self) -> None:
        process = self._process
        connection = self._connection
        self._process = None
        self._connection = None
        if connection is not None:
            connection.close()
        if process is None:
            return
        pid = process.pid
        if process.is_alive():
            process.terminate()
        process.join(timeout=self.config.termination_grace_seconds)
        if process.is_alive():
            process.kill()
            process.join(timeout=self.config.termination_grace_seconds)
        self._last_terminated_pid = pid
        self._last_terminated_exitcode = process.exitcode

    def _start_locked(self) -> bool:
        if self._process is not None and self._process.is_alive():
            return True
        self._terminate_locked()
        parent, child = self._context.Pipe(duplex=True)
        process = self._context.Process(
            target=self._worker_entry,
            args=(
                child,
                str(self.evidence_dir),
                self.config.max_request_bytes,
                self.config.max_response_bytes,
            ),
            daemon=True,
            name="finqa-e13-shadow-worker",
        )
        process.start()
        child.close()
        self._process = process
        self._connection = parent
        if not parent.poll(self.config.startup_timeout_seconds):
            self._terminate_locked()
            return False
        try:
            content = parent.recv_bytes(maxlength=self.config.max_response_bytes)
            handshake = _WorkerHandshakeV1.model_validate_json(content)
        except (EOFError, OSError, ValueError):
            self._terminate_locked()
            return False
        if handshake.status != "READY":
            self._terminate_locked()
            return False
        return True

    def _restart_locked(self) -> bool:
        self._terminate_locked()
        self._restart_count += 1
        return self._start_locked()

    def _worker_exited_locked(self) -> bool:
        if self._process is None:
            return True
        self._process.join(timeout=0.05)
        return self._process.exitcode is not None

    def start(self) -> bool:
        with self._lock:
            return self._start_locked()

    def close(self) -> None:
        with self._lock:
            if self._connection is not None and self._process is not None:
                if self._process.is_alive():
                    try:
                        self._connection.send_bytes(b'{"kind":"STOP"}')
                        self._process.join(
                            timeout=self.config.termination_grace_seconds
                        )
                    except (BrokenPipeError, EOFError, OSError):
                        pass
            self._terminate_locked()

    def _failure(
        self,
        *,
        outcome: WorkerOutcomeV1,
        role_count: int,
        started: float,
        restart: bool,
    ) -> FinQAIsolatedShadowObservationV1:
        restarted = self._restart_locked() if restart else False
        return FinQAIsolatedShadowObservationV1(
            outcome=outcome,
            role_count=role_count,
            changed_role_count=0,
            common_descriptor_count_at_4=0,
            latency_ms=max(0.0, (self._clock() - started) * 1_000),
            worker_restarted=restarted,
        )

    def observe(
        self,
        *,
        primary: FinQAPrimaryDescriptorDecisionV1,
        question: str,
        skeleton: SemanticProgramSkeletonV2,
        catalog: RetrievableSafeDescriptorCatalogV3,
    ) -> FinQAIsolatedShadowObservationV1:
        with self._lock:
            started = self._clock()
            role_count = len(primary.result.selections.selections)
            if _input_binding_sha256(
                question=question,
                skeleton=skeleton,
                catalog=catalog,
            ) != primary.input_binding_sha256:
                return self._failure(
                    outcome="INPUT_MISMATCH",
                    role_count=role_count,
                    started=started,
                    restart=False,
                )
            request = FinQAShadowWorkerRequestV1(
                question=question,
                skeleton=skeleton,
                catalog=catalog,
                primary_selections=primary.result.selections,
            )
            content = _canonical_bytes(request.model_dump(mode="json"))
            if len(content) > self.config.max_request_bytes:
                return self._failure(
                    outcome="PAYLOAD_REJECTED",
                    role_count=role_count,
                    started=started,
                    restart=False,
                )
            if not self._start_locked():
                return self._failure(
                    outcome="WORKER_ERROR",
                    role_count=role_count,
                    started=started,
                    restart=False,
                )
            assert self._connection is not None
            assert self._process is not None
            try:
                self._connection.send_bytes(content)
            except (BrokenPipeError, EOFError, OSError):
                return self._failure(
                    outcome="WORKER_CRASH",
                    role_count=role_count,
                    started=started,
                    restart=True,
                )
            if not self._connection.poll(self.config.observation_timeout_seconds):
                outcome: WorkerOutcomeV1 = (
                    "WORKER_CRASH"
                    if self._worker_exited_locked()
                    else "WORKER_TIMEOUT"
                )
                return self._failure(
                    outcome=outcome,
                    role_count=role_count,
                    started=started,
                    restart=True,
                )
            try:
                response_bytes = self._connection.recv_bytes(
                    maxlength=self.config.max_response_bytes
                )
                response = FinQAShadowWorkerResponseV1.model_validate_json(
                    response_bytes
                )
            except (EOFError, OSError, ValueError):
                outcome = (
                    "WORKER_CRASH"
                    if self._worker_exited_locked()
                    else "WORKER_ERROR"
                )
                return self._failure(
                    outcome=outcome,
                    role_count=role_count,
                    started=started,
                    restart=True,
                )
            return FinQAIsolatedShadowObservationV1(
                outcome=response.outcome,
                role_count=response.role_count,
                changed_role_count=response.changed_role_count,
                common_descriptor_count_at_4=(
                    response.common_descriptor_count_at_4
                ),
                latency_ms=max(0.0, (self._clock() - started) * 1_000),
                worker_peak_rss_bytes=response.worker_peak_rss_bytes,
                worker_restarted=False,
            )


__all__ = [
    "FinQAIsolatedShadowObservationV1",
    "FinQAIsolatedShadowWorkerV1",
    "FinQAShadowWorkerConfigV1",
    "FinQAShadowWorkerDiagnosticsV1",
    "FinQAShadowWorkerRequestV1",
    "FinQAShadowWorkerResponseV1",
]
