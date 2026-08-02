from __future__ import annotations

import hashlib
import json
import time

import pytest
from pydantic import ValidationError

from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeCandidateDescriptorV3,
    RetrievableSafeDescriptorCatalogV3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
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
)
from app.runtime.dark_observation import (
    DarkObservationConfig,
    DarkObservationRequest,
    DarkObservationService,
)


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
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
            metric=f"operating metric category {index}",
            row_header=f"operating metric category {index}",
            column_header="current period",
            local_context_hint="annual operating result",
            topic_hint="company operating performance",
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
    return RetrievableSafeDescriptorCatalogV3(
        **payload,
        catalog_sha256=hashlib.sha256(_canonical_bytes(payload)).hexdigest(),
    )


def _context(question: str) -> FinQATypedServiceContextV1:
    return FinQATypedServiceContextV1.build(
        question=question,
        skeleton=_skeleton(),
        catalog=_catalog(),
        skeleton_origin="ONLINE_RULES",
        catalog_origin="RETRIEVED_ADMITTED_EVIDENCE",
    )


def _request(question: str) -> DarkObservationRequest:
    return DarkObservationRequest(
        request_id="req-e17-test",
        question=question,
        primary_mode="answered",
        primary_stop_reason="complete",
    )


class _Resolver:
    def __init__(self, resolution: FinQATypedServiceResolutionV1) -> None:
        self.resolution = resolution
        self.calls = 0

    def resolve(
        self,
        request: DarkObservationRequest,
    ) -> FinQATypedServiceResolutionV1:
        self.calls += 1
        return self.resolution


class _FailingResolver:
    def resolve(self, request: DarkObservationRequest):
        raise RuntimeError(f"must not leak {request.question}")


class _SpoofingResolver:
    def resolve(self, request: DarkObservationRequest):
        raise FinQAServiceAdapterErrorV1(request.question)


class _InvalidResolver:
    def resolve(self, request: DarkObservationRequest):
        return {"question": request.question}


class _Worker:
    def __init__(self, outcome: str = "MATCH") -> None:
        self.outcome = outcome
        self.calls = 0
        self.primaries = []
        self.closed = False

    def observe(self, *, primary, question, skeleton, catalog):
        self.calls += 1
        self.primaries.append(primary)
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
        self.closed = True


def test_complete_online_context_computes_e8_primary_before_worker() -> None:
    question = "How did the operating metric change between periods?"
    resolver = _Resolver(FinQATypedServiceResolutionV1.eligible(_context(question)))
    worker = _Worker("MATCH")
    adapter = FinQATypedServiceAdapterV1(resolver=resolver, worker=worker)

    outcome = adapter.observe(
        _request(question),
        deadline_monotonic=time.perf_counter() + 1,
    )
    snapshot = adapter.snapshot()
    adapter.close()

    assert outcome == "MATCH"
    assert resolver.calls == 1
    assert worker.calls == 1
    assert worker.primaries[0].result.retriever_version == (
        "finqa_deterministic_descriptor_retriever_v5"
    )
    assert worker.primaries[0].result.generation_calls == 0
    assert snapshot["eligibility_reasons"] == {"TYPED_CONTEXT_COMPLETE": 1}
    assert snapshot["provider_outcomes"] == {"MATCH": 1}
    assert snapshot["model_call_count"] == 0
    assert worker.closed is True


@pytest.mark.parametrize(
    "reason",
    (
        "NOT_FINANCIAL_NUMERIC",
        "MISSING_TYPED_SKELETON",
        "MISSING_SAFE_CATALOG",
        "POLICY_DENIED",
        "UNSUPPORTED_TYPED_CONTRACT",
    ),
)
def test_ineligible_context_abstains_without_starting_worker(reason: str) -> None:
    resolver = _Resolver(FinQATypedServiceResolutionV1.not_applicable(reason))
    worker = _Worker()
    adapter = FinQATypedServiceAdapterV1(resolver=resolver, worker=worker)

    outcome = adapter.observe(
        _request("What is the leave policy?"),
        deadline_monotonic=time.perf_counter() + 1,
    )

    assert outcome == "NOT_APPLICABLE"
    assert worker.calls == 0
    assert adapter.snapshot()["eligibility_reasons"] == {reason: 1}


