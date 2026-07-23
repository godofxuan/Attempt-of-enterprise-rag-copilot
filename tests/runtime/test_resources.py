from __future__ import annotations

from datetime import datetime, timezone
import threading
from types import MappingProxyType, SimpleNamespace

import pytest

from app.config import Settings
import app.runtime.resources as resources_module
from app.runtime.resources import (
    ReadyIndexInfo,
    RuntimeResources,
    build_service_container,
)
import app.security.retrieved_content as retrieved_content_module


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


def test_start_returns_fail_closed_while_deep_probe_runs_in_background() -> None:
    probe_entered = threading.Event()
    release_probe = threading.Event()
    start_returned = threading.Event()
    returned_snapshots = []

    def blocking_model_probe() -> None:
        probe_entered.set()
        release_probe.wait(timeout=1.0)

    resources = RuntimeResources(
        settings(),
        database_probe=lambda: None,
        index_probe=index_info,
        model_probe=blocking_model_probe,
        identity_probe=lambda: None,
    )

    def call_start() -> None:
        returned_snapshots.append(resources.start())
        start_returned.set()

    caller = threading.Thread(target=call_start)
    caller.start()
    try:
        assert probe_entered.wait(timeout=0.5)
        assert start_returned.wait(timeout=0.05)
    finally:
        release_probe.set()
        caller.join(timeout=1.0)
        resources.close()

    assert returned_snapshots[0].status == "not_ready"


def test_resources_start_reports_ready_with_safe_index_metadata() -> None:
    calls = {"database": 0, "index": 0, "models": 0, "identity": 0}

    def database_probe() -> None:
        calls["database"] += 1

    def index_probe() -> ReadyIndexInfo:
        calls["index"] += 1
        return index_info()

    def model_probe() -> None:
        calls["models"] += 1

    def identity_probe() -> None:
        calls["identity"] += 1

    resources = RuntimeResources(
        settings(),
        database_probe=database_probe,
        index_probe=index_probe,
        model_probe=model_probe,
        identity_probe=identity_probe,
        clock=lambda: 0.0,
        utcnow=lambda: datetime(2026, 7, 17, tzinfo=timezone.utc),
    )

    initial = resources.start()
    assert initial.status == "not_ready"
    assert resources.wait_for_refresh(timeout=0.5)
    snapshot = resources.refresh_if_stale()

    assert snapshot.status == "ready"
    assert snapshot.checks == {
        "database": "ok",
        "index": "ok",
        "models": "ok",
        "identity": "ok",
    }
    assert snapshot.index == index_info()
    assert calls == {"database": 1, "index": 1, "models": 1, "identity": 1}
    assert resources.started is True
    assert resources.closed is False
    resources.close()


def test_dependency_failure_is_safe_not_ready_and_does_not_skip_other_probes() -> None:
    calls: list[str] = []

    def database_probe() -> None:
        calls.append("database")

    def index_probe() -> ReadyIndexInfo:
        calls.append("index")
        raise RuntimeError("D:/vault/secret.index password=never-show")

    def model_probe() -> None:
        calls.append("models")

    def identity_probe() -> None:
        calls.append("identity")

    resources = RuntimeResources(
        settings(),
        database_probe=database_probe,
        index_probe=index_probe,
        model_probe=model_probe,
        identity_probe=identity_probe,
        clock=lambda: 0.0,
    )

    resources.start()
    assert resources.wait_for_refresh(timeout=0.5)
    snapshot = resources.refresh_if_stale()
    serialized = snapshot.model_dump_json()

    assert snapshot.status == "not_ready"
    assert snapshot.checks == {
        "database": "ok",
        "index": "error",
        "models": "error",
        "identity": "ok",
    }
    assert snapshot.index is None
    assert calls == ["database", "index", "identity"]
    assert "vault" not in serialized
    assert "never-show" not in serialized
    resources.close()


