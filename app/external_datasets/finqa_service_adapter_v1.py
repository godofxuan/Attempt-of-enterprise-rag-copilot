from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from collections import Counter
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa_descriptor_shadow_v1 import (
    FinQADescriptorShadowRuntimeV1,
    FinQAPrimaryDescriptorDecisionV1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeDescriptorCatalogV3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)
from app.external_datasets.finqa_shadow_worker_v1 import (
    FinQAIsolatedShadowObservationV1,
)
from app.runtime.dark_observation import (
    DarkObservationProviderOutcome,
    DarkObservationRequest,
)


SERVICE_ADAPTER_VERSION = "finqa_typed_service_adapter_v1"
SkeletonOriginV1 = Literal["ONLINE_RULES", "ONLINE_MODEL"]
CatalogOriginV1 = Literal["RETRIEVED_ADMITTED_EVIDENCE"]
EligibilityReasonV1 = Literal[
    "TYPED_CONTEXT_COMPLETE",
    "NOT_FINANCIAL_NUMERIC",
    "MISSING_TYPED_SKELETON",
    "MISSING_SAFE_CATALOG",
    "POLICY_DENIED",
    "UNSUPPORTED_TYPED_CONTRACT",
]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _context_binding_sha256(
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


class FinQATypedServiceContextV1(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_typed_service_context_v1"
    ] = "finqa_typed_service_context_v1"
    question: str = Field(min_length=1, max_length=8_000)
    skeleton: SemanticProgramSkeletonV2
    catalog: RetrievableSafeDescriptorCatalogV3
    skeleton_origin: SkeletonOriginV1
    catalog_origin: CatalogOriginV1
    input_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def build(
        cls,
        *,
        question: str,
        skeleton: SemanticProgramSkeletonV2,
        catalog: RetrievableSafeDescriptorCatalogV3,
        skeleton_origin: SkeletonOriginV1,
        catalog_origin: CatalogOriginV1,
    ) -> FinQATypedServiceContextV1:
        return cls(
            question=question,
            skeleton=skeleton,
            catalog=catalog,
            skeleton_origin=skeleton_origin,
            catalog_origin=catalog_origin,
            input_binding_sha256=_context_binding_sha256(
                question=question,
                skeleton=skeleton,
                catalog=catalog,
            ),
        )

    @model_validator(mode="after")
    def validate_binding(self) -> FinQATypedServiceContextV1:
        expected = _context_binding_sha256(
            question=self.question,
            skeleton=self.skeleton,
            catalog=self.catalog,
        )
        if self.input_binding_sha256 != expected:
            raise ValueError("E17 typed context binding is invalid")
        return self


class FinQATypedServiceResolutionV1(_StrictFrozenModel):
    disposition: Literal["ELIGIBLE", "NOT_APPLICABLE"]
    reason: EligibilityReasonV1
    context: FinQATypedServiceContextV1 | None = None

    @classmethod
    def eligible(
        cls,
        context: FinQATypedServiceContextV1,
    ) -> FinQATypedServiceResolutionV1:
        return cls(
            disposition="ELIGIBLE",
            reason="TYPED_CONTEXT_COMPLETE",
            context=context,
        )

    @classmethod
    def not_applicable(
        cls,
        reason: Literal[
            "NOT_FINANCIAL_NUMERIC",
            "MISSING_TYPED_SKELETON",
            "MISSING_SAFE_CATALOG",
            "POLICY_DENIED",
            "UNSUPPORTED_TYPED_CONTRACT",
        ],
    ) -> FinQATypedServiceResolutionV1:
        return cls(disposition="NOT_APPLICABLE", reason=reason)

    @model_validator(mode="after")
    def validate_resolution(self) -> FinQATypedServiceResolutionV1:
        eligible = self.disposition == "ELIGIBLE"
        if eligible != (self.reason == "TYPED_CONTEXT_COMPLETE"):
            raise ValueError("E17 eligibility disposition and reason disagree")
        if eligible != (self.context is not None):
            raise ValueError("E17 eligibility context is inconsistent")
        return self


class FinQATypedContextResolverV1(Protocol):
    def resolve(
        self,
        request: DarkObservationRequest,
    ) -> FinQATypedServiceResolutionV1: ...


class FinQATypedShadowWorkerV1(Protocol):
    def observe(
        self,
        *,
        primary: FinQAPrimaryDescriptorDecisionV1,
        question: str,
        skeleton: SemanticProgramSkeletonV2,
        catalog: RetrievableSafeDescriptorCatalogV3,
    ) -> FinQAIsolatedShadowObservationV1: ...

    def close(self) -> None: ...


class FinQAServiceAdapterErrorV1(RuntimeError):
    """Safe adapter failure with a bounded code and no request content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"FinQA typed service adapter failed: {code}")


@dataclass(frozen=True)
class _PendingResolutionV1:
    resolution: FinQATypedServiceResolutionV1
    expires_at_monotonic: float


class FinQAEphemeralContextResolverV1:
    """Bounded consume-once bridge between request and dark worker threads."""

    def __init__(
        self,
        *,
        capacity: int = 256,
        ttl_seconds: float = 5.0,
        clock=time.perf_counter,
    ) -> None:
        if not 1 <= capacity <= 4_096:
            raise ValueError("E17 resolver capacity is out of range")
        if not 0.01 <= ttl_seconds <= 60:
            raise ValueError("E17 resolver TTL is out of range")
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: dict[str, _PendingResolutionV1] = {}
        self._counters: Counter[str] = Counter()
        self._high_watermark = 0
        self._closed = False

    @staticmethod
    def _validate_request_id(request_id: str) -> None:
        if (
            not isinstance(request_id, str)
            or not request_id.strip()
            or len(request_id) > 256
        ):
            raise FinQAServiceAdapterErrorV1("invalid_request_id")

    def _purge_expired_locked(self, now: float) -> None:
        expired = tuple(
            request_id
            for request_id, pending in self._pending.items()
            if pending.expires_at_monotonic <= now
        )
        for request_id in expired:
            del self._pending[request_id]
        if expired:
            self._counters["expired_total"] += len(expired)

    def register(
        self,
        *,
        request_id: str,
        resolution: FinQATypedServiceResolutionV1,
    ) -> None:
        self._validate_request_id(request_id)
        if not isinstance(resolution, FinQATypedServiceResolutionV1):
            raise FinQAServiceAdapterErrorV1("invalid_resolution")
        now = self._clock()
        with self._lock:
            if self._closed:
                raise FinQAServiceAdapterErrorV1("resolver_closed")
            self._purge_expired_locked(now)
            if request_id in self._pending:
                self._counters["duplicate_rejected_total"] += 1
                raise FinQAServiceAdapterErrorV1("duplicate_request_id")
            if len(self._pending) >= self.capacity:
                self._counters["capacity_rejected_total"] += 1
                raise FinQAServiceAdapterErrorV1("capacity_exceeded")
            self._pending[request_id] = _PendingResolutionV1(
                resolution=resolution,
                expires_at_monotonic=now + self.ttl_seconds,
            )
            self._counters["registered_total"] += 1
            self._high_watermark = max(
                self._high_watermark,
                len(self._pending),
            )

    def resolve(
        self,
        request: DarkObservationRequest,
    ) -> FinQATypedServiceResolutionV1:
        self._validate_request_id(request.request_id)
        now = self._clock()
        with self._lock:
            self._purge_expired_locked(now)
            pending = self._pending.pop(request.request_id, None)
            if pending is None:
                self._counters["unresolved_total"] += 1
                return FinQATypedServiceResolutionV1.not_applicable(
                    "UNSUPPORTED_TYPED_CONTRACT"
                )
            self._counters["consumed_total"] += 1
            return pending.resolution

    def discard(self, request_id: str) -> bool:
        self._validate_request_id(request_id)
        with self._lock:
            removed = self._pending.pop(request_id, None) is not None
            if removed:
                self._counters["discarded_total"] += 1
            return removed

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "schema_version": "finqa_ephemeral_context_metrics_v1",
                "capacity": self.capacity,
                "ttl_seconds": self.ttl_seconds,
                "pending_context_count": len(self._pending),
                "pending_high_watermark": self._high_watermark,
                "counters": dict(sorted(self._counters.items())),
                "content_retained_in_snapshot": False,
                "closed": self._closed,
            }

    def close(self) -> None:
        with self._lock:
            pending_count = len(self._pending)
            if pending_count:
                self._counters["shutdown_discarded_total"] += pending_count
            self._pending.clear()
            self._closed = True


class FinQATypedServiceAdapterV1:
    def __init__(
        self,
        *,
        resolver: FinQATypedContextResolverV1,
        worker: FinQATypedShadowWorkerV1,
        primary_runtime: FinQADescriptorShadowRuntimeV1 | None = None,
        clock=time.perf_counter,
    ) -> None:
        self._resolver = resolver
        self._worker = worker
        self._primary_runtime = primary_runtime or FinQADescriptorShadowRuntimeV1()
        self._clock = clock
        self._lock = threading.Lock()
        self._eligibility_reasons: Counter[str] = Counter()
        self._provider_outcomes: Counter[str] = Counter()
        self._failures: Counter[str] = Counter()
        self._worker_calls = 0
        self._closed = False

    def _record_eligibility(self, reason: str) -> None:
        with self._lock:
            self._eligibility_reasons[reason] += 1

    def _record_outcome(self, outcome: str) -> None:
        with self._lock:
            self._provider_outcomes[outcome] += 1

    def _fail(self, code: str) -> None:
        with self._lock:
            self._failures[code] += 1
        raise FinQAServiceAdapterErrorV1(code)

    def observe(
        self,
        request: DarkObservationRequest,
        *,
        deadline_monotonic: float,
    ) -> DarkObservationProviderOutcome:
        with self._lock:
            closed = self._closed
        if closed:
            self._fail("adapter_closed")
        if not math.isfinite(deadline_monotonic):
            self._fail("invalid_deadline")
        if self._clock() >= deadline_monotonic:
            self._fail("deadline_expired")
        try:
            resolution = self._resolver.resolve(request)
        except Exception:
            self._fail("resolver_error")
        if not isinstance(resolution, FinQATypedServiceResolutionV1):
            self._fail("invalid_resolution")
        self._record_eligibility(resolution.reason)
        if resolution.disposition == "NOT_APPLICABLE":
            self._record_outcome("NOT_APPLICABLE")
            return "NOT_APPLICABLE"

        context = resolution.context
        if context is None:
            self._fail("invalid_resolution")
        if context.question != request.question:
            self._fail("input_binding_mismatch")
        if self._clock() >= deadline_monotonic:
            self._fail("deadline_expired")
        try:
            primary = self._primary_runtime.select_primary(
                question=context.question,
                skeleton=context.skeleton,
                catalog=context.catalog,
            )
        except Exception:
            self._fail("primary_selection_error")
        if primary.result.generation_calls != 0:
            self._fail("primary_model_call_detected")
        if self._clock() >= deadline_monotonic:
            self._fail("deadline_expired")
        with self._lock:
            self._worker_calls += 1
        try:
            observation = self._worker.observe(
                primary=primary,
                question=context.question,
                skeleton=context.skeleton,
                catalog=context.catalog,
            )
        except Exception:
            self._fail("worker_error")
        if self._clock() >= deadline_monotonic:
            self._fail("deadline_expired")
        if observation.outcome == "MATCH":
            outcome: DarkObservationProviderOutcome = "MATCH"
        elif observation.outcome == "DIVERGED":
            outcome = "DIFFERENT"
        else:
            self._fail("worker_nonterminal_outcome")
        self._record_outcome(outcome)
        return outcome

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "schema_version": "finqa_typed_service_adapter_metrics_v1",
                "adapter_version": SERVICE_ADAPTER_VERSION,
                "eligibility_reasons": dict(sorted(self._eligibility_reasons.items())),
                "provider_outcomes": dict(sorted(self._provider_outcomes.items())),
                "failures": dict(sorted(self._failures.items())),
                "worker_calls": self._worker_calls,
                "model_call_count": 0,
                "content_retained": False,
                "closed": self._closed,
            }

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._worker.close()


__all__ = [
    "EligibilityReasonV1",
    "FinQAEphemeralContextResolverV1",
    "FinQAServiceAdapterErrorV1",
    "FinQATypedContextResolverV1",
    "FinQATypedServiceAdapterV1",
    "FinQATypedServiceContextV1",
    "FinQATypedServiceResolutionV1",
    "SERVICE_ADAPTER_VERSION",
]