def test_context_and_resolution_reject_oracle_or_inconsistent_state() -> None:
    question = "How did the operating metric change between periods?"
    payload = _context(question).model_dump(mode="json")
    payload["skeleton_origin"] = "GOLD_PROGRAM"

    with pytest.raises(ValidationError):
        FinQATypedServiceContextV1.model_validate(payload)
    with pytest.raises(ValidationError, match="disposition and reason"):
        FinQATypedServiceResolutionV1(
            disposition="ELIGIBLE",
            reason="NOT_FINANCIAL_NUMERIC",
            context=_context(question),
        )


def test_diverged_worker_maps_to_different_without_exposing_content() -> None:
    question = "PRIVATE E17 operating plan changed between periods"
    adapter = FinQATypedServiceAdapterV1(
        resolver=_Resolver(
            FinQATypedServiceResolutionV1.eligible(_context(question))
        ),
        worker=_Worker("DIVERGED"),
    )

    assert adapter.observe(
        _request(question),
        deadline_monotonic=time.perf_counter() + 1,
    ) == "DIFFERENT"
    serialized = json.dumps(adapter.snapshot(), sort_keys=True)

    assert adapter.snapshot()["provider_outcomes"] == {"DIFFERENT": 1}
    assert question not in serialized
    assert "req-e17-test" not in serialized


def test_binding_and_deadline_fail_before_worker() -> None:
    original = "How did the operating metric change between periods?"
    for request_question, deadline in (
        (f"{original} altered", time.perf_counter() + 1),
        (original, time.perf_counter() - 1),
    ):
        worker = _Worker()
        adapter = FinQATypedServiceAdapterV1(
            resolver=_Resolver(
                FinQATypedServiceResolutionV1.eligible(_context(original))
            ),
            worker=worker,
        )

        with pytest.raises(FinQAServiceAdapterErrorV1) as raised:
            adapter.observe(
                _request(request_question),
                deadline_monotonic=deadline,
            )

        assert raised.value.code in {
            "input_binding_mismatch",
            "deadline_expired",
        }
        assert original not in str(raised.value)
        assert worker.calls == 0


def test_resolver_and_worker_failures_are_reduced_to_safe_codes() -> None:
    question = "PRIVATE E17 board metric"
    worker = _Worker()
    resolver_adapter = FinQATypedServiceAdapterV1(
        resolver=_FailingResolver(),
        worker=worker,
    )
    with pytest.raises(
        FinQAServiceAdapterErrorV1,
        match="resolver_error",
    ) as resolver_error:
        resolver_adapter.observe(
            _request(question),
            deadline_monotonic=time.perf_counter() + 1,
        )

    class _FailingWorker(_Worker):
        def observe(self, *, primary, question, skeleton, catalog):
            self.calls += 1
            raise RuntimeError(f"must not leak {question}")

    failing_worker = _FailingWorker()
    worker_adapter = FinQATypedServiceAdapterV1(
        resolver=_Resolver(
            FinQATypedServiceResolutionV1.eligible(_context(question))
        ),
        worker=failing_worker,
    )
    with pytest.raises(
        FinQAServiceAdapterErrorV1,
        match="worker_error",
    ) as worker_error:
        worker_adapter.observe(
            _request(question),
            deadline_monotonic=time.perf_counter() + 1,
        )

    assert question not in str(resolver_error.value)
    assert question not in str(worker_error.value)
    assert worker.calls == 0
    assert failing_worker.calls == 1
    assert resolver_adapter.snapshot()["failures"] == {"resolver_error": 1}
    assert worker_adapter.snapshot()["failures"] == {"worker_error": 1}


def test_ephemeral_resolver_consumes_once_and_never_overwrites_request_id() -> None:
    now = [100.0]
    resolver = FinQAEphemeralContextResolverV1(
        capacity=2,
        ttl_seconds=5,
        clock=lambda: now[0],
    )
    question = "PRIVATE E17 operating metric"
    first = FinQATypedServiceResolutionV1.eligible(_context(question))
    second = FinQATypedServiceResolutionV1.not_applicable("POLICY_DENIED")

    resolver.register(request_id="req-e17-test", resolution=first)
    with pytest.raises(FinQAServiceAdapterErrorV1, match="duplicate_request_id"):
        resolver.register(request_id="req-e17-test", resolution=second)

    assert resolver.resolve(_request(question)) == first
    assert resolver.resolve(_request(question)).reason == (
        "UNSUPPORTED_TYPED_CONTRACT"
    )
    serialized = json.dumps(resolver.snapshot(), sort_keys=True)
    assert resolver.snapshot()["pending_context_count"] == 0
    assert resolver.snapshot()["counters"] == {
        "consumed_total": 1,
        "duplicate_rejected_total": 1,
        "registered_total": 1,
        "unresolved_total": 1,
    }
    assert question not in serialized
    assert "req-e17-test" not in serialized


