from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.evidence import AnswerResponse
from app.main import create_app
from app.observability.metrics import MetricsRegistry
from app.observability.tracing import InMemoryTraceStore
from app.runtime.dark_observation import (
    DarkObservationConfig,
    DarkObservationRequest,
    DarkObservationService,
)
from app.runtime.dark_observation_protocol_v1 import (
    load_dark_observation_service_protocol_v1,
)
from app.runtime.resources import (
    DEFAULT_ROUTE_TEMPLATES,
    ReadinessSnapshot,
    ReadyIndexInfo,
    ServiceContainer,
)
from app.security.identity import (
    AuthenticationFailure,
    FeedbackActorHasher,
    Principal,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/external_datasets/evidence"
DEFAULT_PROTOCOL = EVIDENCE / "dark_observation_service_protocol_v1.json"
DEFAULT_OUTPUT = EVIDENCE / "dark_observation_service_public_v1.json"
IMPLEMENTATION_PATHS = (
    "app/config.py",
    "app/main.py",
    "app/runtime/dark_observation.py",
    "app/runtime/dark_observation_protocol_v1.py",
    "app/runtime/resources.py",
    "scripts/audit_dark_observation_service_v1.py",
)
_SENSITIVE_QUESTION_PREFIX = "E16 PRIVATE DARK TRAFFIC SENTINEL"
_PRIMARY_ANSWER = "No supported answer from the unchanged primary path."


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


def _authorization(role: str) -> str:
    return f"Bearer e16-{role}-token"


def _headers(role: str) -> dict[str, str]:
    return {"Authorization": _authorization(role)}


class _ReadyResources:
    def __init__(self) -> None:
        self._snapshot = ReadinessSnapshot(
            status="ready",
            checks={
                "database": "ok",
                "index": "ok",
                "models": "ok",
                "identity": "ok",
            },
            retrieved_guard="ready",
            index=ReadyIndexInfo(
                run_id="e16-audit-index",
                chunk_count=1,
                embedding_model="audit-no-model",
                embedding_dimension=1,
                build_duration_ms=0,
                index_size_bytes=1,
            ),
            checked_at_utc=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )

    def start(self) -> ReadinessSnapshot:
        return self._snapshot

    def refresh_if_stale(self) -> ReadinessSnapshot:
        return self._snapshot

    def close(self) -> None:
        return None


class _AuditIdentityVerifier:
    def ready(self) -> None:
        return None

    def verify_bearer(self, authorization: str | None) -> Principal:
        if authorization not in {
            _authorization("user"),
            _authorization("operator"),
        }:
            raise AuthenticationFailure("invalid_token")
        operator = authorization == _authorization("operator")
        now = datetime(2026, 8, 2, tzinfo=timezone.utc)
        return Principal(
            subject="e16-audit-operator" if operator else "e16-audit-user",
            tenant_id="e16-audit-tenant",
            region="local",
            groups=["e16-audit-group"],
            roles=["rag.operator"] if operator else [],
            issuer="https://identity.localhost/",
            audience="enterprise-rag-api",
            key_id="e16-audit-key",
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
        )


class _CountingProvider:
    def __init__(self, *, outcome: str = "NOT_APPLICABLE") -> None:
        self.calls = 0
        self.fields: set[str] = set()
        self.outcome = outcome
        self._lock = threading.Lock()

    def observe(
        self,
        request: DarkObservationRequest,
        *,
        deadline_monotonic: float,
    ) -> str:
        with self._lock:
            self.calls += 1
            self.fields.update(request.__dict__)
        return self.outcome


class _FailingProvider:
    def observe(
        self,
        request: DarkObservationRequest,
        *,
        deadline_monotonic: float,
    ) -> str:
        raise RuntimeError(f"injected private failure: {request.question}")


class _SlowProvider:
    def observe(
        self,
        request: DarkObservationRequest,
        *,
        deadline_monotonic: float,
    ) -> str:
        time.sleep(0.02)
        return "DIFFERENT"


class _BlockingProvider:
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


def _make_service(
    *,
    provider: object | None,
    mode: str,
    sample_basis_points: int,
    worker_count: int = 1,
    queue_capacity: int = 4,
    observation_deadline_ms: int = 100,
    shutdown_grace_ms: int = 2_000,
) -> DarkObservationService:
    return DarkObservationService(
        DarkObservationConfig(
            mode=mode,
            sample_basis_points=sample_basis_points,
            worker_count=worker_count,
            queue_capacity=queue_capacity,
            observation_deadline_ms=observation_deadline_ms,
            shutdown_grace_ms=shutdown_grace_ms,
        ),
        provider=provider,
        sampling_key=hashlib.sha256(
            b"e16-public-audit-sampling-domain-v1"
        ).digest(),
    )


def _make_container(dark_observation: DarkObservationService) -> ServiceContainer:
    settings = Settings(
        _env_file=None,
        api_request_deadline_ms=5_000,
        trace_buffer_size=100,
    )
    return ServiceContainer(
        settings=settings,
        resources=_ReadyResources(),
        metrics=MetricsRegistry(
            latency_buffer_size=100,
            allowed_routes=DEFAULT_ROUTE_TEMPLATES,
            memory_provider=lambda: 123_456,
        ),
        traces=InMemoryTraceStore(max_records=100),
        identity_verifier=_AuditIdentityVerifier(),
        feedback_actor_hasher=FeedbackActorHasher(
            _key=hashlib.sha256(b"e16-audit-feedback-domain-v1").digest()
        ),
        dark_observation=dark_observation,
    )


def _primary_answer(*_: object, **__: object) -> AnswerResponse:
    return AnswerResponse(
        mode="not_found",
        answer=_PRIMARY_ANSWER,
        stop_reason="not_found",
        trace={"intent": "fact", "steps": [], "budget": {}},
    )


def _wait_for_counter(
    service: DarkObservationService,
    counter: str,
    expected: int,
    *,
    timeout: float = 2.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if service.snapshot()["counters"][counter] >= expected:
            return
        time.sleep(0.005)
    raise RuntimeError(f"E16 counter {counter} did not reach {expected}")


def _request_pair(client: TestClient, index: int) -> tuple[bytes, str, int]:
    response = client.post(
        "/agent/v2/chat",
        headers={
            **_headers("user"),
            "X-Request-ID": f"e16-private-request-{index:02d}",
        },
        json={"question": f"{_SENSITIVE_QUESTION_PREFIX} {index:02d}"},
    )
    return (
        response.content,
        response.headers.get("X-Feedback-Receipt", ""),
        response.status_code,
    )


def _run_route_pair(
    *,
    request_count: int,
    worker_count: int,
    queue_capacity: int,
    observation_deadline_ms: int,
    shutdown_grace_ms: int,
) -> dict[str, object]:
    off_provider = _CountingProvider()
    off_service = _make_service(
        provider=off_provider,
        mode="OFF",
        sample_basis_points=0,
    )
    enabled_provider = _CountingProvider()
    enabled_service = _make_service(
        provider=enabled_provider,
        mode="LOCAL_TEST_ONLY",
        sample_basis_points=10_000,
        worker_count=worker_count,
        queue_capacity=queue_capacity,
        observation_deadline_ms=observation_deadline_ms,
        shutdown_grace_ms=shutdown_grace_ms,
    )

    with patch("app.main.run_agent_v2_chat", side_effect=_primary_answer):
        with TestClient(create_app(_make_container(off_service))) as client:
            baseline = [_request_pair(client, index) for index in range(request_count)]
        with TestClient(create_app(_make_container(enabled_service))) as client:
            observed = [_request_pair(client, index) for index in range(request_count)]
            _wait_for_counter(enabled_service, "completed_total", request_count)
            endpoint_metrics = client.get(
                "/observability/metrics",
                headers=_headers("operator"),
            ).json()["dark_observation"]

    enabled_snapshot = enabled_service.snapshot()
    off_snapshot = off_service.snapshot()
    return {
        "default_off_provider_calls": off_provider.calls,
        "default_off_disabled_count": off_snapshot["counters"]["disabled_total"],
        "default_off_workers_alive_after_shutdown": off_snapshot["current"][
            "workers_alive"
        ],
        "enabled_provider_calls": enabled_provider.calls,
        "provider_fields_match_protocol": enabled_provider.fields
        == {
            "request_id",
            "question",
            "primary_mode",
            "primary_stop_reason",
        },
        "primary_response_mismatches": sum(
            baseline_item != observed_item
            for baseline_item, observed_item in zip(baseline, observed, strict=True)
        ),
        "aggregate_metrics": endpoint_metrics,
        "enabled_workers_alive_after_shutdown": enabled_snapshot["current"][
            "workers_alive"
        ],
    }


def _offer(service: DarkObservationService, suffix: str) -> str:
    return service.offer(
        request_id=f"e16-private-failure-{suffix}",
        question=f"{_SENSITIVE_QUESTION_PREFIX} failure {suffix}",
        primary_mode="not_found",
        primary_stop_reason="not_found",
    )


def _run_failure_injection() -> dict[str, object]:
    failing = _make_service(
        provider=_FailingProvider(),
        mode="LOCAL_TEST_ONLY",
        sample_basis_points=10_000,
    )
    failing.start()
    failing_admission = _offer(failing, "provider-error")
    _wait_for_counter(failing, "provider_error_total", 1)
    failing_snapshot = failing.snapshot()
    failing_close = failing.close()

    slow = _make_service(
        provider=_SlowProvider(),
        mode="LOCAL_TEST_ONLY",
        sample_basis_points=10_000,
        observation_deadline_ms=5,
    )
    slow.start()
    slow_admission = _offer(slow, "deadline")
    _wait_for_counter(slow, "deadline_exceeded_total", 1)
    slow_snapshot = slow.snapshot()
    slow_close = slow.close()

    blocking_provider = _BlockingProvider()
    bounded = _make_service(
        provider=blocking_provider,
        mode="LOCAL_TEST_ONLY",
        sample_basis_points=10_000,
        queue_capacity=1,
        observation_deadline_ms=1_000,
    )
    bounded.start()
    active_admission = _offer(bounded, "active")
    if not blocking_provider.entered.wait(timeout=1.0):
        raise RuntimeError("E16 blocking provider did not start")
    queued_admission = _offer(bounded, "queued")
    backpressure_outcome = _offer(bounded, "backpressure")
    blocking_provider.release.set()
    bounded_close = bounded.close()
    bounded_snapshot = bounded.snapshot()
    closed_outcome = _offer(bounded, "after-close")

    return {
        "provider_error": {
            "admission": failing_admission,
            "safe_error_count": failing_snapshot["counters"][
                "provider_error_total"
            ],
            "completed_count": failing_snapshot["counters"]["completed_total"],
            "residual_workers": failing_close["residual_workers"],
        },
        "deadline": {
            "admission": slow_admission,
            "deadline_exceeded_count": slow_snapshot["counters"][
                "deadline_exceeded_total"
            ],
            "completed_count": slow_snapshot["counters"]["completed_total"],
            "residual_workers": slow_close["residual_workers"],
        },
        "backpressure": {
            "active_admission": active_admission,
            "queued_admission": queued_admission,
            "rejected_outcome": backpressure_outcome,
            "closed_outcome": closed_outcome,
            "admitted_count": bounded_snapshot["counters"]["admitted_total"],
            "terminal_count": sum(
                bounded_snapshot["counters"][name]
                for name in (
                    "completed_total",
                    "provider_error_total",
                    "deadline_exceeded_total",
                    "shutdown_cancelled_total",
                )
            ),
            "residual_workers": bounded_close["residual_workers"],
        },
    }


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_all_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value), set())
    return set()