def test_refresh_if_stale_never_runs_probes_on_the_request_path() -> None:
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
        identity_probe=lambda: None,
        clock=clock,
    )
    initial = resources.start()
    assert initial.status == "not_ready"
    assert resources.wait_for_refresh(timeout=0.5)
    first = resources.refresh_if_stale()

    clock.value = 4.9
    assert resources.refresh_if_stale() is first
    assert calls == 1

    clock.value = 5.0
    second = resources.refresh_if_stale()
    assert second is not first
    assert second.status == "not_ready"
    assert second.checks == {
        "database": "error",
        "index": "error",
        "models": "error",
        "identity": "error",
    }
    assert calls == 1
    resources.close()


def test_close_is_idempotent_and_does_not_probe_dependencies() -> None:
    resources = RuntimeResources(
        settings(),
        database_probe=lambda: None,
        index_probe=index_info,
        model_probe=lambda: None,
        identity_probe=lambda: None,
    )
    resources.start()

    resources.close()
    resources.close()

    assert resources.closed is True


def test_close_prevents_an_in_flight_probe_from_publishing() -> None:
    probe_entered = threading.Event()
    release_probe = threading.Event()
    configured = SimpleNamespace(
        readiness_ttl_seconds=5.0,
        readiness_probe_timeout_seconds=0.01,
    )

    def blocking_model_probe() -> None:
        probe_entered.set()
        release_probe.wait(timeout=1.0)

    resources = RuntimeResources(
        configured,
        database_probe=lambda: None,
        index_probe=index_info,
        model_probe=blocking_model_probe,
        identity_probe=lambda: None,
    )

    initial = resources.start()
    assert probe_entered.wait(timeout=0.5)
    resources.close()
    release_probe.set()

    assert resources.wait_for_refresh(timeout=0.1) is False
    assert resources.refresh_if_stale() is initial


def test_guard_probe_adds_only_low_sensitivity_ready_status() -> None:
    calls: list[str] = []

    resources = RuntimeResources(
        settings(),
        database_probe=lambda: calls.append("database"),
        index_probe=lambda: (calls.append("index"), index_info())[1],
        model_probe=lambda: calls.append("models"),
        guard_probe=lambda: calls.append("retrieved_guard"),
        identity_probe=lambda: calls.append("identity"),
        clock=lambda: 0.0,
    )

    resources.start()
    assert resources.wait_for_refresh(timeout=0.5)
    snapshot = resources.refresh_if_stale()

    assert snapshot.status == "ready"
    assert snapshot.retrieved_guard == "ready"
    assert calls == ["database", "index", "models", "identity", "retrieved_guard"]
    resources.close()


def test_guard_probe_failure_is_safe_and_keeps_other_probe_results() -> None:
    calls: list[str] = []

    def guard_probe() -> None:
        calls.append("retrieved_guard")
        raise RuntimeError(
            "invalid rules at D:/vault/private-rules.json token=never-show"
        )

    resources = RuntimeResources(
        settings(),
        database_probe=lambda: calls.append("database"),
        index_probe=lambda: (calls.append("index"), index_info())[1],
        model_probe=lambda: calls.append("models"),
        guard_probe=guard_probe,
        identity_probe=lambda: calls.append("identity"),
        clock=lambda: 0.0,
    )

    resources.start()
    assert resources.wait_for_refresh(timeout=0.5)
    snapshot = resources.refresh_if_stale()
    serialized = snapshot.model_dump_json()

    assert snapshot.status == "not_ready"
    assert snapshot.retrieved_guard == "error"
    assert snapshot.checks == {
        "database": "ok",
        "index": "ok",
        "models": "ok",
        "identity": "ok",
    }
    assert snapshot.index is None
    assert calls == ["database", "index", "models", "identity", "retrieved_guard"]
    assert "vault" not in serialized
    assert "never-show" not in serialized
    assert "private-rules" not in serialized
    resources.close()


