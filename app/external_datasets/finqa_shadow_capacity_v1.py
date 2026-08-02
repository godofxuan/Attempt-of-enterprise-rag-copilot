from __future__ import annotations

import hashlib
import json
import statistics
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa import FinQACase
from app.external_datasets.finqa_descriptor_retriever_v5 import RETRIEVER_VERSION
from app.external_datasets.finqa_descriptor_shadow_v1 import (
    FinQADescriptorShadowRuntimeV1,
    FinQAPrimaryDescriptorDecisionV1,
)
from app.external_datasets.finqa_shadow_capacity_protocol_v1 import (
    FinQAShadowCapacityProtocolV1,
)
from app.external_datasets.finqa_shadow_pool_v1 import (
    FinQABoundedShadowWorkerPoolV1,
    FinQAShadowWorkerPoolConfigV1,
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
from app.external_datasets.finqa_shadow_worker_v1 import FinQAShadowWorkerConfigV1
from app.observability.metrics import nearest_rank_percentile
from app.security.retrieved_content import RetrievedContentGuard


CAPACITY_SUMMARY_VERSION = "finqa_shadow_capacity_summary_v1"
_COMPLETED_OUTCOMES = {"MATCH", "DIVERGED"}
_WORKER_ERROR_OUTCOMES = {
    "INPUT_MISMATCH",
    "PAYLOAD_REJECTED",
    "WORKER_ERROR",
    "WORKER_TIMEOUT",
    "WORKER_CRASH",
    "POOL_NOT_RUNNING",
    "POOL_CLOSED",
}


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


@dataclass(frozen=True)
class FinQAShadowCapacityRequestV1:
    primary: FinQAPrimaryDescriptorDecisionV1
    prepared: PreparedFinQAShadowReplayCaseV1


@dataclass(frozen=True)
class PreparedFinQAShadowCapacityWorkloadV1:
    preparation: FinQAShadowPreparationSummaryV1
    requests: tuple[FinQAShadowCapacityRequestV1, ...]
    all_primary_results_e8: bool


class FinQAShadowCapacityScheduleItemV1(_StrictFrozenModel):
    schedule_ordinal: int = Field(ge=1)
    repetition_index: int = Field(ge=0)
    config_id: str = Field(pattern=r"^w(?:1|2|4)-c(?:1|4|8)$")
    worker_count: int = Field(ge=1, le=4)
    caller_concurrency: int = Field(ge=1, le=8)

    @model_validator(mode="after")
    def validate_config_id(self) -> FinQAShadowCapacityScheduleItemV1:
        if self.config_id != f"w{self.worker_count}-c{self.caller_concurrency}":
            raise ValueError("E15 schedule config id does not match dimensions")
        return self


class FinQAShadowCapacityTrialV1(_StrictFrozenModel):
    trial_id: str = Field(pattern=r"^r[0-2]-w(?:1|2|4)-c(?:1|4|8)$")
    schedule_ordinal: int = Field(ge=1)
    repetition_index: int = Field(ge=0, le=2)
    config_id: str = Field(pattern=r"^w(?:1|2|4)-c(?:1|4|8)$")
    worker_count: int = Field(ge=1, le=4)
    caller_concurrency: int = Field(ge=1, le=8)
    attempted_count: int = Field(ge=1)
    admitted_count: int = Field(ge=0)
    executed_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    outcome_counts: dict[str, int]
    backpressure_rejected_count: int = Field(ge=0)
    deadline_exceeded_count: int = Field(ge=0)
    worker_error_count: int = Field(ge=0)
    worker_restart_count: int = Field(ge=0)
    late_result_discarded_count: int = Field(ge=0)
    cancelled_before_execution_count: int = Field(ge=0)
    active_worker_high_watermark: int = Field(ge=0)
    queue_high_watermark: int = Field(ge=0)
    queue_wait_ms: FinQAAggregateDistributionV1
    end_to_end_latency_ms: FinQAAggregateDistributionV1
    elapsed_ms: float = Field(gt=0)
    throughput_requests_per_second: float = Field(gt=0)
    workers_with_rss_samples: int = Field(ge=0)
    maximum_individual_worker_peak_rss_bytes: int = Field(ge=0)
    worker_pool_rss_upper_bound_bytes: int = Field(ge=0)
    close_completed: bool
    residual_dispatcher_count: int = Field(ge=0)
    residual_worker_pid_count: int = Field(ge=0)
    model_call_count: Literal[0]

    @model_validator(mode="after")
    def validate_accounting(self) -> FinQAShadowCapacityTrialV1:
        expected_config = f"w{self.worker_count}-c{self.caller_concurrency}"
        if self.config_id != expected_config:
            raise ValueError("E15 trial config id does not match dimensions")
        if self.trial_id != f"r{self.repetition_index}-{expected_config}":
            raise ValueError("E15 trial id does not match dimensions")
        if sum(self.outcome_counts.values()) != self.attempted_count:
            raise ValueError("E15 trial outcomes do not reconcile")
        if self.completed_count != sum(
            self.outcome_counts.get(outcome, 0) for outcome in _COMPLETED_OUTCOMES
        ):
            raise ValueError("E15 trial completed count does not reconcile")
        if self.queue_wait_ms.count != self.completed_count:
            raise ValueError("E15 queue latency samples do not reconcile")
        if self.end_to_end_latency_ms.count != self.completed_count:
            raise ValueError("E15 end-to-end samples do not reconcile")
        if self.workers_with_rss_samples > self.worker_count:
            raise ValueError("E15 RSS samples exceed configured workers")
        if (
            self.maximum_individual_worker_peak_rss_bytes
            > self.worker_pool_rss_upper_bound_bytes
        ):
            raise ValueError("E15 RSS upper bound is inconsistent")
        return self


class FinQAShadowCapacityConfigurationV1(_StrictFrozenModel):
    config_id: str = Field(pattern=r"^w(?:1|2|4)-c(?:1|4|8)$")
    worker_count: int = Field(ge=1, le=4)
    caller_concurrency: int = Field(ge=1, le=8)
    trial_count: int = Field(ge=1)
    attempted_count: int = Field(ge=1)
    failure_count: int = Field(ge=0)
    throughput_min_requests_per_second: float = Field(gt=0)
    throughput_median_requests_per_second: float = Field(gt=0)
    throughput_max_requests_per_second: float = Field(gt=0)
    throughput_relative_spread: float = Field(ge=0)
    median_queue_wait_p95_ms: float = Field(ge=0)
    median_end_to_end_p95_ms: float = Field(ge=0)
    maximum_end_to_end_p95_ms: float = Field(ge=0)
    maximum_worker_pool_rss_upper_bound_bytes: int = Field(ge=0)
    minimum_active_worker_high_watermark: int = Field(ge=0)
    maximum_queue_high_watermark: int = Field(ge=0)


class FinQAShadowCapacityComparisonResultV1(_StrictFrozenModel):
    comparison_id: str
    baseline_config_id: str
    candidate_config_id: str
    median_throughput_speedup: float = Field(gt=0)
    worker_scaling_efficiency: float = Field(gt=0)


class FinQAShadowCapacityRecommendationV1(_StrictFrozenModel):
    scope: Literal["LOCAL_UNLABELED_SHADOW_ONLY"]
    config_id: str
    worker_count: int = Field(ge=1)
    caller_concurrency: int = Field(ge=1)
    selection_rule: Literal[
        "highest_median_throughput_among_failure_free_latency_and_rss_eligible_configs_tie_lower_rss"
    ]


class FinQAShadowCapacitySummaryV1(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_shadow_capacity_summary_v1"
    ] = CAPACITY_SUMMARY_VERSION
    preparation: FinQAShadowPreparationSummaryV1
    schedule_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    trial_aggregates: tuple[FinQAShadowCapacityTrialV1, ...]
    configuration_aggregates: tuple[FinQAShadowCapacityConfigurationV1, ...]
    scaling_comparisons: tuple[FinQAShadowCapacityComparisonResultV1, ...]
    local_recommendation: FinQAShadowCapacityRecommendationV1
    all_primary_results_e8: bool
    per_request_rows_persisted: Literal[0]
    quality_labels_consumed: Literal[0]


def capacity_trial_schedule_v1(
    protocol: FinQAShadowCapacityProtocolV1,
) -> tuple[FinQAShadowCapacityScheduleItemV1, ...]:
    base = [
        (worker_count, caller_concurrency)
        for worker_count in protocol.matrix.worker_counts
        for caller_concurrency in protocol.matrix.caller_concurrency
    ]
    orders = (base, list(reversed(base)), base[3:] + base[:3])
    items: list[FinQAShadowCapacityScheduleItemV1] = []
    for repetition_index, order in enumerate(orders):
        for worker_count, caller_concurrency in order:
            items.append(
                FinQAShadowCapacityScheduleItemV1(
                    schedule_ordinal=len(items) + 1,
                    repetition_index=repetition_index,
                    config_id=f"w{worker_count}-c{caller_concurrency}",
                    worker_count=worker_count,
                    caller_concurrency=caller_concurrency,
                )
            )
    if len(items) != protocol.gates.required_trial_count:
        raise ValueError("E15 schedule does not match required trial count")
    return tuple(items)


def capacity_schedule_sha256_v1(
    schedule: tuple[FinQAShadowCapacityScheduleItemV1, ...],
) -> str:
    payload = [item.model_dump(mode="json") for item in schedule]
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def prepare_finqa_shadow_capacity_workload_v1(
    cases: list[FinQACase],
    *,
    e13_protocol: FinQAShadowWorkerReplayProtocolV1,
    guard: RetrievedContentGuard | None = None,
    primary_runtime: FinQADescriptorShadowRuntimeV1 | None = None,
) -> PreparedFinQAShadowCapacityWorkloadV1:
    selected = select_shadow_replay_cases_v1(cases, protocol=e13_protocol)
    content_guard = guard or RetrievedContentGuard()
    runtime = primary_runtime or FinQADescriptorShadowRuntimeV1()
    preparation_failures = 0
    primary_failures = 0
    prepared_count = 0
    all_primary_e8 = True
    requests: list[FinQAShadowCapacityRequestV1] = []
    for case in selected:
        try:
            prepared = prepare_finqa_shadow_replay_case_v1(
                case,
                guard=content_guard,
                selected_unit_limit=e13_protocol.dataset.max_selected_units_per_case,
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
        requests.append(
            FinQAShadowCapacityRequestV1(primary=primary, prepared=prepared)
        )
    return PreparedFinQAShadowCapacityWorkloadV1(
        preparation=FinQAShadowPreparationSummaryV1(
            selected_case_count=len(selected),
            prepared_case_count=prepared_count,
            preparation_failure_count=preparation_failures,
            primary_failure_count=primary_failures,
        ),
        requests=tuple(requests),
        all_primary_results_e8=all_primary_e8,
    )


def _distribution(values: list[float]) -> FinQAAggregateDistributionV1:
    if not values:
        return FinQAAggregateDistributionV1(count=0)
    return FinQAAggregateDistributionV1(
        count=len(values),
        p50=nearest_rank_percentile(values, 0.50),
        p95=nearest_rank_percentile(values, 0.95),
        maximum=max(values),
    )


def run_finqa_shadow_capacity_trial_v1(
    workload: PreparedFinQAShadowCapacityWorkloadV1,
    *,
    schedule_item: FinQAShadowCapacityScheduleItemV1,
    protocol: FinQAShadowCapacityProtocolV1,
    e13_protocol: FinQAShadowWorkerReplayProtocolV1,
    evidence_dir: Path,
) -> FinQAShadowCapacityTrialV1:
    pool = FinQABoundedShadowWorkerPoolV1(
        evidence_dir=evidence_dir,
        config=FinQAShadowWorkerPoolConfigV1(
            worker_count=schedule_item.worker_count,
            queue_capacity=protocol.matrix.queue_capacity,
            admission_timeout_seconds=protocol.matrix.admission_timeout_seconds,
            response_deadline_seconds=protocol.matrix.response_deadline_seconds,
            shutdown_grace_seconds=protocol.matrix.shutdown_grace_seconds,
        ),
        worker_config=FinQAShadowWorkerConfigV1.from_protocol(e13_protocol),
    )
    if not pool.start():
        raise RuntimeError(
            f"E15 pool failed to start for {schedule_item.config_id}"
        )
    observations = []
    started = time.perf_counter()
    try:
        with ThreadPoolExecutor(
            max_workers=schedule_item.caller_concurrency,
            thread_name_prefix="finqa-e15-capacity-caller",
        ) as executor:
            futures = [
                executor.submit(
                    pool.observe,
                    primary=request.primary,
                    question=request.prepared.question,
                    skeleton=request.prepared.skeleton,
                    catalog=request.prepared.catalog,
                )
                for request in workload.requests
            ]
            observations = [future.result() for future in futures]
        elapsed_ms = max(0.001, (time.perf_counter() - started) * 1_000)
        metrics = pool.metrics()
    finally:
        close_completed = pool.close()
    closed = pool.diagnostics()
    outcomes = Counter(item.outcome for item in observations)
    completed = [item for item in observations if item.outcome in _COMPLETED_OUTCOMES]
    worker_rss: dict[int, int] = {}
    for item in completed:
        if item.worker_slot is not None and item.worker_peak_rss_bytes is not None:
            worker_rss[item.worker_slot] = max(
                worker_rss.get(item.worker_slot, 0),
                item.worker_peak_rss_bytes,
            )
    return FinQAShadowCapacityTrialV1(
        trial_id=f"r{schedule_item.repetition_index}-{schedule_item.config_id}",
        **schedule_item.model_dump(mode="python", exclude={"config_id"}),
        config_id=schedule_item.config_id,
        attempted_count=len(observations),
        admitted_count=metrics.admitted_count,
        executed_count=metrics.executed_count,
        completed_count=len(completed),
        outcome_counts=dict(sorted(outcomes.items())),
        backpressure_rejected_count=metrics.backpressure_rejected_count,
        deadline_exceeded_count=metrics.deadline_exceeded_count,
        worker_error_count=sum(
            outcomes.get(outcome, 0) for outcome in _WORKER_ERROR_OUTCOMES
        ),
        worker_restart_count=metrics.worker_restart_count,
        late_result_discarded_count=metrics.late_result_discarded_count,
        cancelled_before_execution_count=metrics.cancelled_before_execution_count,
        active_worker_high_watermark=metrics.active_worker_high_watermark,
        queue_high_watermark=metrics.queue_high_watermark,
        queue_wait_ms=_distribution([item.queue_wait_ms for item in completed]),
        end_to_end_latency_ms=_distribution(
            [item.end_to_end_latency_ms for item in completed]
        ),
        elapsed_ms=elapsed_ms,
        throughput_requests_per_second=len(observations) / (elapsed_ms / 1_000),
        workers_with_rss_samples=len(worker_rss),
        maximum_individual_worker_peak_rss_bytes=max(worker_rss.values(), default=0),
        worker_pool_rss_upper_bound_bytes=sum(worker_rss.values()),
        close_completed=close_completed,
        residual_dispatcher_count=closed.dispatcher_alive_count,
        residual_worker_pid_count=sum(pid is not None for pid in closed.worker_pids),
        model_call_count=0,
    )


def _median(values: list[float]) -> float:
    return float(statistics.median(values))


def aggregate_finqa_shadow_capacity_trials_v1(
    preparation: FinQAShadowPreparationSummaryV1,
    trials: list[FinQAShadowCapacityTrialV1],
    *,
    protocol: FinQAShadowCapacityProtocolV1,
    all_primary_results_e8: bool,
) -> FinQAShadowCapacitySummaryV1:
    schedule = capacity_trial_schedule_v1(protocol)
    actual_schedule = tuple(
        (
            item.schedule_ordinal,
            item.repetition_index,
            item.config_id,
            item.worker_count,
            item.caller_concurrency,
        )
        for item in trials
    )
    expected_schedule = tuple(
        (
            item.schedule_ordinal,
            item.repetition_index,
            item.config_id,
            item.worker_count,
            item.caller_concurrency,
        )
        for item in schedule
    )
    if actual_schedule != expected_schedule:
        raise ValueError("E15 trial rows do not match the frozen schedule")

    grouped: dict[str, list[FinQAShadowCapacityTrialV1]] = defaultdict(list)
    for trial in trials:
        grouped[trial.config_id].append(trial)
    configurations: list[FinQAShadowCapacityConfigurationV1] = []
    for worker_count in protocol.matrix.worker_counts:
        for caller_concurrency in protocol.matrix.caller_concurrency:
            config_id = f"w{worker_count}-c{caller_concurrency}"
            rows = grouped[config_id]
            if len(rows) != protocol.matrix.repetitions:
                raise ValueError(f"E15 configuration {config_id} lacks repetitions")
            throughput = [item.throughput_requests_per_second for item in rows]
            median_throughput = _median(throughput)
            queue_p95 = [float(item.queue_wait_ms.p95) for item in rows]
            end_to_end_p95 = [
                float(item.end_to_end_latency_ms.p95) for item in rows
            ]
            configurations.append(
                FinQAShadowCapacityConfigurationV1(
                    config_id=config_id,
                    worker_count=worker_count,
                    caller_concurrency=caller_concurrency,
                    trial_count=len(rows),
                    attempted_count=sum(item.attempted_count for item in rows),
                    failure_count=sum(
                        item.attempted_count - item.completed_count for item in rows
                    ),
                    throughput_min_requests_per_second=min(throughput),
                    throughput_median_requests_per_second=median_throughput,
                    throughput_max_requests_per_second=max(throughput),
                    throughput_relative_spread=(
                        (max(throughput) - min(throughput)) / median_throughput
                    ),
                    median_queue_wait_p95_ms=_median(queue_p95),
                    median_end_to_end_p95_ms=_median(end_to_end_p95),
                    maximum_end_to_end_p95_ms=max(end_to_end_p95),
                    maximum_worker_pool_rss_upper_bound_bytes=max(
                        item.worker_pool_rss_upper_bound_bytes for item in rows
                    ),
                    minimum_active_worker_high_watermark=min(
                        item.active_worker_high_watermark for item in rows
                    ),
                    maximum_queue_high_watermark=max(
                        item.queue_high_watermark for item in rows
                    ),
                )
            )
    by_config = {item.config_id: item for item in configurations}
    comparisons: list[FinQAShadowCapacityComparisonResultV1] = []
    for frozen in protocol.gates.comparisons:
        baseline_id = (
            f"w{frozen.baseline_worker_count}-c{frozen.caller_concurrency}"
        )
        candidate_id = (
            f"w{frozen.candidate_worker_count}-c{frozen.caller_concurrency}"
        )
        speedup = (
            by_config[candidate_id].throughput_median_requests_per_second
            / by_config[baseline_id].throughput_median_requests_per_second
        )
        worker_ratio = (
            frozen.candidate_worker_count / frozen.baseline_worker_count
        )
        comparisons.append(
            FinQAShadowCapacityComparisonResultV1(
                comparison_id=frozen.comparison_id,
                baseline_config_id=baseline_id,
                candidate_config_id=candidate_id,
                median_throughput_speedup=speedup,
                worker_scaling_efficiency=speedup / worker_ratio,
            )
        )
    eligible = [
        item
        for item in configurations
        if item.failure_count == 0
        and item.maximum_end_to_end_p95_ms
        <= protocol.gates.max_end_to_end_latency_p95_ms
        and item.maximum_worker_pool_rss_upper_bound_bytes
        <= protocol.gates.max_four_worker_rss_upper_bound_bytes
    ]
    if not eligible:
        raise ValueError("E15 has no locally eligible capacity configuration")
    recommended = sorted(
        eligible,
        key=lambda item: (
            -item.throughput_median_requests_per_second,
            item.maximum_worker_pool_rss_upper_bound_bytes,
            item.worker_count,
            item.caller_concurrency,
        ),
    )[0]
    return FinQAShadowCapacitySummaryV1(
        preparation=preparation,
        schedule_sha256=capacity_schedule_sha256_v1(schedule),
        trial_aggregates=tuple(trials),
        configuration_aggregates=tuple(configurations),
        scaling_comparisons=tuple(comparisons),
        local_recommendation=FinQAShadowCapacityRecommendationV1(
            scope="LOCAL_UNLABELED_SHADOW_ONLY",
            config_id=recommended.config_id,
            worker_count=recommended.worker_count,
            caller_concurrency=recommended.caller_concurrency,
            selection_rule=(
                "highest_median_throughput_among_failure_free_latency_and_rss_eligible_configs_tie_lower_rss"
            ),
        ),
        all_primary_results_e8=all_primary_results_e8,
        per_request_rows_persisted=0,
        quality_labels_consumed=0,
    )


def run_finqa_shadow_capacity_experiment_v1(
    cases: list[FinQACase],
    *,
    protocol: FinQAShadowCapacityProtocolV1,
    e13_protocol: FinQAShadowWorkerReplayProtocolV1,
    evidence_dir: Path,
) -> FinQAShadowCapacitySummaryV1:
    workload = prepare_finqa_shadow_capacity_workload_v1(
        cases,
        e13_protocol=e13_protocol,
    )
    trials = [
        run_finqa_shadow_capacity_trial_v1(
            workload,
            schedule_item=item,
            protocol=protocol,
            e13_protocol=e13_protocol,
            evidence_dir=evidence_dir,
        )
        for item in capacity_trial_schedule_v1(protocol)
    ]
    return aggregate_finqa_shadow_capacity_trials_v1(
        workload.preparation,
        trials,
        protocol=protocol,
        all_primary_results_e8=workload.all_primary_results_e8,
    )


def evaluate_finqa_shadow_capacity_gates_v1(
    summary: FinQAShadowCapacitySummaryV1,
    *,
    protocol: FinQAShadowCapacityProtocolV1,
) -> dict[str, bool]:
    gates = protocol.gates
    trials = summary.trial_aggregates
    configurations = summary.configuration_aggregates
    comparisons = {
        item.comparison_id: item for item in summary.scaling_comparisons
    }
    comparison_gates = {
        f"{item.comparison_id}_speedup": (
            comparisons[item.comparison_id].median_throughput_speedup
            >= item.min_median_throughput_speedup
        )
        for item in gates.comparisons
    }
    comparison_gates.update(
        {
            f"{item.comparison_id}_efficiency": (
                comparisons[item.comparison_id].worker_scaling_efficiency
                >= item.min_worker_scaling_efficiency
            )
            for item in gates.comparisons
        }
    )
    return {
        "preparation_success_rate": (
            summary.preparation.prepared_case_count
            / summary.preparation.selected_case_count
            >= gates.min_preparation_success_rate
        ),
        "required_trial_count": len(trials) == gates.required_trial_count,
        "trial_completion_rate": all(
            trial.completed_count / trial.attempted_count
            >= gates.min_trial_completion_rate
            for trial in trials
        ),
        "backpressure_rejections": sum(
            item.backpressure_rejected_count for item in trials
        )
        <= gates.max_backpressure_rejections,
        "deadline_exceeded": sum(
            item.deadline_exceeded_count for item in trials
        )
        <= gates.max_deadline_exceeded,
        "worker_errors": sum(item.worker_error_count for item in trials)
        <= gates.max_worker_errors,
        "worker_restarts": sum(item.worker_restart_count for item in trials)
        <= gates.max_worker_restarts,
        "expected_active_worker_high_watermark": all(
            item.active_worker_high_watermark
            == min(item.worker_count, item.caller_concurrency)
            for item in trials
        ),
        "queue_bound": all(
            item.queue_high_watermark <= protocol.matrix.queue_capacity
            for item in trials
        ),
        "end_to_end_latency_p95": all(
            item.end_to_end_latency_ms.p95 is not None
            and item.end_to_end_latency_ms.p95
            <= gates.max_end_to_end_latency_p95_ms
            for item in trials
        ),
        "four_worker_rss_upper_bound": all(
            item.worker_count != 4
            or item.worker_pool_rss_upper_bound_bytes
            <= gates.max_four_worker_rss_upper_bound_bytes
            for item in trials
        ),
        "throughput_relative_spread": all(
            item.throughput_relative_spread
            <= gates.max_throughput_relative_spread
            for item in configurations
        ),
        "no_residual_workers_after_each_trial": all(
            item.close_completed
            and item.residual_dispatcher_count == 0
            and item.residual_worker_pid_count == 0
            for item in trials
        ),
        "all_primary_results_e8": summary.all_primary_results_e8,
        "zero_model_calls": all(item.model_call_count == 0 for item in trials),
        "aggregate_only_output": summary.per_request_rows_persisted == 0,
        "no_quality_labels_or_scores": summary.quality_labels_consumed == 0,
        **comparison_gates,
    }


__all__ = [
    "FinQAShadowCapacityConfigurationV1",
    "FinQAShadowCapacityScheduleItemV1",
    "FinQAShadowCapacitySummaryV1",
    "FinQAShadowCapacityTrialV1",
    "PreparedFinQAShadowCapacityWorkloadV1",
    "aggregate_finqa_shadow_capacity_trials_v1",
    "capacity_schedule_sha256_v1",
    "capacity_trial_schedule_v1",
    "evaluate_finqa_shadow_capacity_gates_v1",
    "prepare_finqa_shadow_capacity_workload_v1",
    "run_finqa_shadow_capacity_experiment_v1",
    "run_finqa_shadow_capacity_trial_v1",
]
