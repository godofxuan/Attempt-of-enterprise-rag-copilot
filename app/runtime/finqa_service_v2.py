from __future__ import annotations

import math
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from app.agent.generation_v2 import GenerationV2ResponseBuilder
from app.agent.query_analysis import RuleFirstQueryAnalyzer
from app.agent.runner_v2 import ResponseBuilder, V2AgentRunner, budget_from_settings
from app.agent.tools_v2 import V2ToolRegistry
from app.config import Settings
from app.domain.evidence import AnswerResponse
from app.domain.queries import UserContext
from app.external_datasets.finqa_admitted_context_v1 import (
    FinQAAdmittedContextCoordinatorV1,
    FinQATypedObservationResponseBuilderV1,
)
from app.external_datasets.finqa_service_adapter_v1 import (
    FinQAEphemeralContextResolverV1,
    FinQATypedServiceAdapterV1,
)
from app.external_datasets.finqa_shadow_worker_v1 import (
    FinQAIsolatedShadowWorkerV1,
)
from app.retrieval.navigation import DocumentNavigator
from app.retrieval.pipeline import HybridRetrievalPipeline
from app.retrieval.snapshot import V2IndexSnapshot
from app.retriever import _embed_text
from app.runtime.dark_observation import build_dark_observation_service
from app.runtime.finqa_service_protocol_v2 import FINQA_SERVICE_ASSEMBLY_VERSION
from app.runtime.resources import ServiceContainer, build_service_container


_EVIDENCE_DIR = (
    Path(__file__).resolve().parents[2] / "docs" / "external_datasets" / "evidence"
)
_COORDINATOR_COUNTERS = frozenset(
    {
        "dark_offer_error_total",
        "offer_admitted_total",
        "offer_backpressure_total",
        "offer_closed_total",
        "offer_disabled_total",
        "offer_sample_skipped_total",
        "offer_unavailable_total",
        "resolver_registration_error_total",
    }
)
_ELIGIBILITY_REASONS = frozenset(
    {
        "MISSING_SAFE_CATALOG",
        "MISSING_TYPED_SKELETON",
        "NOT_EVALUATED_DEFAULT_OFF",
        "NOT_FINANCIAL_NUMERIC",
        "POLICY_DENIED",
        "TYPED_CONTEXT_COMPLETE",
        "UNSUPPORTED_TYPED_CONTRACT",
    }
)
_RESOLVER_COUNTERS = frozenset(
    {
        "capacity_rejected_total",
        "consumed_total",
        "discarded_total",
        "duplicate_rejected_total",
        "expired_total",
        "registered_total",
        "shutdown_discarded_total",
        "unresolved_total",
    }
)
_ADAPTER_FAILURES = frozenset(
    {
        "adapter_closed",
        "deadline_expired",
        "input_binding_mismatch",
        "invalid_deadline",
        "invalid_resolution",
        "primary_model_call_detected",
        "primary_selection_error",
        "resolver_error",
        "worker_error",
        "worker_nonterminal_outcome",
    }
)
_PROVIDER_OUTCOMES = frozenset({"DIFFERENT", "MATCH", "NOT_APPLICABLE"})
_DARK_COUNTERS = frozenset(
    {
        "admitted_total",
        "backpressure_total",
        "closed_rejected_total",
        "completed_total",
        "deadline_exceeded_total",
        "disabled_total",
        "execution_started_total",
        "offered_total",
        "provider_error_total",
        "sample_skipped_total",
        "shutdown_cancelled_total",
        "unavailable_total",
    }
)


class AgentRunnerV2(Protocol):
    def run(
        self,
        question: str,
        user: UserContext,
        top_k: int | None = None,
    ) -> AnswerResponse: ...


class ShadowWorkerLifecycleV2(Protocol):
    def start(self) -> bool: ...

    def close(self) -> None: ...


class LazyAgentRunnerV2:
    def __init__(self, factory: Callable[[], AgentRunnerV2]) -> None:
        self._factory = factory
        self._lock = threading.Lock()
        self._runner: AgentRunnerV2 | None = None

    def _get(self) -> AgentRunnerV2:
        with self._lock:
            if self._runner is None:
                self._runner = self._factory()
            return self._runner

    def run(
        self,
        question: str,
        user: UserContext,
        top_k: int | None = None,
    ) -> AnswerResponse:
        return self._get().run(question, user, top_k)