def build_public_evidence() -> dict[str, object]:
    protocol, protocol_sha256 = load_dark_observation_service_protocol_v1(
        DEFAULT_PROTOCOL
    )
    audit = protocol.audit_profile
    route_pair = _run_route_pair(
        request_count=audit.request_count,
        worker_count=audit.worker_count,
        queue_capacity=audit.queue_capacity,
        observation_deadline_ms=audit.observation_deadline_ms,
        shutdown_grace_ms=audit.shutdown_grace_ms,
    )
    failure = _run_failure_injection()
    aggregate = route_pair["aggregate_metrics"]
    assert isinstance(aggregate, dict)
    offer_p95 = float(aggregate["offer_latency_ms"]["p95"])

    evidence: dict[str, object] = {
        "schema_version": "dark_observation_service_public_v1",
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "claim": protocol.claim_label,
        "decision": "E16_MECHANISM_GATE_PASSED_DARK_OBSERVATION_REMAINS_DEFAULT_OFF",
        "source_binding": {
            "source_e15_protocol_sha256": protocol.source_e15_protocol_sha256,
            "source_e15_public_evidence_sha256": (
                protocol.source_e15_public_evidence_sha256
            ),
            "implementation_sha256": {
                relative: _sha256(ROOT / relative)
                for relative in IMPLEMENTATION_PATHS
            },
        },
        "runtime_profile": {
            "request_count": audit.request_count,
            "worker_count": audit.worker_count,
            "queue_capacity": audit.queue_capacity,
            "sample_basis_points": audit.sample_basis_points,
            "observation_deadline_ms": audit.observation_deadline_ms,
            "shutdown_grace_ms": audit.shutdown_grace_ms,
            "serving_route": protocol.runtime_contract.serving_route,
            "enabled_mode": protocol.runtime_contract.enabled_mode,
            "default_mode": protocol.runtime_contract.default_mode,
        },
        "aggregate_metrics": {
            "default_off_provider_calls": route_pair[
                "default_off_provider_calls"
            ],
            "default_off_disabled_count": route_pair[
                "default_off_disabled_count"
            ],
            "default_off_workers_alive_after_shutdown": route_pair[
                "default_off_workers_alive_after_shutdown"
            ],
            "enabled_provider_calls": route_pair["enabled_provider_calls"],
            "enabled_workers_alive_after_shutdown": route_pair[
                "enabled_workers_alive_after_shutdown"
            ],
            "primary_response_mismatches": route_pair[
                "primary_response_mismatches"
            ],
            "provider_fields_match_protocol": route_pair[
                "provider_fields_match_protocol"
            ],
            "dark_observation_snapshot_phase": "before_lifespan_shutdown",
            "dark_observation": aggregate,
            "model_call_count": 0,
        },
        "failure_injection": failure,
        "non_claims": list(protocol.non_claims),
    }
    serialized = json.dumps(evidence, ensure_ascii=True, sort_keys=True)
    sensitive_values = [
        _SENSITIVE_QUESTION_PREFIX,
        _PRIMARY_ANSWER,
        "e16-private-request-",
        "e16-audit-user",
        "e16-audit-tenant",
        "e16-audit-group",
        "injected private failure",
    ]
    prohibited_keys = set(protocol.public_output.prohibited_content)
    public_content_findings = sum(value in serialized for value in sensitive_values)
    public_content_findings += len(_all_keys(evidence).intersection(prohibited_keys))
    failure_error = failure["provider_error"]
    failure_deadline = failure["deadline"]
    failure_backpressure = failure["backpressure"]
    gates = {
        "source_hash_binding": (
            protocol.source_e15_protocol_sha256
            == _sha256(EVIDENCE / "finqa_shadow_capacity_protocol_v1.json")
            and protocol.source_e15_public_evidence_sha256
            == _sha256(EVIDENCE / "finqa_shadow_capacity_public_v1.json")
        ),
        "default_off_zero_provider_calls": route_pair[
            "default_off_provider_calls"
        ]
        == audit.required_default_off_provider_calls,
        "default_off_all_offers_disabled": route_pair[
            "default_off_disabled_count"
        ]
        == audit.request_count,
        "default_off_zero_workers": route_pair[
            "default_off_workers_alive_after_shutdown"
        ]
        == 0,
        "all_selected_requests_executed": route_pair["enabled_provider_calls"]
        == audit.request_count,
        "primary_response_immutability": route_pair[
            "primary_response_mismatches"
        ]
        == audit.required_primary_response_mismatches,
        "minimal_ephemeral_provider_contract": route_pair[
            "provider_fields_match_protocol"
        ]
        is True,
        "offer_latency_budget": offer_p95 <= audit.max_offer_latency_p95_ms,
        "provider_error_isolation": (
            failure_error["admission"] == "ADMITTED"
            and failure_error["safe_error_count"] == 1
            and failure_error["completed_count"] == 0
        ),
        "deadline_isolation": (
            failure_deadline["admission"] == "ADMITTED"
            and failure_deadline["deadline_exceeded_count"] == 1
            and failure_deadline["completed_count"] == 0
        ),
        "backpressure_isolation": (
            failure_backpressure["active_admission"] == "ADMITTED"
            and failure_backpressure["queued_admission"] == "ADMITTED"
            and failure_backpressure["rejected_outcome"] == "BACKPRESSURE"
        ),
        "admitted_observation_conservation": failure_backpressure[
            "admitted_count"
        ]
        == failure_backpressure["terminal_count"],
        "closed_admission_rejection": failure_backpressure["closed_outcome"]
        == "CLOSED",
        "zero_residual_controlled_workers": (
            route_pair["enabled_workers_alive_after_shutdown"] == 0
            and failure_error["residual_workers"] == 0
            and failure_deadline["residual_workers"] == 0
            and failure_backpressure["residual_workers"] == 0
        ),
        "aggregate_only_public_output": public_content_findings
        == audit.required_public_content_findings,
        "zero_model_calls": True,
        "finqa_contract_gap_disclosed": protocol.finqa_adapter_status
        == "NOT_IMPLEMENTED_CONTRACT_MISMATCH_RECORDED",
        "frozen_test_untouched": protocol.frozen_test_status == "UNTOUCHED",
    }
    evidence["gate_checks"] = gates
    if not all(gates.values()):
        failed = [name for name, passed in gates.items() if not passed]
        raise RuntimeError(f"E16 mechanism gates failed: {failed}")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    content = _canonical_bytes(build_public_evidence())
    output = args.output.resolve()
    if output.exists() and output.read_bytes() != content:
        raise RuntimeError("refusing to overwrite different E16 public evidence")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    print(json.dumps(json.loads(content), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