def test_identity_probe_failure_is_safe_and_fails_readiness() -> None:
    def identity_probe() -> None:
        raise RuntimeError("D:/private/jwks.json key=never-show")

    resources = RuntimeResources(
        settings(),
        database_probe=lambda: None,
        index_probe=index_info,
        model_probe=lambda: None,
        identity_probe=identity_probe,
        guard_probe=lambda: None,
    )

    resources.start()
    assert resources.wait_for_refresh(timeout=0.5)
    snapshot = resources.refresh_if_stale()
    serialized = snapshot.model_dump_json()

    assert snapshot.status == "not_ready"
    assert snapshot.checks["identity"] == "error"
    assert snapshot.index is None
    assert "jwks" not in serialized.casefold()
    assert "never-show" not in serialized.casefold()
    resources.close()


def test_default_container_rejects_invalid_guard_policy_with_safe_error() -> None:
    def invalid_guard_policy() -> None:
        raise RuntimeError("D:/secret/rules.py api_key=never-show")

    with pytest.raises(
        RuntimeError,
        match="retrieved-content guard policy validation failed",
    ) as exc_info:
        build_service_container(
            Settings(_env_file=None),
            guard_validator=invalid_guard_policy,
        )

    assert "secret" not in str(exc_info.value).casefold()
    assert "never-show" not in str(exc_info.value).casefold()


def test_detector_policy_validator_rejects_ruleset_digest_drift(
    monkeypatch,
) -> None:
    validator = retrieved_content_module.validate_retrieved_content_guard
    validator()
    monkeypatch.setattr(
        retrieved_content_module,
        "RULE_SET_SHA256",
        "0" * 64,
    )

    with pytest.raises(RuntimeError, match="retrieved-content guard policy is invalid"):
        validator()


def test_detector_policy_validator_rejects_missing_runtime_rule(
    monkeypatch,
) -> None:
    rules = dict(retrieved_content_module.RULE_SPECS)
    rules.pop("RCG-INSTRUCTION-OVERRIDE-001")
    monkeypatch.setattr(
        retrieved_content_module,
        "RULE_SPECS",
        MappingProxyType(rules),
    )

    with pytest.raises(RuntimeError, match="retrieved-content guard policy is invalid"):
        retrieved_content_module.validate_retrieved_content_guard()


def test_database_initialization_uses_container_settings_and_keyed_digest_provider(
    monkeypatch,
) -> None:
    configured = SimpleNamespace(
        sqlite_path="container-owned.db",
        sqlite_timeout_seconds=1.0,
        readiness_ttl_seconds=5.0,
    )
    observed: dict[str, object] = {}

    def digest(kind, value):
        return "a" * 64

    def fake_init(settings, *, content_digest):
        observed["init_settings"] = settings
        observed["content_digest"] = content_digest

    def fake_check(settings):
        observed["check_settings"] = settings
        return True

    monkeypatch.setattr(resources_module, "init_db", fake_init)
    monkeypatch.setattr(resources_module, "check_db", fake_check)
    resources = RuntimeResources(
        configured,
        database_content_digest=digest,
        index_probe=index_info,
        model_probe=lambda: None,
        identity_probe=lambda: None,
    )

    resources._initialize_database()
    resources._probe_database()

    assert observed == {
        "init_settings": configured,
        "content_digest": digest,
        "check_settings": configured,
    }


def test_readiness_refresh_never_repeats_database_initialization() -> None:
    clock = MutableClock()
    calls = {"initialize": 0, "probe": 0}

    def initialize() -> None:
        calls["initialize"] += 1

    def probe() -> None:
        calls["probe"] += 1

    resources = RuntimeResources(
        settings(),
        database_initializer=initialize,
        database_probe=probe,
        index_probe=index_info,
        model_probe=lambda: None,
        identity_probe=lambda: None,
        clock=clock,
    )

    resources.start()
    assert resources.wait_for_refresh(timeout=0.5)
    assert resources.refresh_in_background()
    assert resources.wait_for_refresh(timeout=0.5)
    assert resources.refresh_in_background()
    assert resources.wait_for_refresh(timeout=0.5)

    assert calls == {"initialize": 1, "probe": 3}
    resources.close()


