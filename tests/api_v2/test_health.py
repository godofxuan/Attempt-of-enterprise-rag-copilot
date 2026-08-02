from __future__ import annotations

import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import create_app
from app.runtime.resources import ReadyIndexInfo, RuntimeResources
from tests.api_v2.helpers import (
    FakeResources,
    USER_HEADERS,
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


class _FailingDarkLifecycle:
    def __init__(self) -> None:
        self.start_calls = 0
        self.close_calls = 0

    def start(self) -> None:
        self.start_calls += 1
        raise RuntimeError("injected dark startup failure")

    def close(self) -> None:
        self.close_calls += 1
        raise RuntimeError("injected dark shutdown failure")

    def snapshot(self) -> dict[str, object]:
        return {"status": "UNAVAILABLE", "content_retained": False}


def test_dark_lifecycle_failure_never_blocks_primary_service_lifespan() -> None:
    resources = FakeResources()
    dark = _FailingDarkLifecycle()
    app = create_app(
        make_container(resources=resources, dark_observation=dark)  # type: ignore[arg-type]
    )

    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200

    assert dark.start_calls == 1
    assert dark.close_calls == 1
    assert resources.start_calls == 1
    assert resources.close_calls == 1


def test_blocked_startup_deep_probe_does_not_block_liveness() -> None:
    probe_entered = threading.Event()
    release_probe = threading.Event()

    def blocking_model_probe() -> None:
        probe_entered.set()
        release_probe.wait(timeout=1.0)

    resources = RuntimeResources(
        SimpleNamespace(
            readiness_ttl_seconds=5.0,
            readiness_probe_timeout_seconds=0.1,
        ),
        database_probe=lambda: None,
        index_probe=lambda: ReadyIndexInfo(
            run_id="index-run-1",
            chunk_count=64,
            embedding_model="bge-m3",
            embedding_dimension=1024,
            build_duration_ms=100,
            index_size_bytes=1_000,
        ),
        model_probe=blocking_model_probe,
        identity_probe=lambda: None,
    )

    with TestClient(create_app(make_container(resources=resources))) as client:
        assert probe_entered.wait(timeout=0.5)
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503

        release_probe.set()
        assert resources.wait_for_refresh(timeout=0.5)
        assert client.get("/health/ready").status_code == 200


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
            "checks": {
                "database": "ok",
                "index": "error",
                "models": "ok",
                "identity": "ok",
            },
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


def test_chat_rejects_not_ready_service_before_agent_side_effect(monkeypatch) -> None:
    calls = 0

    def forbidden_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("agent must not run")

    monkeypatch.setattr("app.main.run_agent_v2_chat", forbidden_run)
    resources = FakeResources(not_ready_snapshot())
    response = TestClient(create_app(make_container(resources=resources))).post(
        "/agent/v2/chat",
        headers=USER_HEADERS,
        json={"question": "Policy?"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_not_ready"
    assert response.json()["error"]["retryable"] is True
    assert calls == 0


def test_feedback_requires_database_and_identity_but_not_model_or_index(
    monkeypatch,
) -> None:
    writes = 0

    def fake_write(**kwargs):
        nonlocal writes
        writes += 1

    monkeypatch.setattr("app.main.save_feedback_metadata", fake_write)
    snapshot = not_ready_snapshot().model_copy(
        update={
            "checks": {
                "database": "ok",
                "index": "error",
                "models": "error",
                "identity": "ok",
            }
        }
    )
    container = make_container(resources=FakeResources(snapshot))
    principal = container.identity_verifier.verify_bearer(
        USER_HEADERS["Authorization"]
    )
    receipt = container.feedback_actor_hasher.issue_feedback_receipt(
        principal,
        target_request_id="req-answer-target",
        question="Policy?",
        answer="Answer",
    )

    response = TestClient(create_app(container)).post(
        "/feedback",
        headers=USER_HEADERS,
        json={
            "target_request_id": "req-answer-target",
            "question": "Policy?",
            "answer": "Answer",
            "helpful": True,
            "receipt": receipt,
        },
    )

    assert response.status_code == 200
    assert writes == 1


def test_feedback_rejects_database_not_ready_before_write(monkeypatch) -> None:
    writes = 0

    def forbidden_write(**kwargs):
        nonlocal writes
        writes += 1

    monkeypatch.setattr("app.main.save_feedback_metadata", forbidden_write)
    snapshot = not_ready_snapshot().model_copy(
        update={
            "checks": {
                "database": "error",
                "index": "ok",
                "models": "ok",
                "identity": "ok",
            }
        }
    )
    response = TestClient(
        create_app(make_container(resources=FakeResources(snapshot)))
    ).post(
        "/feedback",
        headers=USER_HEADERS,
        json={
            "target_request_id": "req-answer-target",
            "question": "Policy?",
            "answer": "Answer",
            "helpful": True,
            "receipt": "a" * 64,
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_not_ready"
    assert writes == 0