class FinQAServiceRuntimeV2:
    def __init__(
        self,
        *,
        container: ServiceContainer,
        coordinator: FinQAAdmittedContextCoordinatorV1,
        shadow_worker: ShadowWorkerLifecycleV2,
    ) -> None:
        self.container = container
        self.coordinator = coordinator
        self.shadow_worker = shadow_worker
        self._lock = threading.Lock()
        self._started = False
        self._closed = False
        self._failed = False
        self._worker_started = False
        self._startup_failure_total = 0
        self._shutdown_total = 0

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("E19 service runtime is closed")
            if self._started:
                return
        resources_started = False
        try:
            self.container.resources.start()
            resources_started = True
            if self.coordinator.dark_observation.config.mode == "LOCAL_TEST_ONLY":
                if not self.shadow_worker.start():
                    raise RuntimeError("E19 isolated worker failed to start")
                with self._lock:
                    self._worker_started = True
            self.coordinator.start()
        except Exception:
            with self._lock:
                self._failed = True
                self._startup_failure_total += 1
            try:
                self.coordinator.close()
            finally:
                if resources_started:
                    self.container.resources.close()
            raise RuntimeError("E19 versioned service startup failed") from None
        with self._lock:
            self._started = True

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._shutdown_total += 1
        try:
            self.coordinator.close()
        finally:
            self.container.resources.close()

    def lifecycle_snapshot(self) -> dict[str, int | bool | str]:
        with self._lock:
            if self._closed:
                status = "CLOSED"
            elif self._failed:
                status = "FAILED"
            elif self._started:
                status = "RUNNING"
            else:
                status = "NEW"
            return {
                "status": status,
                "started": self._started,
                "closed": self._closed,
                "worker_started": self._worker_started,
                "startup_failure_total": self._startup_failure_total,
                "shutdown_total": self._shutdown_total,
            }


@dataclass(frozen=True)
class FinQAServiceAssemblyV2:
    container: ServiceContainer
    runtime: FinQAServiceRuntimeV2
    agent_runner: AgentRunnerV2


def build_finqa_v2_agent_runner(
    *,
    settings: Settings,
    coordinator: FinQAAdmittedContextCoordinatorV1,
    registry: V2ToolRegistry | None = None,
    response_builder: ResponseBuilder | None = None,
) -> V2AgentRunner:
    active_registry = registry
    if active_registry is None:
        snapshot = V2IndexSnapshot.load(settings.v2_indexes_dir)

        def embed_text(text: str) -> list[float]:
            return _embed_text(settings.embedding_model, text)

        pipeline = HybridRetrievalPipeline(snapshot, embed_text=embed_text)
        navigator = DocumentNavigator(snapshot, pipeline=pipeline)
        active_registry = V2ToolRegistry(navigator)
    delegate = response_builder or GenerationV2ResponseBuilder(
        model=settings.chat_model,
    )
    return V2AgentRunner(
        registry=active_registry,
        analyzer=RuleFirstQueryAnalyzer(),
        response_builder=FinQATypedObservationResponseBuilderV1(
            delegate=delegate,
            coordinator=coordinator,
        ),
        budget=budget_from_settings(settings),
    )


def build_finqa_service_assembly_v2(
    settings: Settings,
    *,
    base_container: ServiceContainer | None = None,
    shadow_worker: ShadowWorkerLifecycleV2 | None = None,
    agent_runner: AgentRunnerV2 | None = None,
) -> FinQAServiceAssemblyV2:
    worker = shadow_worker or FinQAIsolatedShadowWorkerV1(
        evidence_dir=_EVIDENCE_DIR,
    )
    resolver = FinQAEphemeralContextResolverV1(
        capacity=max(16, settings.dark_observation_queue_capacity * 2),
        ttl_seconds=min(
            60.0,
            max(1.0, settings.dark_observation_deadline_ms / 1_000 + 1.0),
        ),
    )
    adapter = FinQATypedServiceAdapterV1(
        resolver=resolver,
        worker=worker,
    )
    dark_observation = build_dark_observation_service(
        settings,
        provider=adapter,
    )
    coordinator = FinQAAdmittedContextCoordinatorV1(
        resolver=resolver,
        adapter=adapter,
        dark_observation=dark_observation,
    )
    original = base_container or build_service_container(settings)
    container = replace(original, dark_observation=dark_observation)
    runtime = FinQAServiceRuntimeV2(
        container=container,
        coordinator=coordinator,
        shadow_worker=worker,
    )
    runner = agent_runner or LazyAgentRunnerV2(
        lambda: build_finqa_v2_agent_runner(
            settings=settings,
            coordinator=coordinator,
        )
    )
    return FinQAServiceAssemblyV2(
        container=container,
        runtime=runtime,
        agent_runner=runner,
    )


