from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.runtime.resources import ReadyIndexInfo, RuntimeResources


class MutableClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def settings():
    return SimpleNamespace(readiness_ttl_seconds=5.0)


def index_info() -> ReadyIndexInfo:
    return ReadyIndexInfo(
        run_id="index-run-1",
        chunk_count=64,
        embedding_model="bge-m3",
        embedding_dimension=1024,
        build_duration_ms=13_970,
        index_size_bytes=550_000,
    )


def test_resources_start_reports_ready_with_safe_index_metadata() -> None:
    calls = {"database": 0, "index": 0, "models": 0}

    def database_probe() -> None:
        calls["database"] += 1

    def index_probe() -> ReadyIndexInfo:
        calls["index"] += 1
        return index_info()

    def model_probe() -> None:
        calls["models"] += 1

    resources = RuntimeResources(
        settings(),
        database_probe=database_probe,
        index_probe=index_probe,
        model_probe=model_probe,
        clock=lambda: 0.0,
        utcnow=lambda: datetime(2026, 7, 17, tzinfo=timezone.utc),
    )

    snapshot = resources.start()

    assert snapshot.status == "ready"
    assert snapshot.checks == {
        "database": "ok",
        "index": "ok",
        "models": "ok",
    }
    assert snapshot.index == index_info()
    assert calls == {"database": 1, "index": 1, "models": 1}
    assert resources.started is True
    assert resources.closed is False


def test_dependency_failure_is_safe_not_ready_and_does_not_skip_other_probes() -> None:
    calls: list[str] = []

    def database_probe() -> None:
        calls.append("database")

    def index_probe() -> ReadyIndexInfo:
        calls.append("index")
        raise RuntimeError("D:/vault/secret.index password=never-show")

    def model_probe() -> None:
        calls.append("models")

    resources = RuntimeResources(
        settings(),
        database_probe=database_probe,
        index_probe=index_probe,
        model_probe=model_probe,
        clock=lambda: 0.0,
    )

    snapshot = resources.start()
    serialized = snapshot.model_dump_json()

    assert snapshot.status == "not_ready"
    assert snapshot.checks == {
        "database": "ok",
        "index": "error",
        "models": "ok",
    }
    assert snapshot.index is None
    assert calls == ["database", "index", "models"]
    assert "vault" not in serialized
    assert "never-show" not in serialized


def test_refresh_if_stale_uses_ttl_then_refreshes_all_dependencies() -> None:
    clock = MutableClock()
    calls = 0

    def database_probe() -> None:
        nonlocal calls
        calls += 1

    resources = RuntimeResources(
        settings(),
        database_probe=database_probe,
        index_probe=index_info,
        model_probe=lambda: None,
        clock=clock,
    )
    first = resources.start()

    clock.value = 4.9
    assert resources.refresh_if_stale() is first
    assert calls == 1

    clock.value = 5.0
    second = resources.refresh_if_stale()
    assert second is not first
    assert calls == 2


def test_close_is_idempotent_and_does_not_probe_dependencies() -> None:
    resources = RuntimeResources(
        settings(),
        database_probe=lambda: None,
        index_probe=index_info,
        model_probe=lambda: None,
    )
    resources.start()

    resources.close()
    resources.close()

    assert resources.closed is True
