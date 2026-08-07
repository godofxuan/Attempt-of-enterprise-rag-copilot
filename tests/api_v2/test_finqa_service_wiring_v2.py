from __future__ import annotations

import json
import threading
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.agent.controller_v2 import ControllerState
from app.config import Settings
from app.domain.agent import AgentBudget, BudgetState
from app.domain.evidence import AnswerResponse
from app.domain.queries import QueryAnalysis, UserContext
from app.domain.retrieved_security import AdmittedEvidenceChunk
from app.external_datasets.finqa_admitted_context_v1 import (
    FinQATypedObservationResponseBuilderV1,
)
from app.external_datasets.finqa_shadow_worker_v1 import (
    FinQAIsolatedShadowObservationV1,
)
from app.main_v2 import create_app_v2
from app.runtime.finqa_service_v2 import (
    FinQAServiceAssemblyV2,
    build_finqa_service_assembly_v2,
    build_finqa_v2_agent_runner,
    safe_finqa_service_snapshot_v2,
)
from app.security.retrieved_content import RetrievedContentGuard
from tests.api_v2.helpers import OPERATOR_HEADERS, USER_HEADERS, make_container
from tests.v2_test_support import search_hit


QUESTION = "What was the percentage change in revenue from 2022 to 2023?"
PRIVATE_TEXT = "Revenue was $100 million in 2022 and $125 million in 2023."
PRIMARY = AnswerResponse(
    mode="not_found",
    answer="No supported primary answer was found.",
    stop_reason="not_found",
    warnings=["primary warning remains unchanged"],
    trace={"intent": "fact", "steps": [], "budget": {}},
)