def test_database_initialization_failure_remains_not_ready_without_retry() -> None:
    clock = MutableClock()
    calls = 0

    def initialize() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("migration unavailable")

    resources = RuntimeResources(
        settings(),
        database_initializer=initialize,
        index_probe=index_info,
        model_probe=lambda: None,
        identity_probe=lambda: None,
        clock=clock,
    )

    resources.start()
    assert resources.wait_for_refresh(timeout=0.5)
    first = resources.refresh_if_stale()
    assert resources.refresh_in_background()
    assert resources.wait_for_refresh(timeout=0.5)
    second = resources.refresh_if_stale()

    assert first.checks["database"] == "error"
    assert second.checks["database"] == "error"
    assert calls == 1
    resources.close()


def test_model_probe_requires_embedding_chat_and_evidence_models(monkeypatch) -> None:
    configured = SimpleNamespace(
        readiness_ttl_seconds=5.0,
        llm_base_url="http://127.0.0.1:11434/v1",
        readiness_probe_timeout_seconds=1.0,
        readiness_model_load_timeout_seconds=10.0,
        embedding_model="bge-m3",
        chat_model="qwen-chat:latest",
        evidence_model="qwen-evidence:latest",
    )
    available = ["bge-m3", "qwen-chat"]

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    class FakeSession:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url, *, timeout):
            assert url == "http://127.0.0.1:11434/api/tags"
            assert 0 < timeout.total <= 10.0
            assert timeout.connect_timeout <= 1.0
            assert self.trust_env is False
            return FakeResponse(
                {"models": [{"name": name} for name in available]}
            )

        def post(self, url, *, json, timeout):
            assert 0 < timeout.total <= 10.0
            assert timeout.connect_timeout <= 1.0
            if url.endswith("/api/embed"):
                return FakeResponse({"embeddings": [[0.1] * 1024]})
            assert url.endswith("/api/chat")
            return FakeResponse({"message": {"content": "OK"}})

    monkeypatch.setattr(resources_module.requests, "Session", FakeSession)
    resources = RuntimeResources(
        configured,
        database_probe=lambda: None,
        index_probe=index_info,
        identity_probe=lambda: None,
    )

    with pytest.raises(RuntimeError, match="required models"):
        resources._probe_models(index_info())

    available.append("qwen-evidence")
    resources._probe_models(index_info())


def test_model_probe_fails_when_a_listed_model_cannot_be_loaded(
    monkeypatch,
) -> None:
    configured = SimpleNamespace(
        readiness_ttl_seconds=5.0,
        llm_base_url="http://127.0.0.1:11434/v1",
        readiness_probe_timeout_seconds=1.0,
        readiness_model_load_timeout_seconds=10.0,
        embedding_model="bge-m3",
        chat_model="qwen-chat:latest",
        evidence_model="qwen-evidence:latest",
    )
    post_calls: list[tuple[str, dict]] = []

    class FakeResponse:
        def __init__(self, payload, *, failure: str | None = None):
            self._payload = payload
            self._failure = failure

        def raise_for_status(self) -> None:
            if self._failure is not None:
                raise RuntimeError(self._failure)

        def json(self):
            return self._payload

    class FakeSession:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, _url, *, timeout):
            assert 0 < timeout.total <= 10.0
            assert timeout.connect_timeout <= 1.0
            return FakeResponse(
                {
                    "models": [
                        {"name": "bge-m3"},
                        {"name": "qwen-chat"},
                        {"name": "qwen-evidence"},
                    ]
                }
            )

        def post(self, url, *, json, timeout):
            assert 0 < timeout.total <= 10.0
            assert timeout.connect_timeout <= 1.0
            post_calls.append((url, json))
            failure = (
                "model load failed"
                if json["model"] == "qwen-evidence:latest"
                else None
            )
            if url.endswith("/api/embed"):
                return FakeResponse(
                    {"embeddings": [[0.1] * 1024]},
                    failure=failure,
                )
            return FakeResponse(
                {"message": {"content": "OK"}},
                failure=failure,
            )

    monkeypatch.setattr(resources_module.requests, "Session", FakeSession)
    resources = RuntimeResources(
        configured,
        database_probe=lambda: None,
        index_probe=index_info,
        identity_probe=lambda: None,
    )

    with pytest.raises(RuntimeError, match="model load failed"):
        resources._probe_models(index_info())

    assert post_calls == [
        (
            "http://127.0.0.1:11434/api/embed",
            {"model": "bge-m3", "input": "readiness"},
        ),
        (
            "http://127.0.0.1:11434/api/chat",
            {
                "model": "qwen-chat:latest",
                "messages": [
                    {
                        "role": "user",
                        "content": "Reply with OK.",
                    }
                ],
                "stream": False,
                "keep_alive": "5m",
                "options": {"temperature": 0},
            },
        ),
        (
            "http://127.0.0.1:11434/api/chat",
            {
                "model": "qwen-evidence:latest",
                "messages": [
                    {
                        "role": "user",
                        "content": "Reply with OK.",
                    }
                ],
                "stream": False,
                "keep_alive": "5m",
                "options": {"temperature": 0},
            },
        ),
    ]


