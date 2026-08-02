from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa import FinQACase
from app.external_datasets.finqa_descriptor_retriever_v5 import (
    RETRIEVER_VERSION,
)
from app.external_datasets.finqa_descriptor_shadow_v1 import (
    FinQADescriptorShadowRuntimeV1,
    FinQAPrimaryDescriptorDecisionV1,
)
from app.external_datasets.finqa_shadow_pool_protocol_v1 import (
    FinQAShadowPoolReplayProtocolV1,
)
from app.external_datasets.finqa_shadow_pool_v1 import (
    FinQABoundedShadowWorkerPoolV1,
    FinQAPooledShadowObservationV1,
)
from app.external_datasets.finqa_shadow_replay_v1 import (
    FinQAAggregateDistributionV1,
    FinQAShadowPreparationSummaryV1,
    PreparedFinQAShadowReplayCaseV1,
    prepare_finqa_shadow_replay_case_v1,
    select_shadow_replay_cases_v1,
)
from app.external_datasets.finqa_shadow_worker_protocol_v1 import (
    FinQAShadowWorkerReplayProtocolV1,
)
from app.observability.metrics import nearest_rank_percentile
from app.security.retrieved_content import RetrievedContentGuard


POOL_REPLAY_SUMMARY_VERSION = "finqa_shadow_pool_replay_summary_v1"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class FinQAShadowPoolLoadSummaryV1(_StrictFrozenModel):
    caller_concurrency: int = Field(ge=1)
    attempted_count: int = Field(ge=0)
    admitted_count: int = Field(ge=0)
    executed_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    outcome_counts: dict[str, int]
    role_count: int = Field(ge=0)
    changed_role_count: int = Field(ge=0)
    common_descriptor_count_at_4: int = Field(ge=0)
    backpressure_rejected_count: int = Field(ge=0)
    deadline_exceeded_count: int = Field(ge=0)
    pool_state_rejected_count: int = Field(ge=0)
    late_result_discarded_count: int = Field(ge=0)
    cancelled_before_execution_count: int = Field(ge=0)
    active_worker_high_watermark: int = Field(ge=0)
    queue_high_watermark: int = Field(ge=0)
    worker_restart_count: int = Field(ge=0)
    model_call_count: Literal[0]
    elapsed_ms: float = Field(gt=0)
    throughput_requests_per_second: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_accounting(self) -> FinQAShadowPoolLoadSummaryV1:
        allowed = {
            "MATCH",
            "DIVERGED",
            "INPUT_MISMATCH",
            "PAYLOAD_REJECTED",
            "WORKER_ERROR",
            "WORKER_TIMEOUT",
            "WORKER_CRASH",
            "BACKPRESSURE_REJECTED",
            "DEADLINE_EXCEEDED",
            "POOL_NOT_RUNNING",
            "POOL_CLOSED",
        }
        if (
            not set(self.outcome_counts).issubset(allowed)
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in self.outcome_counts.values()
            )
            or sum(self.outcome_counts.values()) != self.attempted_count
        ):
            raise ValueError("E14 returned outcome counts do not reconcile")
        if self.completed_count != (
            self.outcome_counts.get("MATCH", 0)
            + self.outcome_counts.get("DIVERGED", 0)
        ):
            raise ValueError("E14 completed count does not reconcile")
        if self.backpressure_rejected_count != self.outcome_counts.get(
            "BACKPRESSURE_REJECTED", 0
        ):
            raise ValueError("E14 backpressure count does not reconcile")
        if self.deadline_exceeded_count != self.outcome_counts.get(
            "DEADLINE_EXCEEDED", 0
        ):
            raise ValueError("E14 deadline count does not reconcile")
        if self.admitted_count > self.attempted_count:
            raise ValueError("E14 admitted count exceeds attempts")
        return self


class FinQAShadowPoolResourceSummaryV1(_StrictFrozenModel):
    configured_worker_count: int = Field(ge=1)
    workers_with_rss_samples: int = Field(ge=0)
    maximum_individual_worker_peak_rss_bytes: int = Field(ge=0)
    worker_pool_rss_upper_bound_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_resources(self) -> FinQAShadowPoolResourceSummaryV1:
        if self.workers_with_rss_samples > self.configured_worker_count:
            raise ValueError("E14 RSS samples exceed configured workers")
        if (
            self.maximum_individual_worker_peak_rss_bytes
            > self.worker_pool_rss_upper_bound_bytes
        ):
            raise ValueError("E14 pool RSS upper bound is inconsistent")
        return self