def _safe_counts(value: object, *, allowed: frozenset[str]) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, count in value.items():
        if (
            isinstance(key, str)
            and key in allowed
            and isinstance(count, int)
            and not isinstance(count, bool)
            and count >= 0
        ):
            result[key] = count
    return dict(sorted(result.items()))


def _safe_latency(value: object) -> dict[str, int | float]:
    if not isinstance(value, dict):
        return {"count": 0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    result: dict[str, int | float] = {"count": 0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    for key in result:
        candidate = value.get(key)
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            number = float(candidate)
            if math.isfinite(number) and number >= 0:
                result[key] = int(number) if key == "count" else round(number, 3)
    return result


def safe_finqa_service_snapshot_v2(runtime: object) -> dict[str, object]:
    try:
        if not isinstance(runtime, FinQAServiceRuntimeV2):
            raise TypeError("unexpected E19 runtime")
        source = runtime.coordinator.snapshot()
        resolver = source.get("resolver", {})
        adapter = source.get("adapter", {})
        dark = source.get("dark_observation", {})
        if not all(isinstance(item, dict) for item in (resolver, adapter, dark)):
            raise TypeError("invalid E19 component snapshot")
        lifecycle = runtime.lifecycle_snapshot()
        return {
            "schema_version": "finqa_service_metrics_v2",
            "assembly_version": FINQA_SERVICE_ASSEMBLY_VERSION,
            "status": lifecycle["status"],
            "mode": runtime.coordinator.dark_observation.config.mode,
            "lifecycle": lifecycle,
            "counters": _safe_counts(
                source.get("counters"), allowed=_COORDINATOR_COUNTERS
            ),
            "eligibility_reasons": _safe_counts(
                source.get("eligibility_reasons"), allowed=_ELIGIBILITY_REASONS
            ),
            "preparation_latency_ms": _safe_latency(
                source.get("preparation_latency_ms")
            ),
            "resolver": {
                "pending_context_count": int(
                    max(0, int(resolver.get("pending_context_count", 0)))
                ),
                "pending_high_watermark": int(
                    max(0, int(resolver.get("pending_high_watermark", 0)))
                ),
                "counters": _safe_counts(
                    resolver.get("counters"), allowed=_RESOLVER_COUNTERS
                ),
                "closed": bool(resolver.get("closed", False)),
            },
            "adapter": {
                "eligibility_reasons": _safe_counts(
                    adapter.get("eligibility_reasons"), allowed=_ELIGIBILITY_REASONS
                ),
                "provider_outcomes": _safe_counts(
                    adapter.get("provider_outcomes"), allowed=_PROVIDER_OUTCOMES
                ),
                "failures": _safe_counts(
                    adapter.get("failures"), allowed=_ADAPTER_FAILURES
                ),
                "worker_calls": int(max(0, int(adapter.get("worker_calls", 0)))),
                "closed": bool(adapter.get("closed", False)),
            },
            "dark_observation": {
                "status": (
                    dark.get("status")
                    if dark.get("status") in {"OFF", "RUNNING", "CLOSED"}
                    else "UNAVAILABLE"
                ),
                "mode": (
                    dark.get("mode")
                    if dark.get("mode") in {"OFF", "LOCAL_TEST_ONLY"}
                    else "OFF"
                ),
                "counters": _safe_counts(
                    dark.get("counters"), allowed=_DARK_COUNTERS
                ),
                "provider_outcomes": _safe_counts(
                    dark.get("provider_outcomes"), allowed=_PROVIDER_OUTCOMES
                ),
            },
            "secondary_retrieval_calls": 0,
            "model_calls": 0,
            "legacy_generic_offer_calls": 0,
            "content_retained": False,
        }
    except Exception:
        return {
            "schema_version": "finqa_service_metrics_v2",
            "assembly_version": FINQA_SERVICE_ASSEMBLY_VERSION,
            "status": "UNAVAILABLE",
            "mode": "OFF",
            "secondary_retrieval_calls": 0,
            "model_calls": 0,
            "legacy_generic_offer_calls": 0,
            "content_retained": False,
        }


__all__ = [
    "AgentRunnerV2",
    "FinQAServiceAssemblyV2",
    "FinQAServiceRuntimeV2",
    "LazyAgentRunnerV2",
    "build_finqa_service_assembly_v2",
    "build_finqa_v2_agent_runner",
    "safe_finqa_service_snapshot_v2",
]