def _wait_until(predicate, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition did not become true")


def _admitted() -> AdmittedEvidenceChunk:
    guard = RetrievedContentGuard()
    return AdmittedEvidenceChunk(
        hit=search_hit(
            chunk_id="chunk-e19-finance",
            doc_id="doc-e19-finance",
            source_path="documents/e19-finance.md",
            matched_text=PRIVATE_TEXT,
            context_text=PRIVATE_TEXT,
            fact_ids=["fact-e19-finance"],
        ),
        matched_decision=guard.scan(PRIVATE_TEXT),
        metadata_decision=guard.scan("documents e19 finance"),
    )


def _state(user: UserContext) -> ControllerState:
    analysis = QueryAnalysis(
        original_question=QUESTION,
        intent="fact",
        entities=[],
        search_queries=[QUESTION],
        required_aspects=["answer"],
        source="rules",
    )
    return ControllerState(
        analysis=analysis,
        user=user,
        top_k=5,
        budget_state=BudgetState(
            budget=AgentBudget(),
            deadline_at_ms=1_000,
        ),
        evidence_by_aspect={"answer": [_admitted()]},
    )


class _Delegate:
    def build(self, **_kwargs) -> AnswerResponse:
        return PRIMARY


class _ControlledRunner:
    def __init__(self, coordinator) -> None:
        self.builder = FinQATypedObservationResponseBuilderV1(
            delegate=_Delegate(),
            coordinator=coordinator,
        )
        self.calls = 0

    def run(
        self,
        question: str,
        user: UserContext,
        top_k: int | None = None,
    ) -> AnswerResponse:
        self.calls += 1
        return self.builder.build(
            question=question,
            state=_state(user),
            mode=PRIMARY.mode,
            stop_reason=PRIMARY.stop_reason,
            trace=PRIMARY.trace,
        )


class _Worker:
    def __init__(
        self,
        *,
        fail_start: bool = False,
        fail_observe: bool = False,
        block: bool = False,
    ) -> None:
        self.fail_start = fail_start
        self.fail_observe = fail_observe
        self.block = block
        self.release = threading.Event()
        self.started_observing = threading.Event()
        self.start_calls = 0
        self.observe_calls = 0
        self.close_calls = 0

    def start(self) -> bool:
        self.start_calls += 1
        return not self.fail_start

    def observe(self, *, primary, question, skeleton, catalog):
        self.observe_calls += 1
        self.started_observing.set()
        if self.block:
            self.release.wait(timeout=2)
        if self.fail_observe:
            raise RuntimeError(f"private worker failure: {question}")
        role_count = len(primary.result.selections.selections)
        return FinQAIsolatedShadowObservationV1(
            outcome="MATCH",
            role_count=role_count,
            changed_role_count=0,
            common_descriptor_count_at_4=role_count * 4,
            latency_ms=0.1,
            worker_restarted=False,
        )

    def close(self) -> None:
        self.release.set()
        self.close_calls += 1


def _assembly(
    *,
    mode: str,
    worker: _Worker | None = None,
    queue_capacity: int = 4,
) -> tuple[FinQAServiceAssemblyV2, _Worker, _ControlledRunner]:
    settings = Settings(
        _env_file=None,
        api_request_deadline_ms=5_000,
        dark_observation_mode=mode,
        dark_observation_sample_basis_points=(
            10_000 if mode == "LOCAL_TEST_ONLY" else 0
        ),
        dark_observation_worker_count=1,
        dark_observation_queue_capacity=queue_capacity,
        dark_observation_deadline_ms=1_000,
    )
    active_worker = worker or _Worker()
    base = replace(make_container(), settings=settings)
    initial = build_finqa_service_assembly_v2(
        settings,
        base_container=base,
        shadow_worker=active_worker,
        agent_runner=_Delegate(),
    )
    controlled = _ControlledRunner(initial.runtime.coordinator)
    return replace(initial, agent_runner=controlled), active_worker, controlled


def _post(client: TestClient, request_id: str):
    return client.post(
        "/agent/v2/chat",
        headers={**USER_HEADERS, "X-Request-ID": request_id},
        json={"question": QUESTION, "top_k": 5},
    )


def test_off_and_local_test_only_return_exact_response_and_receipt() -> None:
    off, off_worker, _ = _assembly(mode="OFF")
    enabled, enabled_worker, _ = _assembly(mode="LOCAL_TEST_ONLY")

    with TestClient(create_app_v2(off)) as off_client:
        off_response = _post(off_client, "req-e19-paired")
        off_metrics = off_client.get(
            "/observability/metrics", headers=OPERATOR_HEADERS
        ).json()["finqa_typed_observation"]
    with TestClient(create_app_v2(enabled)) as enabled_client:
        enabled_response = _post(enabled_client, "req-e19-paired")
        _wait_until(lambda: enabled_worker.observe_calls == 1)
        enabled_metrics = enabled_client.get(
            "/observability/metrics", headers=OPERATOR_HEADERS
        ).json()["finqa_typed_observation"]

    assert off_response.status_code == enabled_response.status_code == 200
    assert off_response.content == enabled_response.content
    assert off_response.headers["X-Feedback-Receipt"] == enabled_response.headers[
        "X-Feedback-Receipt"
    ]
    assert off_worker.start_calls == off_worker.observe_calls == 0
    assert off_metrics["mode"] == "OFF"
    assert off_metrics["preparation_latency_ms"]["count"] == 0
    assert enabled_worker.start_calls == enabled_worker.observe_calls == 1
    assert enabled_metrics["mode"] == "LOCAL_TEST_ONLY"
    assert enabled_metrics["legacy_generic_offer_calls"] == 0
    assert enabled_metrics["dark_observation"]["counters"]["offered_total"] == 1
    assert enabled_metrics["adapter"]["provider_outcomes"] == {"MATCH": 1}


def test_versioned_runner_wraps_primary_builder_at_controller_state_boundary() -> None:
    assembly, _, _ = _assembly(mode="OFF")
    runner = build_finqa_v2_agent_runner(
        settings=assembly.container.settings,
        coordinator=assembly.runtime.coordinator,
        registry=object(),  # type: ignore[arg-type]
        response_builder=_Delegate(),
    )

    assert isinstance(
        runner.response_builder,
        FinQATypedObservationResponseBuilderV1,
    )
    assert runner.response_builder.coordinator is assembly.runtime.coordinator


def test_provider_error_isolated_and_metrics_never_retain_content() -> None:
    assembly, worker, _ = _assembly(
        mode="LOCAL_TEST_ONLY",
        worker=_Worker(fail_observe=True),
    )

    with TestClient(create_app_v2(assembly)) as client:
        response = _post(client, "req-e19-provider-error")
        _wait_until(
            lambda: assembly.container.dark_observation.snapshot()["counters"][
                "provider_error_total"
            ]
            == 1
        )
        metrics = client.get(
            "/observability/metrics", headers=OPERATOR_HEADERS
        ).json()["finqa_typed_observation"]

    assert response.status_code == 200
    assert response.json()["answer"] == PRIMARY.answer
    assert worker.observe_calls == 1
    serialized = json.dumps(metrics, sort_keys=True)
    for forbidden in (
        QUESTION,
        PRIVATE_TEXT,
        PRIMARY.answer,
        "req-e19-provider-error",
        "tenant-one",
        "employee-one",
        "private worker failure",
    ):
        assert forbidden not in serialized
    assert metrics["adapter"]["failures"] == {"worker_error": 1}
    assert metrics["content_retained"] is False


def test_safe_snapshot_drops_unrecognized_counter_names_and_status(monkeypatch) -> None:
    assembly, _, _ = _assembly(mode="OFF")
    original = assembly.runtime.coordinator.snapshot

    def poisoned_snapshot():
        payload = original()
        payload["counters"] = {QUESTION: 1, "offer_disabled_total": 1}
        payload["adapter"]["failures"] = {PRIVATE_TEXT: 1, "worker_error": 1}
        payload["dark_observation"]["status"] = PRIVATE_TEXT
        return payload

    monkeypatch.setattr(assembly.runtime.coordinator, "snapshot", poisoned_snapshot)
    snapshot = safe_finqa_service_snapshot_v2(assembly.runtime)
    serialized = json.dumps(snapshot, sort_keys=True)

    assert QUESTION not in serialized
    assert PRIVATE_TEXT not in serialized
    assert snapshot["counters"] == {"offer_disabled_total": 1}
    assert snapshot["adapter"]["failures"] == {"worker_error": 1}
    assert snapshot["dark_observation"]["status"] == "UNAVAILABLE"


def test_backpressure_discards_only_rejected_context_and_shutdown_cleans() -> None:
    worker = _Worker(block=True)
    assembly, _, _ = _assembly(
        mode="LOCAL_TEST_ONLY",
        worker=worker,
        queue_capacity=1,
    )

    with TestClient(create_app_v2(assembly)) as client:
        first = _post(client, "req-e19-active")
        assert worker.started_observing.wait(timeout=1)
        second = _post(client, "req-e19-queued")
        third = _post(client, "req-e19-rejected")
        during = safe_finqa_service_snapshot_v2(assembly.runtime)
        worker.release.set()
        _wait_until(
            lambda: assembly.container.dark_observation.snapshot()["counters"][
                "completed_total"
            ]
            == 2
        )

    assert first.status_code == second.status_code == third.status_code == 200
    assert during["dark_observation"]["counters"]["backpressure_total"] == 1
    assert during["resolver"]["pending_context_count"] == 1
    after = safe_finqa_service_snapshot_v2(assembly.runtime)
    assert after["status"] == "CLOSED"
    assert after["resolver"]["pending_context_count"] == 0
    assert worker.close_calls == 1


def test_local_test_startup_fails_closed_when_worker_cannot_start() -> None:
    assembly, worker, _ = _assembly(
        mode="LOCAL_TEST_ONLY",
        worker=_Worker(fail_start=True),
    )

    with pytest.raises(RuntimeError, match="E19 versioned service startup failed"):
        with TestClient(create_app_v2(assembly)):
            pass

    snapshot = safe_finqa_service_snapshot_v2(assembly.runtime)
    assert worker.start_calls == 1
    assert worker.close_calls == 1
    assert snapshot["status"] == "FAILED"
    assert snapshot["lifecycle"]["startup_failure_total"] == 1
    assert assembly.container.resources.close_calls == 1


def test_default_off_runtime_starts_no_worker_and_closes_idempotently() -> None:
    assembly, worker, _ = _assembly(mode="OFF")

    with TestClient(create_app_v2(assembly)) as client:
        response = _post(client, "req-e19-off")
        assert response.status_code == 200
        assert worker.start_calls == 0

    assembly.runtime.close()
    assert worker.observe_calls == 0
    assert worker.close_calls == 1
    assert assembly.container.resources.close_calls == 1