@pytest.mark.parametrize(
    "embedding",
    [
        [0.1, 0.2],
        [0.1] * 1023 + [float("nan")],
        [0.1] * 1023 + [float("inf")],
    ],
    ids=["wrong-dimension", "nan", "infinity"],
)
def test_model_probe_rejects_embedding_contract_drift(
    monkeypatch,
    embedding,
) -> None:
    configured = SimpleNamespace(
        readiness_ttl_seconds=5.0,
        llm_base_url="http://127.0.0.1:11434/v1",
        readiness_probe_timeout_seconds=1.0,
        readiness_model_load_timeout_seconds=10.0,
        embedding_model="bge-m3",
        chat_model="qwen-chat",
        evidence_model="qwen-evidence",
    )

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    class FakeSession:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, _url, *, timeout):
            return FakeResponse(
                {
                    "models": [
                        {"name": "bge-m3"},
                        {"name": "qwen-chat"},
                        {"name": "qwen-evidence"},
                    ]
                }
            )

        def post(self, url, *, json, timeout):
            if url.endswith("/api/embed"):
                return FakeResponse({"embeddings": [embedding]})
            return FakeResponse({"message": {"content": "OK"}})

    monkeypatch.setattr(resources_module.requests, "Session", FakeSession)
    resources = RuntimeResources(
        configured,
        database_probe=lambda: None,
        index_probe=index_info,
        identity_probe=lambda: None,
    )

    with pytest.raises(RuntimeError, match="embedding model probe"):
        resources._probe_models(index_info())


def test_model_probe_uses_one_total_deadline_across_all_requests(
    monkeypatch,
) -> None:
    deadline_clock = MutableClock()
    configured = SimpleNamespace(
        readiness_ttl_seconds=5.0,
        llm_base_url="http://127.0.0.1:11434/v1",
        readiness_probe_timeout_seconds=1.0,
        readiness_model_load_timeout_seconds=10.0,
        embedding_model="bge-m3",
        chat_model="qwen-chat",
        evidence_model="qwen-evidence",
    )
    requested_urls: list[str] = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    class FakeSession:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url, *, timeout):
            requested_urls.append(url)
            deadline_clock.value = 4.0
            return FakeResponse(
                {
                    "models": [
                        {"name": "bge-m3"},
                        {"name": "qwen-chat"},
                        {"name": "qwen-evidence"},
                    ]
                }
            )

        def post(self, url, *, json, timeout):
            requested_urls.append(url)
            deadline_clock.value += 4.0
            if url.endswith("/api/embed"):
                return FakeResponse({"embeddings": [[0.1] * 1024]})
            return FakeResponse({"message": {"content": "OK"}})

    monkeypatch.setattr(resources_module.requests, "Session", FakeSession)
    resources = RuntimeResources(
        configured,
        database_probe=lambda: None,
        index_probe=index_info,
        identity_probe=lambda: None,
        deadline_clock=deadline_clock,
    )

    with pytest.raises(RuntimeError, match="deadline exceeded"):
        resources._probe_models(index_info())

    assert requested_urls == [
        "http://127.0.0.1:11434/api/tags",
        "http://127.0.0.1:11434/api/embed",
        "http://127.0.0.1:11434/api/chat",
    ]