class FinQAShadowPoolReplaySummaryV1(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_shadow_pool_replay_summary_v1"
    ] = POOL_REPLAY_SUMMARY_VERSION
    preparation: FinQAShadowPreparationSummaryV1
    load: FinQAShadowPoolLoadSummaryV1
    queue_wait_ms: FinQAAggregateDistributionV1
    end_to_end_latency_ms: FinQAAggregateDistributionV1
    worker_pool_resources: FinQAShadowPoolResourceSummaryV1
    all_primary_results_e8: bool
    per_request_rows_persisted: Literal[0]
    quality_labels_consumed: Literal[0]

    @model_validator(mode="after")
    def validate_cross_group_accounting(
        self,
    ) -> FinQAShadowPoolReplaySummaryV1:
        if self.load.attempted_count != (
            self.preparation.prepared_case_count
            - self.preparation.primary_failure_count
        ):
            raise ValueError("E14 preparation and load counts do not reconcile")
        if (
            self.queue_wait_ms.count != self.load.completed_count
            or self.end_to_end_latency_ms.count != self.load.completed_count
        ):
            raise ValueError("E14 completed observations lack latency samples")
        return self


def _distribution(values: list[float]) -> FinQAAggregateDistributionV1:
    if not values:
        return FinQAAggregateDistributionV1(count=0)
    return FinQAAggregateDistributionV1(
        count=len(values),
        p50=nearest_rank_percentile(values, 0.50),
        p95=nearest_rank_percentile(values, 0.95),
        maximum=max(values),
    )


def run_finqa_shadow_pool_replay_v1(
    cases: list[FinQACase],
    *,
    e13_protocol: FinQAShadowWorkerReplayProtocolV1,
    e14_protocol: FinQAShadowPoolReplayProtocolV1,
    pool: FinQABoundedShadowWorkerPoolV1,
    guard: RetrievedContentGuard | None = None,
    primary_runtime: FinQADescriptorShadowRuntimeV1 | None = None,
) -> FinQAShadowPoolReplaySummaryV1:
    if any(pool.metrics().returned_outcome_counts.values()):
        raise ValueError("E14 operational replay requires a fresh worker pool")
    selected = select_shadow_replay_cases_v1(cases, protocol=e13_protocol)
    content_guard = guard or RetrievedContentGuard()
    runtime = primary_runtime or FinQADescriptorShadowRuntimeV1()
    prepared_count = 0
    preparation_failures = 0
    primary_failures = 0
    all_primary_e8 = True
    requests: list[
        tuple[FinQAPrimaryDescriptorDecisionV1, PreparedFinQAShadowReplayCaseV1]
    ] = []

    for case in selected:
        try:
            prepared = prepare_finqa_shadow_replay_case_v1(
                case,
                guard=content_guard,
                selected_unit_limit=(
                    e13_protocol.dataset.max_selected_units_per_case
                ),
            )
            prepared_count += 1
        except Exception:
            preparation_failures += 1
            continue
        try:
            primary = runtime.select_primary(
                question=prepared.question,
                skeleton=prepared.skeleton,
                catalog=prepared.catalog,
            )
        except Exception:
            primary_failures += 1
            all_primary_e8 = False
            continue
        all_primary_e8 = all_primary_e8 and (
            primary.result.retriever_version == RETRIEVER_VERSION
            and primary.result.generation_calls == 0
        )
        requests.append((primary, prepared))

    started = time.perf_counter()
    with ThreadPoolExecutor(
        max_workers=e14_protocol.pool.caller_concurrency,
        thread_name_prefix="finqa-e14-load-caller",
    ) as executor:
        futures = [
            executor.submit(
                pool.observe,
                primary=primary,
                question=prepared.question,
                skeleton=prepared.skeleton,
                catalog=prepared.catalog,
            )
            for primary, prepared in requests
        ]
        observations = [future.result() for future in futures]
    elapsed_ms = max(0.001, (time.perf_counter() - started) * 1_000)
    metrics = pool.metrics()
    outcomes = Counter(item.outcome for item in observations)
    completed = [
        item for item in observations if item.outcome in {"MATCH", "DIVERGED"}
    ]
    worker_rss: dict[int, int] = {}
    for item in completed:
        if item.worker_slot is not None and item.worker_peak_rss_bytes is not None:
            worker_rss[item.worker_slot] = max(
                worker_rss.get(item.worker_slot, 0),
                item.worker_peak_rss_bytes,
            )

    return FinQAShadowPoolReplaySummaryV1(
        preparation=FinQAShadowPreparationSummaryV1(
            selected_case_count=len(selected),
            prepared_case_count=prepared_count,
            preparation_failure_count=preparation_failures,
            primary_failure_count=primary_failures,
        ),
        load=FinQAShadowPoolLoadSummaryV1(
            caller_concurrency=e14_protocol.pool.caller_concurrency,
            attempted_count=len(observations),
            admitted_count=metrics.admitted_count,
            executed_count=metrics.executed_count,
            completed_count=len(completed),
            outcome_counts=dict(sorted(outcomes.items())),
            role_count=sum(item.role_count for item in completed),
            changed_role_count=sum(item.changed_role_count for item in completed),
            common_descriptor_count_at_4=sum(
                item.common_descriptor_count_at_4 for item in completed
            ),
            backpressure_rejected_count=(
                metrics.backpressure_rejected_count
            ),
            deadline_exceeded_count=metrics.deadline_exceeded_count,
            pool_state_rejected_count=metrics.pool_state_rejected_count,
            late_result_discarded_count=metrics.late_result_discarded_count,
            cancelled_before_execution_count=(
                metrics.cancelled_before_execution_count
            ),
            active_worker_high_watermark=(
                metrics.active_worker_high_watermark
            ),
            queue_high_watermark=metrics.queue_high_watermark,
            worker_restart_count=metrics.worker_restart_count,
            model_call_count=0,
            elapsed_ms=elapsed_ms,
            throughput_requests_per_second=(
                len(observations) / (elapsed_ms / 1_000)
            ),
        ),
        queue_wait_ms=_distribution([item.queue_wait_ms for item in completed]),
        end_to_end_latency_ms=_distribution(
            [item.end_to_end_latency_ms for item in completed]
        ),
        worker_pool_resources=FinQAShadowPoolResourceSummaryV1(
            configured_worker_count=e14_protocol.pool.worker_count,
            workers_with_rss_samples=len(worker_rss),
            maximum_individual_worker_peak_rss_bytes=(
                max(worker_rss.values(), default=0)
            ),
            worker_pool_rss_upper_bound_bytes=sum(worker_rss.values()),
        ),
        all_primary_results_e8=all_primary_e8,
        per_request_rows_persisted=0,
        quality_labels_consumed=0,
    )


