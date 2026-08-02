from __future__ import annotations

import json
import threading
import time

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.runtime.dark_observation import (
    DarkObservationConfig,
    DarkObservationRequest,
    DarkObservationService,
)


def _wait_for_counter(
    service: DarkObservationService,
    name: str,
    expected: int,
    *,
    timeout: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if service.snapshot()["counters"][name] >= expected:
            return
        time.sleep(0.005)
    raise AssertionError(f"counter {name} did not reach {expected}")


class CountingProvider:
    def __init__(self) -> None:
        self.requests: list[DarkObservationRequest] = []

    def observe(
        self,
        request: DarkObservationRequest,
        *,
        deadline_monotonic: float,
    ) -> str:
        self.requests.append(request)
        return "MATCH"


def test_default_off_starts_no_workers_and_never_calls_provider() -> None:
    provider = CountingProvider()
    service = DarkObservationService(
        DarkObservationConfig(),
        provider=provider,
        sampling_key=b"e16-test-sampling-key-000000000",
    )

    service.start()
    outcome = service.offer(
        request_id="req-default-off",
        question="Confidential acquisition plan",
        primary_mode="not_found",
        primary_stop_reason="not_found",
    )
    close_report = service.close()

    assert outcome == "DISABLED"
    assert provider.requests == []
    assert close_report == {
        "workers_started": 0,
        "workers_stopped": 0,
        "residual_workers": 0,
    }
    snapshot = service.snapshot()
    assert snapshot["mode"] == "OFF"
    assert snapshot["counters"]["disabled_total"] == 1
    assert snapshot["current"]["workers_alive"] == 0


def test_enabled_service_executes_ephemeral_minimal_request_and_aggregates_only() -> None:
    provider = CountingProvider()
    service = DarkObservationService(
        DarkObservationConfig(
            mode="LOCAL_TEST_ONLY",
            sample_basis_points=10_000,
            worker_count=1,
            queue_capacity=2,
        ),
        provider=provider,
        sampling_key=b"e16-test-sampling-key-000000000",
    )
    secret_question = "PROJECT COBALT tenant-secret board compensation"

    service.start()
    assert service.offer(
        request_id="req-minimal",
        question=secret_question,
        primary_mode="answered",
        primary_stop_reason="complete",
    ) == "ADMITTED"
    _wait_for_counter(service, "completed_total", 1)
    snapshot = service.snapshot()
    close_report = service.close()

    assert provider.requests == [
        DarkObservationRequest(
            request_id="req-minimal",
            question=secret_question,
            primary_mode="answered",
            primary_stop_reason="complete",
        )
    ]
    assert snapshot["provider_outcomes"] == {
        "MATCH": 1,
        "DIFFERENT": 0,
        "NOT_APPLICABLE": 0,
    }
    serialized = json.dumps(snapshot)
    assert "req-minimal" not in serialized
    assert secret_question not in serialized
    assert "tenant-secret" not in serialized
    assert close_report["residual_workers"] == 0


def test_sampling_is_keyed_deterministic_and_does_not_use_question_content() -> None:
    provider = CountingProvider()
    service = DarkObservationService(
        DarkObservationConfig(
            mode="LOCAL_TEST_ONLY",
            sample_basis_points=5_000,
        ),
        provider=provider,
        sampling_key=b"e16-test-sampling-key-000000000",
    )
    service.start()

    first = service.offer(
        request_id="stable-request-id",
        question="first question",
        primary_mode="not_found",
        primary_stop_reason=None,
    )
    second = service.offer(
        request_id="stable-request-id",
        question="entirely different question",
        primary_mode="answered",
        primary_stop_reason="complete",
    )
    service.close()

    assert first == second
    assert first in {"ADMITTED", "SAMPLE_SKIPPED"}


class BlockingProvider:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def observe(
        self,
        request: DarkObservationRequest,
        *,
        deadline_monotonic: float,
    ) -> str:
        self.entered.set()
        self.release.wait(timeout=1.0)
        return "MATCH"


def test_bounded_queue_rejects_backpressure_without_blocking_caller() -> None:
    provider = BlockingProvider()
    service = DarkObservationService(
        DarkObservationConfig(
            mode="LOCAL_TEST_ONLY",
            sample_basis_points=10_000,
            worker_count=1,
            queue_capacity=1,
            observation_deadline_ms=1_000,
        ),
        provider=provider,
        sampling_key=b"e16-test-sampling-key-000000000",
    )
    service.start()

    assert service.offer(
        request_id="req-active",
        question="one",
        primary_mode="not_found",
        primary_stop_reason=None,
    ) == "ADMITTED"
    assert provider.entered.wait(timeout=0.5)
    assert service.offer(
        request_id="req-queued",
        question="two",
        primary_mode="not_found",
        primary_stop_reason=None,
    ) == "ADMITTED"
    started_at = time.monotonic()
    rejected = service.offer(
        request_id="req-rejected",
        question="three",
        primary_mode="not_found",
        primary_stop_reason=None,
    )
    elapsed_ms = (time.monotonic() - started_at) * 1_000.0
    provider.release.set()
    close_report = service.close()

    assert rejected == "BACKPRESSURE"
    assert elapsed_ms < 10.0
    assert service.snapshot()["counters"]["backpressure_total"] == 1
    assert close_report["residual_workers"] == 0


class FailingProvider:
    def observe(
        self,
        request: DarkObservationRequest,
        *,
        deadline_monotonic: float,
    ) -> str:
        raise RuntimeError(f"must never expose {request.question}")


class SlowProvider:
    def observe(
        self,
        request: DarkObservationRequest,
        *,
        deadline_monotonic: float,
    ) -> str:
        time.sleep(0.03)
        return "DIFFERENT"


def test_provider_error_and_late_result_are_reduced_to_safe_counters() -> None:
    services = [
        DarkObservationService(
            DarkObservationConfig(
                mode="LOCAL_TEST_ONLY",
                sample_basis_points=10_000,
            ),
            provider=FailingProvider(),
            sampling_key=b"e16-test-sampling-key-000000000",
        ),
        DarkObservationService(
            DarkObservationConfig(
                mode="LOCAL_TEST_ONLY",
                sample_basis_points=10_000,
                observation_deadline_ms=5,
            ),
            provider=SlowProvider(),
            sampling_key=b"e16-test-sampling-key-000000000",
        ),
    ]

    for index, service in enumerate(services):
        service.start()
        assert service.offer(
            request_id=f"req-failure-{index}",
            question="never-persist-this-secret",
            primary_mode="not_found",
            primary_stop_reason=None,
        ) == "ADMITTED"
    _wait_for_counter(services[0], "provider_error_total", 1)
    _wait_for_counter(services[1], "deadline_exceeded_total", 1)

    snapshots = [service.snapshot() for service in services]
    reports = [service.close() for service in services]

    assert snapshots[0]["counters"]["completed_total"] == 0
    assert snapshots[1]["counters"]["completed_total"] == 0
    assert snapshots[1]["provider_outcomes"]["DIFFERENT"] == 0
    assert "never-persist" not in json.dumps(snapshots)
    assert all(report["residual_workers"] == 0 for report in reports)


def test_closed_service_rejects_new_observation() -> None:
    service = DarkObservationService(
        DarkObservationConfig(
            mode="LOCAL_TEST_ONLY",
            sample_basis_points=10_000,
        ),
        provider=CountingProvider(),
        sampling_key=b"e16-test-sampling-key-000000000",
    )
    service.start()
    service.close()

    assert service.offer(
        request_id="req-after-close",
        question="ignored",
        primary_mode="not_found",
        primary_stop_reason=None,
    ) == "CLOSED"
    assert service.snapshot()["counters"]["closed_rejected_total"] == 1


def test_settings_reject_ambiguous_dark_observation_activation() -> None:
    with pytest.raises(ValidationError, match="OFF dark observation"):
        Settings(
            _env_file=None,
            dark_observation_mode="OFF",
            dark_observation_sample_basis_points=1,
        )
    with pytest.raises(ValidationError, match="requires sampling"):
        Settings(
            _env_file=None,
            dark_observation_mode="LOCAL_TEST_ONLY",
            dark_observation_sample_basis_points=0,
        )

    enabled = Settings(
        _env_file=None,
        dark_observation_mode="LOCAL_TEST_ONLY",
        dark_observation_sample_basis_points=1_000,
    )
    assert enabled.dark_observation_mode == "LOCAL_TEST_ONLY"
    assert enabled.dark_observation_sample_basis_points == 1_000