def test_ephemeral_resolver_bounds_capacity_ttl_and_explicit_discard() -> None:
    now = [200.0]
    resolver = FinQAEphemeralContextResolverV1(
        capacity=1,
        ttl_seconds=2,
        clock=lambda: now[0],
    )
    resolution = FinQATypedServiceResolutionV1.not_applicable(
        "NOT_FINANCIAL_NUMERIC"
    )
    resolver.register(request_id="req-one", resolution=resolution)
    with pytest.raises(FinQAServiceAdapterErrorV1, match="capacity_exceeded"):
        resolver.register(request_id="req-two", resolution=resolution)

    now[0] += 3
    resolver.register(request_id="req-two", resolution=resolution)
    assert resolver.discard("req-two") is True
    assert resolver.discard("req-missing") is False
    resolver.close()

    snapshot = resolver.snapshot()
    assert snapshot["pending_context_count"] == 0
    assert snapshot["closed"] is True
    assert snapshot["counters"] == {
        "capacity_rejected_total": 1,
        "discarded_total": 1,
        "expired_total": 1,
        "registered_total": 2,
    }


def test_adapter_composes_with_e16_background_service() -> None:
    question = "How did the operating metric change between periods?"
    resolver = FinQAEphemeralContextResolverV1(capacity=2, ttl_seconds=5)
    resolver.register(
        request_id="req-e17-test",
        resolution=FinQATypedServiceResolutionV1.eligible(_context(question)),
    )
    worker = _Worker("MATCH")
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
        sampling_key=b"e17-composition-key-000000000000",
    )

    service.start()
    assert service.offer(
        request_id="req-e17-test",
        question=question,
        primary_mode="answered",
        primary_stop_reason="complete",
    ) == "ADMITTED"
    deadline = time.monotonic() + 1
    while (
        service.snapshot()["counters"]["completed_total"] < 1
        and time.monotonic() < deadline
    ):
        time.sleep(0.005)
    close_report = service.close()
    adapter.close()
    resolver.close()

    assert service.snapshot()["provider_outcomes"]["MATCH"] == 1
    assert adapter.snapshot()["worker_calls"] == 1
    assert resolver.snapshot()["pending_context_count"] == 0
    assert close_report["residual_workers"] == 0


@pytest.mark.parametrize("resolver", (_SpoofingResolver(), _InvalidResolver()))
def test_untrusted_resolver_cannot_control_error_text_or_return_type(
    resolver,
) -> None:
    question = "PRIVATE E17 resolver payload"
    worker = _Worker()
    adapter = FinQATypedServiceAdapterV1(resolver=resolver, worker=worker)

    with pytest.raises(FinQAServiceAdapterErrorV1) as raised:
        adapter.observe(
            _request(question),
            deadline_monotonic=time.perf_counter() + 1,
        )

    assert raised.value.code in {"resolver_error", "invalid_resolution"}
    assert question not in str(raised.value)
    assert worker.calls == 0


def test_nonfinite_deadline_and_closed_adapter_fail_before_resolution() -> None:
    question = "How did the operating metric change between periods?"
    resolver = _Resolver(
        FinQATypedServiceResolutionV1.eligible(_context(question))
    )
    worker = _Worker()
    adapter = FinQATypedServiceAdapterV1(resolver=resolver, worker=worker)

    with pytest.raises(FinQAServiceAdapterErrorV1) as invalid_deadline:
        adapter.observe(_request(question), deadline_monotonic=float("nan"))
    adapter.close()
    with pytest.raises(FinQAServiceAdapterErrorV1) as closed:
        adapter.observe(
            _request(question),
            deadline_monotonic=time.perf_counter() + 1,
        )

    assert invalid_deadline.value.code == "invalid_deadline"
    assert closed.value.code == "adapter_closed"
    assert resolver.calls == 0
    assert worker.calls == 0
