from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.domain.evidence import AnswerResponse
from app.main import create_app
from tests.api_v2.helpers import OPERATOR_HEADERS, USER_HEADERS, make_container


USER = {
    "user_id": "employee-secret",
    "tenant_id": "tenant-secret",
    "region": "cn",
    "groups": ["hr-confidential"],
    "roles": [],
}


def test_metrics_and_trace_api_expose_only_safe_request_metadata(monkeypatch) -> None:
    question = "PROJECT NIGHTFALL Board Compensation Secret"
    monkeypatch.setattr(
        "app.main.run_agent_v2_chat",
        lambda question, user, top_k=None: AnswerResponse(
            mode="not_found",
            answer="No supported answer.",
            stop_reason="not_found",
            trace={"intent": "fact", "steps": [], "budget": {}},
        ),
    )
    container = make_container()
    client = TestClient(create_app(container))

    response = client.post(
        "/agent/v2/chat",
        headers={**USER_HEADERS, "X-Request-ID": "req-observe"},
        json={"question": question},
    )
    trace = client.get(
        "/observability/traces/req-observe",
        headers=OPERATOR_HEADERS,
    )
    metrics = client.get("/observability/metrics", headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    assert trace.status_code == 200
    assert trace.json()["request_id"] == "req-observe"
    assert trace.json()["route"] == "/agent/v2/chat"
    assert "retrieved_content_security" not in trace.json()
    assert metrics.status_code == 200
    serialized = json.dumps(
        {"trace": trace.json(), "metrics": metrics.json()},
        ensure_ascii=False,
    )
    for forbidden in [
        question,
        "employee-secret",
        "tenant-secret",
        "hr-confidential",
        "Board Compensation",
    ]:
        assert forbidden not in serialized


def test_trace_lookup_does_not_overwrite_target_when_request_id_is_reused(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.main.run_agent_v2_chat",
        lambda question, user, top_k=None: AnswerResponse(
            mode="not_found",
            answer="No supported answer.",
            stop_reason="not_found",
            trace={"intent": "fact", "steps": [], "budget": {}},
        ),
    )
    container = make_container()
    client = TestClient(create_app(container))

    response = client.post(
        "/agent/v2/chat",
        headers={**USER_HEADERS, "X-Request-ID": "req-repeat"},
        json={"question": "What is the policy?"},
    )
    first = client.get(
        "/observability/traces/req-repeat",
        headers={**OPERATOR_HEADERS, "X-Request-ID": "req-repeat"},
    )
    second = client.get(
        "/observability/traces/req-repeat",
        headers={**OPERATOR_HEADERS, "X-Request-ID": "req-repeat"},
    )

    assert response.status_code == first.status_code == second.status_code == 200
    assert first.headers["X-Request-ID"] == "req-repeat"
    assert second.headers["X-Request-ID"] == "req-repeat"
    assert first.json()["route"] == "/agent/v2/chat"
    assert second.json()["route"] == "/agent/v2/chat"
    assert [trace.route for trace in container.traces.recent()] == [
        "/agent/v2/chat"
    ]
    trace_metrics = container.metrics.snapshot()["requests"]["by_route"][
        "GET /observability/traces/{request_id}"
    ]
    assert trace_metrics["status"] == {"2xx": 2}
    assert trace_metrics["latency_ms"]["count"] == 2


def test_unknown_trace_returns_unified_safe_404() -> None:
    response = TestClient(create_app(make_container())).get(
        "/observability/traces/missing-id",
        headers={**OPERATOR_HEADERS, "X-Request-ID": "req-lookup"},
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "trace_not_found",
            "message": "The requested trace was not found.",
            "request_id": "req-lookup",
            "retryable": False,
        }
    }
