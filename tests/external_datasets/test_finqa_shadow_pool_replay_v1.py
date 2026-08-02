from __future__ import annotations

from pathlib import Path

import pytest

from app.external_datasets.finqa_shadow_pool_protocol_v1 import (
    load_shadow_pool_replay_protocol_v1,
)
from app.external_datasets.finqa_shadow_pool_replay_v1 import (
    FinQAShadowPoolLoadSummaryV1,
    FinQAShadowPoolReplaySummaryV1,
    FinQAShadowPoolResourceSummaryV1,
    evaluate_shadow_pool_replay_gates_v1,
)
from app.external_datasets.finqa_shadow_replay_v1 import (
    FinQAAggregateDistributionV1,
    FinQAShadowPreparationSummaryV1,
)


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = (
    ROOT
    / "docs/external_datasets/evidence/finqa_shadow_pool_replay_protocol_v1.json"
)


def _passing_summary() -> FinQAShadowPoolReplaySummaryV1:
    return FinQAShadowPoolReplaySummaryV1(
        preparation=FinQAShadowPreparationSummaryV1(
            selected_case_count=128,
            prepared_case_count=117,
            preparation_failure_count=11,
            primary_failure_count=0,
        ),
        load=FinQAShadowPoolLoadSummaryV1(
            caller_concurrency=4,
            attempted_count=117,
            admitted_count=117,
            executed_count=117,
            completed_count=117,
            outcome_counts={"MATCH": 74, "DIVERGED": 43},
            role_count=252,
            changed_role_count=83,
            common_descriptor_count_at_4=940,
            backpressure_rejected_count=0,
            deadline_exceeded_count=0,
            pool_state_rejected_count=0,
            late_result_discarded_count=0,
            cancelled_before_execution_count=0,
            active_worker_high_watermark=2,
            queue_high_watermark=2,
            worker_restart_count=0,
            model_call_count=0,
            elapsed_ms=500,
            throughput_requests_per_second=234,
        ),
        queue_wait_ms=FinQAAggregateDistributionV1(
            count=117,
            p50=1,
            p95=4,
            maximum=8,
        ),
        end_to_end_latency_ms=FinQAAggregateDistributionV1(
            count=117,
            p50=8,
            p95=20,
            maximum=50,
        ),
        worker_pool_resources=FinQAShadowPoolResourceSummaryV1(
            configured_worker_count=2,
            workers_with_rss_samples=2,
            maximum_individual_worker_peak_rss_bytes=95_000_000,
            worker_pool_rss_upper_bound_bytes=190_000_000,
        ),
        all_primary_results_e8=True,
        per_request_rows_persisted=0,
        quality_labels_consumed=0,
    )


def test_pool_replay_summary_is_aggregate_only_and_passes_exact_gates() -> None:
    protocol, _ = load_shadow_pool_replay_protocol_v1(PROTOCOL)
    summary = _passing_summary()

    assert all(
        evaluate_shadow_pool_replay_gates_v1(
            summary,
            protocol=protocol,
        ).values()
    )
    serialized = summary.model_dump_json()
    for prohibited in (
        "case_id",
        "question_text",
        "descriptor_id",
        "worker_slot_assignments",
        "per_request_latency",
    ):
        assert prohibited not in serialized


def test_pool_replay_summary_rejects_cross_group_count_drift() -> None:
    payload = _passing_summary().model_dump(mode="json")
    payload["preparation"]["prepared_case_count"] = 116
    payload["preparation"]["preparation_failure_count"] = 12

    with pytest.raises(ValueError, match="preparation and load"):
        FinQAShadowPoolReplaySummaryV1.model_validate(payload)
