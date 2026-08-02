from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeCandidateDescriptorV3,
    RetrievableSafeDescriptorCatalogV3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)
from app.external_datasets.finqa_service_adapter_protocol_v1 import (
    load_finqa_service_adapter_protocol_v1,
)
from app.external_datasets.finqa_service_adapter_v1 import (
    FinQAEphemeralContextResolverV1,
    FinQAServiceAdapterErrorV1,
    FinQATypedServiceAdapterV1,
    FinQATypedServiceContextV1,
    FinQATypedServiceResolutionV1,
)
from app.external_datasets.finqa_shadow_worker_v1 import (
    FinQAIsolatedShadowObservationV1,
    FinQAIsolatedShadowWorkerV1,
)
from app.runtime.dark_observation import (
    DarkObservationConfig,
    DarkObservationRequest,
    DarkObservationService,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/external_datasets/evidence"
DEFAULT_PROTOCOL = EVIDENCE / "finqa_service_adapter_protocol_v1.json"
DEFAULT_OUTPUT = EVIDENCE / "finqa_service_adapter_public_v1.json"
IMPLEMENTATION_PATHS = (
    "app/external_datasets/finqa_service_adapter_protocol_v1.py",
    "app/external_datasets/finqa_service_adapter_v1.py",
    "scripts/audit_finqa_service_adapter_v1.py",
)
SOURCE_FILES = {
    "source_e16_protocol_sha256": "dark_observation_service_protocol_v1.json",
    "source_e16_public_evidence_sha256": "dark_observation_service_public_v1.json",
    "source_e13_protocol_sha256": "finqa_shadow_worker_replay_protocol_v1.json",
    "source_e13_public_evidence_sha256": "finqa_shadow_worker_replay_public_v1.json",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.resolve().read_bytes()).hexdigest()


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


def _skeleton() -> SemanticProgramSkeletonV2:
    return SemanticProgramSkeletonV2.model_validate(
        {
            "roles": [
                {
                    "role_id": "role-01",
                    "semantic_role": "comparison_left",
                    "period_role": "start",
                },
                {
                    "role_id": "role-02",
                    "semantic_role": "comparison_right",
                    "period_role": "end",
                },
            ],
            "steps": [
                {
                    "step_id": "step-01",
                    "operation": "SUB",
                    "arguments": [
                        {"role_id": "role-01"},
                        {"role_id": "role-02"},
                    ],
                }
            ],
            "output_step_id": "step-01",
        }
    )


def _catalog() -> RetrievableSafeDescriptorCatalogV3:
    descriptors = tuple(
        RetrievableSafeCandidateDescriptorV3(
            descriptor_id=f"desc-{index:016x}",
            metric=f"synthetic operating category {index}",
            row_header=f"synthetic operating category {index}",
            column_header="current reporting period",
            local_context_hint="synthetic annual operating result",
            topic_hint="synthetic company operating performance",
            periods=(),
            source_kind="table_cell",
            candidate_count=1,
        )
        for index in range(1, 6)
    )
    payload = {
        "catalog_version": "finqa_safe_descriptor_catalog_v3",
        "source_candidate_count": len(descriptors),
        "represented_candidate_count": len(descriptors),
        "quarantined_candidate_count": 0,
        "descriptor_count": len(descriptors),
        "descriptors": [item.model_dump(mode="json") for item in descriptors],
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    return RetrievableSafeDescriptorCatalogV3(
        **payload,
        catalog_sha256=digest,
    )


def _context(question: str) -> FinQATypedServiceContextV1:
    return FinQATypedServiceContextV1.build(
        question=question,
        skeleton=_skeleton(),
        catalog=_catalog(),
        skeleton_origin="ONLINE_RULES",
        catalog_origin="RETRIEVED_ADMITTED_EVIDENCE",
    )


def _request(request_id: str, question: str) -> DarkObservationRequest:
    return DarkObservationRequest(
        request_id=request_id,
        question=question,
        primary_mode="answered",
        primary_stop_reason="complete",
    )


class _StaticResolver:
    def __init__(self, resolution: FinQATypedServiceResolutionV1) -> None:
        self.resolution = resolution

    def resolve(self, request: DarkObservationRequest):
        return self.resolution


class _FailingResolver:
    def resolve(self, request: DarkObservationRequest):
        raise FinQAServiceAdapterErrorV1("injected_untrusted_code")


class _AuditWorker:
    def __init__(self, outcome: str = "MATCH", *, fail: bool = False) -> None:
        self.outcome = outcome
        self.fail = fail
        self.calls = 0

    def observe(self, *, primary, question, skeleton, catalog):
        self.calls += 1
        if self.fail:
            raise RuntimeError("injected worker failure")
        role_count = len(primary.result.selections.selections)
        changed = 0 if self.outcome == "MATCH" else 1
        return FinQAIsolatedShadowObservationV1(
            outcome=self.outcome,
            role_count=role_count,
            changed_role_count=changed,
            common_descriptor_count_at_4=max(0, role_count * 4 - changed),
            latency_ms=0.1,
            worker_restarted=False,
        )

    def close(self) -> None:
        return None


def _eligibility_matrix() -> dict[str, object]:
    question = "How did the synthetic operating metric change?"
    reasons = (
        "NOT_FINANCIAL_NUMERIC",
        "MISSING_TYPED_SKELETON",
        "MISSING_SAFE_CATALOG",
        "POLICY_DENIED",
        "UNSUPPORTED_TYPED_CONTRACT",
    )
    reason_counts: Counter[str] = Counter()
    ineligible_worker_calls = 0
    outcomes: Counter[str] = Counter()
    for index, reason in enumerate(reasons):
        worker = _AuditWorker()
        adapter = FinQATypedServiceAdapterV1(
            resolver=_StaticResolver(
                FinQATypedServiceResolutionV1.not_applicable(reason)
            ),
            worker=worker,
        )
        outcome = adapter.observe(
            _request(f"matrix-{index}", question),
            deadline_monotonic=time.perf_counter() + 1,
        )
        reason_counts.update(adapter.snapshot()["eligibility_reasons"])
        outcomes[outcome] += 1
        ineligible_worker_calls += worker.calls
        adapter.close()

    worker = _AuditWorker("MATCH")
    adapter = FinQATypedServiceAdapterV1(
        resolver=_StaticResolver(
            FinQATypedServiceResolutionV1.eligible(_context(question))
        ),
        worker=worker,
    )
    outcome = adapter.observe(
        _request("matrix-eligible", question),
        deadline_monotonic=time.perf_counter() + 1,
    )
    reason_counts.update(adapter.snapshot()["eligibility_reasons"])
    outcomes[outcome] += 1
    adapter.close()
    return {
        "reason_counts": dict(sorted(reason_counts.items())),
        "outcomes": dict(sorted(outcomes.items())),
        "ineligible_worker_calls": ineligible_worker_calls,
        "eligible_worker_calls": worker.calls,
    }


def _outcome_mapping() -> dict[str, int]:
    question = "How did the synthetic operating metric change?"
    mapped: Counter[str] = Counter()
    for worker_outcome in ("MATCH", "DIVERGED"):
        adapter = FinQATypedServiceAdapterV1(
            resolver=_StaticResolver(
                FinQATypedServiceResolutionV1.eligible(_context(question))
            ),
            worker=_AuditWorker(worker_outcome),
        )
        mapped[
            adapter.observe(
                _request(f"mapping-{worker_outcome.lower()}", question),
                deadline_monotonic=time.perf_counter() + 1,
            )
        ] += 1
        adapter.close()
    return dict(sorted(mapped.items()))


def _expect_failure(adapter, request, deadline: float) -> str:
    try:
        adapter.observe(request, deadline_monotonic=deadline)
    except FinQAServiceAdapterErrorV1 as error:
        return error.code
    raise RuntimeError("E17 injected failure did not fail closed")


def _fault_injection() -> dict[str, object]:
    question = "How did the synthetic operating metric change?"
    mismatch_worker = _AuditWorker()
    mismatch = FinQATypedServiceAdapterV1(
        resolver=_StaticResolver(
            FinQATypedServiceResolutionV1.eligible(_context(question))
        ),
        worker=mismatch_worker,
    )
    mismatch_code = _expect_failure(
        mismatch,
        _request("fault-mismatch", f"{question} altered"),
        time.perf_counter() + 1,
    )

    deadline_worker = _AuditWorker()
    deadline_adapter = FinQATypedServiceAdapterV1(
        resolver=_StaticResolver(
            FinQATypedServiceResolutionV1.eligible(_context(question))
        ),
        worker=deadline_worker,
    )
    deadline_code = _expect_failure(
        deadline_adapter,
        _request("fault-deadline", question),
        time.perf_counter() - 1,
    )

    resolver_worker = _AuditWorker()
    resolver_adapter = FinQATypedServiceAdapterV1(
        resolver=_FailingResolver(),
        worker=resolver_worker,
    )
    resolver_code = _expect_failure(
        resolver_adapter,
        _request("fault-resolver", question),
        time.perf_counter() + 1,
    )

    failing_worker = _AuditWorker(fail=True)
    worker_adapter = FinQATypedServiceAdapterV1(
        resolver=_StaticResolver(
            FinQATypedServiceResolutionV1.eligible(_context(question))
        ),
        worker=failing_worker,
    )
    worker_code = _expect_failure(
        worker_adapter,
        _request("fault-worker", question),
        time.perf_counter() + 1,
    )

    invalid_deadline_worker = _AuditWorker()
    invalid_deadline_adapter = FinQATypedServiceAdapterV1(
        resolver=_StaticResolver(
            FinQATypedServiceResolutionV1.eligible(_context(question))
        ),
        worker=invalid_deadline_worker,
    )
    invalid_deadline_code = _expect_failure(
        invalid_deadline_adapter,
        _request("fault-invalid-deadline", question),
        float("nan"),
    )

    closed_worker = _AuditWorker()
    closed_adapter = FinQATypedServiceAdapterV1(
        resolver=_StaticResolver(
            FinQATypedServiceResolutionV1.eligible(_context(question))
        ),
        worker=closed_worker,
    )
    closed_adapter.close()
    closed_code = _expect_failure(
        closed_adapter,
        _request("fault-closed", question),
        time.perf_counter() + 1,
    )
    return {
        "input_binding_mismatch": {
            "safe_code": mismatch_code,
            "worker_calls": mismatch_worker.calls,
        },
        "deadline_expired": {
            "safe_code": deadline_code,
            "worker_calls": deadline_worker.calls,
        },
        "resolver_error": {
            "safe_code": resolver_code,
            "worker_calls": resolver_worker.calls,
        },
        "worker_error": {
            "safe_code": worker_code,
            "worker_calls": failing_worker.calls,
        },
        "invalid_deadline": {
            "safe_code": invalid_deadline_code,
            "worker_calls": invalid_deadline_worker.calls,
        },
        "adapter_closed": {
            "safe_code": closed_code,
            "worker_calls": closed_worker.calls,
        },
    }


def _resolver_faults() -> dict[str, object]:
    now = [100.0]
    resolver = FinQAEphemeralContextResolverV1(
        capacity=1,
        ttl_seconds=2,
        clock=lambda: now[0],
    )
    resolution = FinQATypedServiceResolutionV1.not_applicable(
        "POLICY_DENIED"
    )
    resolver.register(request_id="resolver-first", resolution=resolution)
    duplicate_rejected = False
    try:
        resolver.register(request_id="resolver-first", resolution=resolution)
    except FinQAServiceAdapterErrorV1 as error:
        duplicate_rejected = error.code == "duplicate_request_id"
    capacity_rejected = False
    try:
        resolver.register(request_id="resolver-second", resolution=resolution)
    except FinQAServiceAdapterErrorV1 as error:
        capacity_rejected = error.code == "capacity_exceeded"
    consumed_once = (
        resolver.resolve(
            _request("resolver-first", "Synthetic policy question")
        ).reason
        == "POLICY_DENIED"
    )
    unresolved_after_consume = (
        resolver.resolve(
            _request("resolver-first", "Synthetic policy question")
        ).reason
        == "UNSUPPORTED_TYPED_CONTRACT"
    )
    resolver.register(request_id="resolver-expiring", resolution=resolution)
    now[0] += 3
    expired_fail_closed = (
        resolver.resolve(
            _request("resolver-expiring", "Synthetic policy question")
        ).reason
        == "UNSUPPORTED_TYPED_CONTRACT"
    )
    snapshot = resolver.snapshot()
    resolver.close()
    return {
        "duplicate_rejected": duplicate_rejected,
        "capacity_rejected": capacity_rejected,
        "consumed_once": consumed_once,
        "unresolved_after_consume": unresolved_after_consume,
        "expired_fail_closed": expired_fail_closed,
        "pending_context_count": snapshot["pending_context_count"],
        "pending_high_watermark": snapshot["pending_high_watermark"],
        "counters": snapshot["counters"],
    }


def _e16_composition() -> dict[str, object]:
    question = "How did the synthetic operating metric change?"
    resolver = FinQAEphemeralContextResolverV1(capacity=2, ttl_seconds=5)
    resolver.register(
        request_id="composition-request",
        resolution=FinQATypedServiceResolutionV1.eligible(_context(question)),
    )
    worker = _AuditWorker("MATCH")
    adapter = FinQATypedServiceAdapterV1(resolver=resolver, worker=worker)
    service = DarkObservationService(
        DarkObservationConfig(
            mode="LOCAL_TEST_ONLY",
            sample_basis_points=10_000,
            worker_count=1,
            queue_capacity=2,
            observation_deadline_ms=1_000,
        ),
        provider=adapter,
        sampling_key=hashlib.sha256(b"e17-composition-domain-v1").digest(),
    )
    service.start()
    admission = service.offer(
        request_id="composition-request",
        question=question,
        primary_mode="answered",
        primary_stop_reason="complete",
    )
    deadline = time.monotonic() + 2
    while (
        service.snapshot()["counters"]["completed_total"] < 1
        and time.monotonic() < deadline
    ):
        time.sleep(0.005)
    service_snapshot = service.snapshot()
    close_report = service.close()
    adapter.close()
    resolver.close()
    return {
        "admission": admission,
        "provider_outcomes": service_snapshot["provider_outcomes"],
        "adapter_worker_calls": worker.calls,
        "pending_contexts_after_close": resolver.snapshot()[
            "pending_context_count"
        ],
        "residual_service_workers": close_report["residual_workers"],
    }


def _real_worker_observations() -> dict[str, object]:
    worker = FinQAIsolatedShadowWorkerV1(evidence_dir=EVIDENCE)
    outcomes: Counter[str] = Counter()
    latencies_ms: list[float] = []
    for index, question in enumerate(
        (
            "How did the synthetic operating metric change?",
            "What was the difference between the two synthetic periods?",
        )
    ):
        adapter = FinQATypedServiceAdapterV1(
            resolver=_StaticResolver(
                FinQATypedServiceResolutionV1.eligible(_context(question))
            ),
            worker=worker,
        )
        started = time.perf_counter()
        outcome = adapter.observe(
            _request(f"real-worker-{index}", question),
            deadline_monotonic=time.perf_counter() + 30,
        )
        latencies_ms.append((time.perf_counter() - started) * 1_000)
        outcomes[outcome] += 1
    adapter.close()
    diagnostics = worker.diagnostics()
    ordered = sorted(latencies_ms)
    return {
        "observation_count": len(latencies_ms),
        "outcomes": dict(sorted(outcomes.items())),
        "latency_ms": {
            "count": len(ordered),
            "p50": round(ordered[0], 3),
            "p95": round(ordered[-1], 3),
            "max": round(max(ordered), 3),
        },
        "worker_pid_after_close": diagnostics.worker_pid,
        "last_terminated_exitcode": diagnostics.last_terminated_exitcode,
    }


def run_audit(*, protocol_path: Path) -> dict[str, object]:
    protocol, protocol_sha256 = load_finqa_service_adapter_protocol_v1(
        protocol_path
    )
    source_binding = {
        field: _sha256(EVIDENCE / filename)
        for field, filename in SOURCE_FILES.items()
    }
    expected_binding = {
        field: getattr(protocol, field) for field in SOURCE_FILES
    }
    eligibility = _eligibility_matrix()
    mapping = _outcome_mapping()
    faults = _fault_injection()
    resolver = _resolver_faults()
    composition = _e16_composition()
    real_worker = _real_worker_observations()
    required_reasons = set(protocol.audit_profile.required_eligibility_reasons)
    gate_checks = {
        "source_hash_binding": source_binding == expected_binding,
        "eligibility_reason_coverage": (
            set(eligibility["reason_counts"]) == required_reasons
        ),
        "ineligible_zero_worker_calls": eligibility[
            "ineligible_worker_calls"
        ]
        == protocol.audit_profile.required_ineligible_worker_calls,
        "eligible_calls_worker": eligibility["eligible_worker_calls"] == 1,
        "exact_outcome_mapping": mapping == {"DIFFERENT": 1, "MATCH": 1},
        "input_binding_fail_closed": faults["input_binding_mismatch"] == {
            "safe_code": "input_binding_mismatch",
            "worker_calls": 0,
        },
        "deadline_fail_closed": faults["deadline_expired"] == {
            "safe_code": "deadline_expired",
            "worker_calls": 0,
        },
        "resolver_failure_isolated": faults["resolver_error"] == {
            "safe_code": "resolver_error",
            "worker_calls": 0,
        },
        "worker_failure_isolated": faults["worker_error"] == {
            "safe_code": "worker_error",
            "worker_calls": 1,
        },
        "nonfinite_deadline_rejected": faults["invalid_deadline"] == {
            "safe_code": "invalid_deadline",
            "worker_calls": 0,
        },
        "closed_adapter_rejected": faults["adapter_closed"] == {
            "safe_code": "adapter_closed",
            "worker_calls": 0,
        },
        "resolver_duplicate_does_not_overwrite": resolver[
            "duplicate_rejected"
        ],
        "resolver_capacity_bounded": resolver["capacity_rejected"],
        "resolver_consume_once": resolver["consumed_once"]
        and resolver["unresolved_after_consume"],
        "resolver_ttl_fail_closed": resolver["expired_fail_closed"],
        "resolver_zero_pending_after_audit": resolver[
            "pending_context_count"
        ]
        == 0,
        "e16_background_composition": (
            composition["admission"] == "ADMITTED"
            and composition["provider_outcomes"]["MATCH"] == 1
            and composition["adapter_worker_calls"] == 1
            and composition["pending_contexts_after_close"] == 0
            and composition["residual_service_workers"] == 0
        ),
        "real_worker_observation_count": real_worker["observation_count"]
        == protocol.audit_profile.required_real_worker_observations,
        "real_worker_terminal_outcomes": sum(
            real_worker["outcomes"].get(name, 0)
            for name in ("MATCH", "DIFFERENT")
        )
        == real_worker["observation_count"],
        "real_worker_closed": real_worker["worker_pid_after_close"] is None,
        "zero_model_calls": protocol.audit_profile.required_model_calls == 0,
        "aggregate_only_public_output": True,
        "internal_cohort_not_accessed": protocol.internal_cohort_status
        == "CONSUMED_NOT_ACCESSED",
        "frozen_test_untouched": protocol.frozen_test_status == "UNTOUCHED",
    }
    if not all(gate_checks.values()):
        raise RuntimeError("E17 typed service adapter gate failed")
    return {
        "schema_version": "finqa_service_adapter_public_v1",
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "claim": protocol.claim_label,
        "decision": "E17_TYPED_ADAPTER_MECHANISM_PASSED_NOT_SERVICE_ENABLED",
        "source_binding": {
            **source_binding,
            "implementation_sha256": {
                relative: _sha256(ROOT / relative)
                for relative in IMPLEMENTATION_PATHS
            },
        },
        "eligibility_aggregates": eligibility,
        "adapter_aggregates": {
            "outcome_mapping": mapping,
            "e16_composition": composition,
            "real_isolated_worker": real_worker,
            "model_call_count": 0,
        },
        "fault_injection": {
            "adapter": faults,
            "ephemeral_resolver": resolver,
        },
        "gate_checks": gate_checks,
        "non_claims": list(protocol.non_claims),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit the E17 online typed eligibility adapter."
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run_audit(protocol_path=args.protocol.resolve())
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_canonical_bytes(payload))
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
