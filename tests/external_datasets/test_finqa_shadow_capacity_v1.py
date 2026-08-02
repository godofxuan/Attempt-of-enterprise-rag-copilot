from __future__ import annotations

from pathlib import Path

import pytest

from app.external_datasets.finqa_shadow_capacity_protocol_v1 import (
    load_shadow_capacity_protocol_v1,
)
from app.external_datasets.finqa_shadow_capacity_v1 import (
    FinQAShadowCapacityScheduleItemV1,
    FinQAShadowCapacityTrialV1,
    aggregate_finqa_shadow_capacity_trials_v1,
    capacity_schedule_sha256_v1,
    capacity_trial_schedule_v1,
    evaluate_finqa_shadow_capacity_gates_v1,
)
from app.external_datasets.finqa_shadow_replay_v1 import (
    FinQAAggregateDistributionV1,
    FinQAShadowPreparationSummaryV1,
)


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = (
    ROOT
    / "docs/external_datasets/evidence/finqa_shadow_capacity_protocol_v1.json"
)


def _throughput(worker_count: int, caller_concurrency: int) -> float:
    values = {
        (1, 1): 100.0,
        (1, 4): 100.0,
        (1, 8): 100.0,
        (2, 1): 100.0,
        (2, 4): 180.0,
        (2, 8): 180.0,
        (4, 1): 100.0,
        (4, 4): 280.0,
        (4, 8): 300.0,
    }
    return values[(worker_count, caller_concurrency)]


def _trial(item: FinQAShadowCapacityScheduleItemV1) -> FinQAShadowCapacityTrialV1:
    multiplier = (0.98, 1.0, 1.02)[item.repetition_index]
    throughput = _throughput(item.worker_count, item.caller_concurrency) * multiplier
    completed = 117
    return FinQAShadowCapacityTrialV1(
        trial_id=f"r{item.repetition_index}-{item.config_id}",
        **item.model_dump(mode="python", exclude={"config_id"}),
        config_id=item.config_id,
        attempted_count=completed,
        admitted_count=completed,
        executed_count=completed,
        completed_count=completed,
        outcome_counts={"DIVERGED": 43, "MATCH": 74},
        backpressure_rejected_count=0,
        deadline_exceeded_count=0,
        worker_error_count=0,
        worker_restart_count=0,
        late_result_discarded_count=0,
        cancelled_before_execution_count=0,
        active_worker_high_watermark=min(
            item.worker_count, item.caller_concurrency
        ),
        queue_high_watermark=min(4, item.caller_concurrency),
        queue_wait_ms=FinQAAggregateDistributionV1(
            count=completed,
            p50=1,
            p95=3,
            maximum=8,
        ),
        end_to_end_latency_ms=FinQAAggregateDistributionV1(
            count=completed,
            p50=5,
            p95=12,
            maximum=30,
        ),
        elapsed_ms=completed / throughput * 1_000,
        throughput_requests_per_second=throughput,
        workers_with_rss_samples=item.worker_count,
        maximum_individual_worker_peak_rss_bytes=90_000_000,
        worker_pool_rss_upper_bound_bytes=90_000_000 * item.worker_count,
        close_completed=True,
        residual_dispatcher_count=0,
        residual_worker_pid_count=0,
        model_call_count=0,
    )


def _passing_summary():
    protocol, _ = load_shadow_capacity_protocol_v1(PROTOCOL)
    schedule = capacity_trial_schedule_v1(protocol)
    summary = aggregate_finqa_shadow_capacity_trials_v1(
        FinQAShadowPreparationSummaryV1(
            selected_case_count=128,
            prepared_case_count=117,
            preparation_failure_count=11,
            primary_failure_count=0,
        ),
        [_trial(item) for item in schedule],
        protocol=protocol,
        all_primary_results_e8=True,
    )
    return protocol, schedule, summary


def test_e15_schedule_is_deterministic_and_counterbalanced() -> None:
    protocol, _ = load_shadow_capacity_protocol_v1(PROTOCOL)
    first = capacity_trial_schedule_v1(protocol)
    second = capacity_trial_schedule_v1(protocol)

    assert first == second
    assert len(first) == 27
    assert [item.config_id for item in first[:9]] == [
        "w1-c1",
        "w1-c4",
        "w1-c8",
        "w2-c1",
        "w2-c4",
        "w2-c8",
        "w4-c1",
        "w4-c4",
        "w4-c8",
    ]
    assert [item.config_id for item in first[9:18]] == [
        item.config_id for item in reversed(first[:9])
    ]
    assert [item.config_id for item in first[18:]] == [
        "w2-c1",
        "w2-c4",
        "w2-c8",
        "w4-c1",
        "w4-c4",
        "w4-c8",
        "w1-c1",
        "w1-c4",
        "w1-c8",
    ]
    assert capacity_schedule_sha256_v1(first) == capacity_schedule_sha256_v1(
        second
    )


def test_e15_aggregation_computes_scaling_and_passes_preregistered_gates() -> None:
    protocol, schedule, summary = _passing_summary()

    assert len(summary.trial_aggregates) == len(schedule) == 27
    assert len(summary.configuration_aggregates) == 9
    assert all(
        evaluate_finqa_shadow_capacity_gates_v1(
            summary,
            protocol=protocol,
        ).values()
    )
    comparisons = {
        item.comparison_id: item for item in summary.scaling_comparisons
    }
    assert comparisons[
        "workers_1_to_2_callers_4"
    ].median_throughput_speedup == pytest.approx(1.8)
    assert comparisons[
        "workers_1_to_4_callers_8"
    ].worker_scaling_efficiency == pytest.approx(0.75)
    assert summary.local_recommendation.config_id == "w4-c8"


def test_e15_aggregation_rejects_missing_or_reordered_trials() -> None:
    protocol, schedule, _ = _passing_summary()
    trials = [_trial(item) for item in schedule]
    trials[0], trials[1] = trials[1], trials[0]

    with pytest.raises(ValueError, match="frozen schedule"):
        aggregate_finqa_shadow_capacity_trials_v1(
            FinQAShadowPreparationSummaryV1(
                selected_case_count=128,
                prepared_case_count=117,
                preparation_failure_count=11,
                primary_failure_count=0,
            ),
            trials,
            protocol=protocol,
            all_primary_results_e8=True,
        )


def test_e15_summary_contains_no_per_request_or_quality_content() -> None:
    _, _, summary = _passing_summary()
    serialized = summary.model_dump_json()

    assert summary.per_request_rows_persisted == 0
    assert summary.quality_labels_consumed == 0
    for prohibited in (
        "question_text",
        "numeric_values",
        "case_ids",
        "company_ids",
        "descriptor_ids",
        "candidate_ids",
        "evidence_ids",
        "source_ids",
        "provenance",
        "ranked_scores",
        "per_request_latency",
        "per_request_outcome",
        "worker_slot_assignments",
    ):
        assert prohibited not in serialized