def evaluate_shadow_pool_replay_gates_v1(
    summary: FinQAShadowPoolReplaySummaryV1,
    *,
    protocol: FinQAShadowPoolReplayProtocolV1,
) -> dict[str, bool]:
    load = summary.load
    gates = protocol.replay_gates
    selected = summary.preparation.selected_case_count
    prepared = summary.preparation.prepared_case_count
    worker_errors = sum(
        load.outcome_counts.get(outcome, 0)
        for outcome in (
            "INPUT_MISMATCH",
            "PAYLOAD_REJECTED",
            "WORKER_ERROR",
            "WORKER_TIMEOUT",
            "WORKER_CRASH",
            "POOL_NOT_RUNNING",
            "POOL_CLOSED",
        )
    )
    return {
        "preparation_success_rate": (
            prepared / selected >= gates.min_preparation_success_rate
        ),
        "admitted_completion_rate": (
            load.completed_count / load.admitted_count
            if load.admitted_count
            else 0.0
        )
        >= gates.min_admitted_completion_rate,
        "nominal_backpressure_rejections": (
            load.backpressure_rejected_count
            <= gates.max_nominal_backpressure_rejections
        ),
        "nominal_deadline_exceeded": (
            load.deadline_exceeded_count <= gates.max_nominal_deadline_exceeded
        ),
        "nominal_worker_errors": worker_errors <= gates.max_nominal_worker_errors,
        "active_worker_high_watermark": (
            load.active_worker_high_watermark
            >= gates.min_active_worker_high_watermark
        ),
        "queue_high_watermark": (
            load.queue_high_watermark <= gates.max_queue_high_watermark
        ),
        "end_to_end_latency_p95": (
            summary.end_to_end_latency_ms.p95 is not None
            and summary.end_to_end_latency_ms.p95
            <= gates.max_end_to_end_latency_p95_ms
        ),
        "worker_pool_rss_upper_bound": (
            summary.worker_pool_resources.workers_with_rss_samples
            == protocol.pool.worker_count
            and summary.worker_pool_resources.worker_pool_rss_upper_bound_bytes
            <= gates.max_worker_pool_rss_upper_bound_bytes
        ),
        "all_primary_results_e8": summary.all_primary_results_e8,
        "zero_model_calls": load.model_call_count == 0,
        "aggregate_only_output": summary.per_request_rows_persisted == 0,
        "no_quality_labels_or_scores": summary.quality_labels_consumed == 0,
    }


__all__ = [
    "FinQAShadowPoolLoadSummaryV1",
    "FinQAShadowPoolReplaySummaryV1",
    "FinQAShadowPoolResourceSummaryV1",
    "evaluate_shadow_pool_replay_gates_v1",
    "run_finqa_shadow_pool_replay_v1",
]
