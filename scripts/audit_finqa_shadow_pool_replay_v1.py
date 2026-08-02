from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event

from app.external_datasets.finqa import DEFAULT_SOURCE_ROOT
from app.external_datasets.finqa_descriptor_shadow_v1 import (
    FinQADescriptorShadowRuntimeV1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeCandidateDescriptorV3,
    RetrievableSafeDescriptorCatalogV3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)
from app.external_datasets.finqa_shadow_pool_protocol_v1 import (
    load_shadow_pool_replay_protocol_v1,
)
from app.external_datasets.finqa_shadow_pool_replay_v1 import (
    evaluate_shadow_pool_replay_gates_v1,
    run_finqa_shadow_pool_replay_v1,
)
from app.external_datasets.finqa_shadow_pool_v1 import (
    FinQABoundedShadowWorkerPoolV1,
    FinQAShadowWorkerPoolConfigV1,
)
from app.external_datasets.finqa_shadow_replay_v1 import (
    load_finqa_shadow_replay_train_v1,
)
from app.external_datasets.finqa_shadow_worker_protocol_v1 import (
    load_shadow_worker_replay_protocol_v1,
)
from app.external_datasets.finqa_shadow_worker_v1 import (
    FinQAIsolatedShadowObservationV1,
    FinQAShadowWorkerConfigV1,
    FinQAShadowWorkerDiagnosticsV1,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/external_datasets/evidence"
DEFAULT_PROTOCOL = EVIDENCE / "finqa_shadow_pool_replay_protocol_v1.json"
DEFAULT_OUTPUT = EVIDENCE / "finqa_shadow_pool_replay_public_v1.json"
E13_PROTOCOL = EVIDENCE / "finqa_shadow_worker_replay_protocol_v1.json"
E13_PUBLIC = EVIDENCE / "finqa_shadow_worker_replay_public_v1.json"
IMPLEMENTATION_PATHS = (
    "app/external_datasets/finqa_shadow_pool_protocol_v1.py",
    "app/external_datasets/finqa_shadow_pool_v1.py",
    "app/external_datasets/finqa_shadow_pool_replay_v1.py",
    "scripts/audit_finqa_shadow_pool_replay_v1.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")


def _fault_inputs():
    skeleton = SemanticProgramSkeletonV2.model_validate(
        {
            "roles": [
                {
                    "role_id": "role-01",
                    "semantic_role": "comparison_left",
                    "period_role": "none",
                }
            ],
            "steps": [
                {
                    "step_id": "step-01",
                    "operation": "SUB",
                    "arguments": [
                        {"role_id": "role-01"},
                        {"constant_id": "const_100"},
                    ],
                }
            ],
            "output_step_id": "step-01",
        }
    )
    descriptor = RetrievableSafeCandidateDescriptorV3(
        descriptor_id="desc-0000000000000001",
        metric="operating metric",
        row_header="operating metric",
        column_header="current period",
        local_context_hint="annual operating result",
        topic_hint="company operating performance",
        periods=(),
        source_kind="table_cell",
        candidate_count=1,
    )
    payload = {
        "catalog_version": "finqa_safe_descriptor_catalog_v3",
        "source_candidate_count": 1,
        "represented_candidate_count": 1,
        "quarantined_candidate_count": 0,
        "descriptor_count": 1,
        "descriptors": [descriptor.model_dump(mode="json")],
    }
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    catalog = RetrievableSafeDescriptorCatalogV3(
        **payload,
        catalog_sha256=hashlib.sha256(canonical).hexdigest(),
    )
    question = "Which operating metric changed?"
    primary = FinQADescriptorShadowRuntimeV1().select_primary(
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )
    return primary, question, skeleton, catalog


class _BlockingWorker:
    def __init__(self, started: Event, release: Event) -> None:
        self.started = started
        self.release = release

    def start(self) -> bool:
        return True

    def observe(self, **_: object) -> FinQAIsolatedShadowObservationV1:
        self.started.set()
        if not self.release.wait(timeout=2):
            raise TimeoutError("E14 fault probe did not release worker")
        return FinQAIsolatedShadowObservationV1(
            outcome="MATCH",
            role_count=1,
            changed_role_count=0,
            common_descriptor_count_at_4=1,
            latency_ms=1,
            worker_peak_rss_bytes=10_000,
            worker_restarted=False,
        )

    def diagnostics(self) -> FinQAShadowWorkerDiagnosticsV1:
        return FinQAShadowWorkerDiagnosticsV1(None, None, None, 0)

    def close(self) -> None:
        return None


class _OutcomeWorker:
    def __init__(self, barrier: Barrier, outcome: str) -> None:
        self.barrier = barrier
        self.outcome = outcome

    def start(self) -> bool:
        return True

    def observe(self, **_: object) -> FinQAIsolatedShadowObservationV1:
        self.barrier.wait(timeout=2)
        return FinQAIsolatedShadowObservationV1(
            outcome=self.outcome,
            role_count=1,
            changed_role_count=0,
            common_descriptor_count_at_4=1 if self.outcome == "MATCH" else 0,
            latency_ms=1,
            worker_peak_rss_bytes=10_000,
            worker_restarted=self.outcome == "WORKER_CRASH",
        )

    def diagnostics(self) -> FinQAShadowWorkerDiagnosticsV1:
        return FinQAShadowWorkerDiagnosticsV1(
            None,
            None,
            None,
            1 if self.outcome == "WORKER_CRASH" else 0,
        )

    def close(self) -> None:
        return None


def _wait_for_metric(pool, attribute: str, value: int) -> None:
    deadline = time.perf_counter() + 1
    while time.perf_counter() < deadline:
        if getattr(pool.metrics(), attribute) >= value:
            return
        time.sleep(0.005)
    raise RuntimeError(f"E14 fault probe did not observe {attribute}={value}")


def _fault_injection() -> dict[str, bool]:
    primary, question, skeleton, catalog = _fault_inputs()
    primary_before = (
        primary.input_binding_sha256,
        primary.result.retriever_version,
        primary.result.generation_calls,
        primary.result.selections.model_dump_json(),
    )

    saturation_started = Event()
    saturation_release = Event()
    saturation_worker = _BlockingWorker(
        saturation_started,
        saturation_release,
    )
    saturation_pool = FinQABoundedShadowWorkerPoolV1(
        evidence_dir=EVIDENCE,
        config=FinQAShadowWorkerPoolConfigV1(
            worker_count=1,
            queue_capacity=1,
            admission_timeout_seconds=0.01,
            response_deadline_seconds=1,
            shutdown_grace_seconds=2,
        ),
        worker_factory=lambda _index: saturation_worker,
    )
    saturation_pool.start()
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            saturation_pool.observe,
            primary=primary,
            question=question,
            skeleton=skeleton,
            catalog=catalog,
        )
        saturation_started.wait(timeout=1)
        second = executor.submit(
            saturation_pool.observe,
            primary=primary,
            question=question,
            skeleton=skeleton,
            catalog=catalog,
        )
        _wait_for_metric(saturation_pool, "admitted_count", 2)
        rejected = saturation_pool.observe(
            primary=primary,
            question=question,
            skeleton=skeleton,
            catalog=catalog,
        )
        saturation_release.set()
        first_result = first.result(timeout=2)
        second_result = second.result(timeout=2)
    saturation_metrics = saturation_pool.metrics()
    saturation_pool.close()

    deadline_started = Event()
    deadline_release = Event()
    deadline_worker = _BlockingWorker(deadline_started, deadline_release)
    deadline_pool = FinQABoundedShadowWorkerPoolV1(
        evidence_dir=EVIDENCE,
        config=FinQAShadowWorkerPoolConfigV1(
            worker_count=1,
            queue_capacity=1,
            admission_timeout_seconds=0.01,
            response_deadline_seconds=0.05,
            shutdown_grace_seconds=2,
        ),
        worker_factory=lambda _index: deadline_worker,
    )
    deadline_pool.start()
    with ThreadPoolExecutor(max_workers=2) as executor:
        first_deadline = executor.submit(
            deadline_pool.observe,
            primary=primary,
            question=question,
            skeleton=skeleton,
            catalog=catalog,
        )
        deadline_started.wait(timeout=1)
        second_deadline = executor.submit(
            deadline_pool.observe,
            primary=primary,
            question=question,
            skeleton=skeleton,
            catalog=catalog,
        )
        _wait_for_metric(deadline_pool, "admitted_count", 2)
        deadline_outcomes = {
            first_deadline.result(timeout=1).outcome,
            second_deadline.result(timeout=1).outcome,
        }
        deadline_release.set()
    _wait_for_metric(deadline_pool, "late_result_discarded_count", 1)
    _wait_for_metric(deadline_pool, "cancelled_before_execution_count", 1)
    deadline_metrics = deadline_pool.metrics()
    deadline_pool.close()

    fault_barrier = Barrier(2)
    fault_workers = [
        _OutcomeWorker(fault_barrier, "WORKER_CRASH"),
        _OutcomeWorker(fault_barrier, "MATCH"),
    ]
    fault_pool = FinQABoundedShadowWorkerPoolV1(
        evidence_dir=EVIDENCE,
        config=FinQAShadowWorkerPoolConfigV1(
            worker_count=2,
            queue_capacity=2,
            admission_timeout_seconds=0.1,
            response_deadline_seconds=1,
            shutdown_grace_seconds=2,
        ),
        worker_factory=lambda index: fault_workers[index],
    )
    fault_pool.start()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                fault_pool.observe,
                primary=primary,
                question=question,
                skeleton=skeleton,
                catalog=catalog,
            )
            for _ in range(2)
        ]
        fault_outcomes = {future.result(timeout=2).outcome for future in futures}
    fault_metrics = fault_pool.metrics()
    fault_pool.close()

    primary_after = (
        primary.input_binding_sha256,
        primary.result.retriever_version,
        primary.result.generation_calls,
        primary.result.selections.model_dump_json(),
    )
    return {
        "queue_bound_enforced": saturation_metrics.queue_high_watermark == 1,
        "overload_rejected_without_primary_mutation": (
            rejected.outcome == "BACKPRESSURE_REJECTED"
            and first_result.outcome == "MATCH"
            and second_result.outcome == "MATCH"
            and primary_after == primary_before
        ),
        "queued_deadline_expires_before_execution": (
            deadline_outcomes == {"DEADLINE_EXCEEDED"}
            and deadline_metrics.executed_count == 1
            and deadline_metrics.cancelled_before_execution_count == 1
        ),
        "late_result_discarded": (
            deadline_metrics.late_result_discarded_count == 1
        ),
        "worker_fault_isolated_to_slot": (
            fault_outcomes == {"MATCH", "WORKER_CRASH"}
            and fault_metrics.executed_outcome_counts
            == {"MATCH": 1, "WORKER_CRASH": 1}
        ),
    }


