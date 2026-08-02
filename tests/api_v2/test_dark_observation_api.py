from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from app.domain.evidence import AnswerResponse
from app.main import create_app
from app.runtime.dark_observation import (
    DarkObservationConfig,
    DarkObservationRequest,
    DarkObservationService,
)
from tests.api_v2.helpers import OPERATOR_HEADERS, USER_HEADERS, make_container


PRIMARY = AnswerResponse(
    mode="not_found",
    answer="No supported answer.",
    stop_reason="not_found",
    warnings=["primary warning remains unchanged"],
    trace={"intent": "fact", "steps": [], "budget": {}},
)


def _wait_until(predicate, *, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition did not become true")


class CapturingProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.requests: list[DarkObservationRequest] = []
        self.fail = fail

    def observe(
        self,
        request: DarkObservationRequest,
        *,
        deadline_monotonic: float,
    ) -> str:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("provider-secret-error")
        return "NOT_APPLICABLE"


def _enabled_service(provider: CapturingProvider) -> DarkObservationService:
    return DarkObservationService(
        DarkObservationConfig(
            mode="LOCAL_TEST_ONLY",
            sample_basis_points=10_000,
            worker_count=1,
            queue_capacity=4,
            observation_deadline_ms=100,
        ),
        provider=provider,
        sampling_key=b"e16-api-sampling-key-0000000000",
    )


def test_chat_response_is_identical_when_dark_provider_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.main.run_agent_v2_chat",
        lambda question, user, top_k=None: PRIMARY,
    )
    provider = CapturingProvider(fail=True)
    dark = _enabled_service(provider)
    app = create_app(make_container(dark_observation=dark))
    request_headers = {**USER_HEADERS, "X-Request-ID": "req-dark-failure"}
    request_json = {"question": "PROJECT SILVER tenant-private"}

    with TestClient(create_app(make_container())) as baseline_client:
        baseline = baseline_client.post(
            "/agent/v2/chat",
            headers=request_headers,
            json=request_json,
        )

    with TestClient(app) as client:
        response = client.post(
            "/agent/v2/chat",
            headers=request_headers,
            json=request_json,
        )
        _wait_until(
            lambda: dark.snapshot()["counters"]["provider_error_total"] == 1
        )

    assert baseline.status_code == response.status_code == 200
    assert response.content == baseline.content
    assert response.headers["X-Feedback-Receipt"] == baseline.headers[
        "X-Feedback-Receipt"
    ]
    assert len(provider.requests) == 1


def test_dark_provider_receives_no_identity_answer_evidence_or_trace(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.main.run_agent_v2_chat",
        lambda question, user, top_k=None: PRIMARY,
    )
    provider = CapturingProvider()
    dark = _enabled_service(provider)
    app = create_app(make_container(dark_observation=dark))

    with TestClient(app) as client:
        response = client.post(
            "/agent/v2/chat",
            headers={**USER_HEADERS, "X-Request-ID": "req-dark-minimal"},
            json={"question": "Question visible only to provider memory"},
        )
        _wait_until(lambda: len(provider.requests) == 1)
        metrics = client.get(
            "/observability/metrics",
            headers=OPERATOR_HEADERS,
        )

    request = provider.requests[0]
    assert set(request.__dict__) == {
        "request_id",
        "question",
        "primary_mode",
        "primary_stop_reason",
    }
    assert request.question == "Question visible only to provider memory"
    assert response.status_code == metrics.status_code == 200
    shadow_metrics = metrics.json()["dark_observation"]
    assert shadow_metrics["counters"]["completed_total"] == 1
    serialized = json.dumps(shadow_metrics)
    for forbidden in [
        request.request_id,
        request.question,
        PRIMARY.answer,
        "tenant-one",
        "employee-one",
        "primary warning remains unchanged",
    ]:
        assert forbidden not in serialized


def test_default_service_is_off_and_spawns_no_dark_workers() -> None:
    container = make_container()

    with TestClient(create_app(container)) as client:
        metrics = client.get(
            "/observability/metrics",
            headers=OPERATOR_HEADERS,
        )

    dark = metrics.json()["dark_observation"]
    assert dark["mode"] == "OFF"
    assert dark["status"] == "OFF"
    assert dark["current"]["workers_alive"] == 0
    assert dark["content_retained"] is False
