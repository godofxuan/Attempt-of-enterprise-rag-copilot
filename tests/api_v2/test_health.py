from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from tests.api_v2.helpers import (
    FakeResources,
    make_container,
    not_ready_snapshot,
)


def test_lifespan_starts_and_closes_resources_once() -> None:
    resources = FakeResources()
    app = create_app(make_container(resources=resources))

    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200

    assert resources.start_calls == 1
    assert resources.close_calls == 1


def test_liveness_never_refreshes_dependencies_and_compatibility_alias_remains() -> None:
    resources = FakeResources(not_ready_snapshot())
    app = create_app(make_container(resources=resources))

    with TestClient(app) as client:
        live = client.get("/health/live")
        legacy = client.get("/health")

    assert live.status_code == 200
    assert live.json() == {"status": "alive"}
    assert legacy.status_code == 200
    assert legacy.json() == {"status": "ok"}
    assert legacy.headers["deprecation"] == "true"
    assert resources.refresh_calls == 0


def test_readiness_maps_dependency_state_to_200_or_503() -> None:
    resources = FakeResources()
    app = create_app(make_container(resources=resources))

    with TestClient(app) as client:
        ready = client.get("/health/ready")
        resources.current = not_ready_snapshot()
        not_ready = client.get("/health/ready")

    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["index"]["run_id"] == "test-index"
    assert not_ready.status_code == 503
    assert not_ready.json() == {
        "status": "not_ready",
        "checks": {"database": "ok", "index": "error", "models": "ok"},
        "retrieved_guard": "ready",
        "index": None,
        "checked_at_utc": "2026-07-17T00:00:00Z",
    }
    assert resources.refresh_calls == 2


def test_readiness_exposes_only_safe_guard_error_status() -> None:
    guard_failed = not_ready_snapshot().model_copy(
        update={
            "checks": {"database": "ok", "index": "ok", "models": "ok"},
            "retrieved_guard": "error",
        }
    )
    resources = FakeResources(guard_failed)

    with TestClient(create_app(make_container(resources=resources))) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "ok", "index": "ok", "models": "ok"},
        "retrieved_guard": "error",
        "index": None,
        "checked_at_utc": "2026-07-17T00:00:00Z",
    }
    assert "rule" not in response.text.casefold()
    assert "path" not in response.text.casefold()
    assert "sha256" not in response.text.casefold()