def build_public_evidence() -> dict[str, object]:
    e14_protocol, e14_protocol_sha256 = load_shadow_pool_replay_protocol_v1(
        DEFAULT_PROTOCOL
    )
    e13_protocol, e13_protocol_sha256 = load_shadow_worker_replay_protocol_v1(
        E13_PROTOCOL
    )
    source_evidence_matches = (
        e14_protocol.source_e13_protocol_sha256 == e13_protocol_sha256
        and e14_protocol.source_e13_public_evidence_sha256 == _sha256(E13_PUBLIC)
    )
    cases = load_finqa_shadow_replay_train_v1(
        DEFAULT_SOURCE_ROOT / "dataset/train.json",
        expected_sha256=e13_protocol.dataset.split_sha256,
    )
    pool = FinQABoundedShadowWorkerPoolV1(
        evidence_dir=EVIDENCE,
        config=FinQAShadowWorkerPoolConfigV1(
            worker_count=e14_protocol.pool.worker_count,
            queue_capacity=e14_protocol.pool.queue_capacity,
            admission_timeout_seconds=(
                e14_protocol.pool.admission_timeout_seconds
            ),
            response_deadline_seconds=e14_protocol.pool.response_deadline_seconds,
            shutdown_grace_seconds=e14_protocol.pool.shutdown_grace_seconds,
        ),
        worker_config=FinQAShadowWorkerConfigV1.from_protocol(e13_protocol),
    )
    if not pool.start():
        raise RuntimeError("E14 real worker pool failed to start")
    try:
        summary = run_finqa_shadow_pool_replay_v1(
            cases,
            e13_protocol=e13_protocol,
            e14_protocol=e14_protocol,
            pool=pool,
        )
    finally:
        close_completed = pool.close()
    closed_diagnostics = pool.diagnostics()
    primary, question, skeleton, catalog = _fault_inputs()
    closed_rejection = pool.observe(
        primary=primary,
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )
    fault_gates = {
        **_fault_injection(),
        "close_rejects_new_work": closed_rejection.outcome == "POOL_CLOSED",
        "no_residual_workers_after_close": (
            close_completed
            and closed_diagnostics.dispatcher_alive_count == 0
            and all(pid is None for pid in closed_diagnostics.worker_pids)
        ),
    }
    replay_gates = evaluate_shadow_pool_replay_gates_v1(
        summary,
        protocol=e14_protocol,
    )
    gate_checks = {
        "source_e13_evidence_hashes": source_evidence_matches,
        **replay_gates,
        **fault_gates,
    }
    if not all(gate_checks.values()):
        failed = sorted(name for name, passed in gate_checks.items() if not passed)
        raise RuntimeError(f"E14 bounded pool replay gates failed: {failed}")

    summary_payload = summary.model_dump(mode="json")
    summary_payload.pop("schema_version")
    return {
        "schema_version": "finqa_shadow_pool_replay_public_v1",
        "protocol_id": e14_protocol.protocol_id,
        "protocol_sha256": e14_protocol_sha256,
        "claim": e14_protocol.claim_label,
        "decision": "E14_BOUNDED_POOL_REPLAY_PASSED_SHADOW_REMAINS_DEFAULT_OFF",
        **summary_payload,
        "fault_injection": fault_gates,
        "gate_checks": gate_checks,
        "implementation_sha256": {
            relative: _sha256(ROOT / relative)
            for relative in IMPLEMENTATION_PATHS
        },
        "serving_champion": e14_protocol.serving_champion,
        "challenger_status": e14_protocol.challenger_status,
        "internal_cohort_status": e14_protocol.internal_cohort_status,
        "frozen_test_status": e14_protocol.frozen_test_status,
        "non_claims": list(e14_protocol.non_claims),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    content = _canonical_bytes(build_public_evidence())
    output = args.output.resolve()
    if output.exists() and output.read_bytes() != content:
        raise RuntimeError("refusing to overwrite different E14 public evidence")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    print(json.dumps(json.loads(content), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
