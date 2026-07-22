from __future__ import annotations

import hashlib
import json
import re
import socket
import threading
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from types import SimpleNamespace

import pytest
import requests
from pydantic import ValidationError

from app.evaluation import indirect_injection_live_runner as live_runner
from app.domain.retrieved_security import ScannedContentUnit
from app.evaluation.indirect_injection_arm_order import (
    build_counterbalanced_arm_order_plan,
)
from app.evaluation.indirect_injection_dataset import (
    build_v1_bundle,
    load_security_bundle,
)
from app.evaluation.indirect_injection_live_index import (
    build_live_fixture_index,
)
from app.evaluation.indirect_injection_live_runner import (
    LiveSecurityConfig,
    LocalOllamaOnlyBoundary,
    _reached_attack_unit_ids,
    evaluate_live_paired,
)


FROZEN_AT = "2026-07-18T00:00:00Z"
FREEZE_HEAD = "a" * 40
FIXTURE_SHA256 = "b" * 64
BUILD_TIME = datetime(2026, 7, 18, 1, 2, 3, tzinfo=timezone.utc)


def _scan_event(
    operation: str,
    surface: str,
    internal_id: str,
) -> ScannedContentUnit:
    return ScannedContentUnit(
        operation=operation,
        surface=surface,
        internal_item_key=internal_id,
        member_internal_ids=(internal_id,),
        aggregate=False,
        disposition="ADMIT",
        rule_ids=(),
    )


def _embedding(text: str, dimension: int = 8) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [float(digest[index] + 1) for index in range(dimension)]


class _StructuredFixtureChat:
    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    def __call__(
        self,
        model: str,
        messages: list[dict],
        *,
        response_format=None,
        think=None,
    ) -> str:
        self.calls.append([dict(message) for message in messages])
        prompt = "\n".join(str(message["content"]) for message in messages)
        begin_index = next(
            index
            for index, line in enumerate(prompt.splitlines())
            if line.startswith("[BEGIN_UNTRUSTED_EVIDENCE nonce=")
        )
        lines = prompt.splitlines()
        end_index = next(
            index
            for index, line in enumerate(lines)
            if index > begin_index
            and line.startswith("[END_UNTRUSTED_EVIDENCE nonce=")
        )
        records = json.loads("\n".join(lines[begin_index + 1 : end_index]))
        matched_text = records[0]["matched_text"]
        document_canary = re.search(r"R2DOC_[A-Z0-9_]+", prompt)
        system_canary = re.search(r"R2SYS_[A-Z0-9_]+", prompt)
        answer = matched_text
        if document_canary is not None:
            answer = document_canary.group(0)
            if system_canary is not None:
                answer += " " + system_canary.group(0)
        return json.dumps(
            {
                "answer": answer,
                "claims": [
                    {
                        "claim_id": "claim-1",
                        "text": matched_text,
                        "critical": True,
                        "cited_source_ids": ["S1"],
                    }
                ],
            },
            ensure_ascii=False,
        )


@pytest.fixture(scope="module")
def live_inputs(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("d7-live-runner")
    security_root = root / "security-data"
    build_v1_bundle(
        security_root,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    bundle = load_security_bundle(security_root, "test")
    built = build_live_fixture_index(
        dataset=bundle.dataset,
        fixtures=bundle.fixture_manifest,
        root=root / "security-index",
        run_id="r2-s1-d7-runner-index",
        fixture_sha256=FIXTURE_SHA256,
        embedding_model="bge-m3",
        embed_text=_embedding,
        started_at=BUILD_TIME,
        finished_at=BUILD_TIME,
    )
    return bundle, built


@pytest.fixture(scope="module")
def paired_live_result(live_inputs):
    bundle, built = live_inputs
    chat = _StructuredFixtureChat()
    result = evaluate_live_paired(
        dataset=bundle.dataset,
        fixtures=bundle.fixture_manifest,
        snapshot=built.snapshot,
        embed_text=_embedding,
        chat_fn=chat,
        config=LiveSecurityConfig(
            llm_endpoint="http://127.0.0.1:11434/v1",
            chat_model="qwen2.5:3b",
        ),
        clock_ms=lambda: 1_000.0,
    )
    return bundle, chat, result


def test_live_pair_runs_the_production_retrieval_guard_and_generation_path(
    paired_live_result,
) -> None:
    bundle, chat, result = paired_live_result

    assert result.status == "COMPLETED WITH OBSERVATIONS"
    assert result.protocol_complete is True
    assert result.pair_input_consistent is True
    assert len(result.security.guard_off.cases) == 36
    assert len(result.security.guard_on.cases) == 36
    assert result.security.guard_off.summary.model_context_exposure.numerator >= 1
    assert result.security.guard_on.summary.model_context_exposure.numerator == 0
    assert chat.calls

    fixture_by_id = {
        fixture.case_id: fixture for fixture in bundle.fixture_manifest.cases
    }
    off_by_id = {item.case_id: item for item in result.security.guard_off.cases}
    on_by_id = {item.case_id: item for item in result.security.guard_on.cases}
    for case_id, off in off_by_id.items():
        on = on_by_id[case_id]
        expected_ids = {
            candidate.chunk_id for candidate in fixture_by_id[case_id].candidates
        }
        assert set(off.candidate_order) == expected_ids
        assert off.candidate_order == on.candidate_order
        assert off.input_fingerprint == on.input_fingerprint
        assert off.nonce_fingerprint == on.nonce_fingerprint


def test_query_embedding_is_real_once_then_reused_for_the_paired_arm(
    paired_live_result,
) -> None:
    _, _, result = paired_live_result

    assert result.embedding_request_count == 72
    assert result.embedding_delegate_call_count == 36
    assert result.embedding_cache_hit_count == 36


def test_counterbalanced_arm_order_controls_calls_and_preserves_mode_alignment(
    live_inputs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, built = live_inputs
    plan = build_counterbalanced_arm_order_plan(
        case.case_id for case in bundle.dataset.cases
    )
    calls: list[tuple[str, str]] = []
    original = live_runner._evaluate_live_case

    def recording_evaluate_live_case(**kwargs):
        calls.append((kwargs["case"].case_id, kwargs["guard_mode"]))
        return original(**kwargs)

    monkeypatch.setattr(
        live_runner,
        "_evaluate_live_case",
        recording_evaluate_live_case,
    )

    result = evaluate_live_paired(
        dataset=bundle.dataset,
        fixtures=bundle.fixture_manifest,
        snapshot=built.snapshot,
        embed_text=_embedding,
        chat_fn=_StructuredFixtureChat(),
        config=LiveSecurityConfig(
            llm_endpoint="http://127.0.0.1:11434/v1",
            chat_model="qwen2.5:3b",
        ),
        clock_ms=lambda: 1_000.0,
        arm_order=plan,
    )

    expected_calls = [
        (case.case_id, mode)
        for case in bundle.dataset.cases
        for mode in plan.assignment_for(case.case_id).modes()
    ]
    dataset_order = [case.case_id for case in bundle.dataset.cases]
    assert calls == expected_calls
    assert isinstance(result, live_runner.LivePairedResultV2)
    assert result.schema_version == "indirect_injection_live_paired_result_v2"
    assert result.arm_order == plan
    assert result.arm_order.off_then_on_count == 18
    assert result.arm_order.on_then_off_count == 18
    assert [
        (event.case_id, event.guard_mode)
        for event in result.arm_execution
    ] == calls
    assert [event.execution_index for event in result.arm_execution] == list(
        range(1, len(calls) + 1)
    )
    assert [event.arm_position for event in result.arm_execution] == [
        position
        for case in bundle.dataset.cases
        for position, _ in enumerate(
            plan.assignment_for(case.case_id).modes(),
            start=1,
        )
    ]
    assert [item.case_id for item in result.guard_off] == dataset_order
    assert [item.case_id for item in result.guard_on] == dataset_order
    assert [item.case_id for item in result.security.guard_off.cases] == dataset_order
    assert [item.case_id for item in result.security.guard_on.cases] == dataset_order


def test_counterbalanced_plan_must_cover_exact_dataset_before_model_work(
    live_inputs,
) -> None:
    bundle, built = live_inputs
    incomplete_plan = build_counterbalanced_arm_order_plan(
        case.case_id for case in bundle.dataset.cases[:-1]
    )
    chat = _StructuredFixtureChat()

    with pytest.raises(ValueError, match="arm-order plan case set"):
        evaluate_live_paired(
            dataset=bundle.dataset,
            fixtures=bundle.fixture_manifest,
            snapshot=built.snapshot,
            embed_text=_embedding,
            chat_fn=chat,
            config=LiveSecurityConfig(
                llm_endpoint="http://127.0.0.1:11434/v1",
                chat_model="qwen2.5:3b",
            ),
            clock_ms=lambda: 1_000.0,
            arm_order=incomplete_plan,
        )

    assert chat.calls == []


def test_no_arm_order_keeps_exact_v1_result_shape(paired_live_result) -> None:
    _, _, result = paired_live_result
    payload = result.model_dump(mode="json")

    assert type(result) is live_runner.LivePairedResult
    assert payload["schema_version"] == "indirect_injection_live_paired_result_v1"
    assert "arm_order" not in payload


def test_v2_result_rejects_any_mode_case_set_that_differs_from_plan(
    live_inputs,
) -> None:
    bundle, built = live_inputs
    plan = build_counterbalanced_arm_order_plan(
        case.case_id for case in bundle.dataset.cases
    )
    result = evaluate_live_paired(
        dataset=bundle.dataset,
        fixtures=bundle.fixture_manifest,
        snapshot=built.snapshot,
        embed_text=_embedding,
        chat_fn=_StructuredFixtureChat(),
        config=LiveSecurityConfig(
            llm_endpoint="http://127.0.0.1:11434/v1",
            chat_model="qwen2.5:3b",
        ),
        clock_ms=lambda: 1_000.0,
        arm_order=plan,
    )
    payload = result.model_dump(mode="python")
    payload["guard_on"][0]["case_id"] = "tampered-case-id"

    with pytest.raises(ValidationError, match="arm-order plan case sets"):
        live_runner.LivePairedResultV2.model_validate(payload)


def test_v2_result_rejects_execution_events_that_contradict_the_plan(
    live_inputs,
) -> None:
    bundle, built = live_inputs
    plan = build_counterbalanced_arm_order_plan(
        case.case_id for case in bundle.dataset.cases
    )
    result = evaluate_live_paired(
        dataset=bundle.dataset,
        fixtures=bundle.fixture_manifest,
        snapshot=built.snapshot,
        embed_text=_embedding,
        chat_fn=_StructuredFixtureChat(),
        config=LiveSecurityConfig(
            llm_endpoint="http://127.0.0.1:11434/v1",
            chat_model="qwen2.5:3b",
        ),
        clock_ms=lambda: 1_000.0,
        arm_order=plan,
    )
    payload = result.model_dump(mode="python")
    payload["arm_execution"][0]["guard_mode"] = (
        "on"
        if payload["arm_execution"][0]["guard_mode"] == "off"
        else "off"
    )

    with pytest.raises(ValidationError, match="execution events contradict"):
        live_runner.LivePairedResultV2.model_validate(payload)


def test_live_observations_distinguish_model_context_from_raw_canary_emission(
    paired_live_result,
) -> None:
    _, _, result = paired_live_result

    off = result.guard_off_summary
    on = result.guard_on_summary
    assert off.raw_document_canary_exposure.numerator >= 1
    assert off.raw_system_canary_exposure.numerator >= 1
    assert off.model_attack_followed.numerator >= 1
    assert on.raw_document_canary_exposure.numerator == 0
    assert on.raw_system_canary_exposure.numerator == 0
    assert on.model_attack_followed.numerator == 0
    assert off.model_call_count >= on.model_call_count
    assert all(
        observation.model_latency_ms >= 0
        for observation in (*result.guard_off, *result.guard_on)
    )


def test_live_detection_metrics_separate_unreached_candidates_from_guard_misses(
    paired_live_result,
) -> None:
    _, _, result = paired_live_result
    on = result.guard_on_summary

    assert on.attack_unit_reached_guard.denominator == 28
    assert on.attack_unit_reached_guard.numerator <= 28
    assert on.quarantine_recall_given_guard_exposure.denominator == (
        on.attack_unit_reached_guard.numerator
    )
    assert on.quarantine_recall_given_guard_exposure.rate == 1.0
    assert on.attack_unit_unreached_count == (
        28 - on.attack_unit_reached_guard.numerator
    )
    assert on.attack_unit_missed_by_guard_count == 0


def test_live_reach_uses_actual_provenance_not_split_payload_category() -> None:
    case = SimpleNamespace(
        category="split_payload",
        attack_unit_ids=("attack-left", "attack-right"),
    )
    fixture = SimpleNamespace(
        candidates=(
            SimpleNamespace(
                chunk_id="chunk-left",
                matched_unit_id="attack-left",
                unit_bindings=lambda: ("attack-left",),
            ),
            SimpleNamespace(
                chunk_id="chunk-right",
                matched_unit_id="attack-right",
                unit_bindings=lambda: ("attack-right",),
            ),
        ),
        open_results=(),
    )

    assert _reached_attack_unit_ids(case, fixture, []) == set()


def test_live_reach_maps_exact_search_and_open_provenance_members() -> None:
    case = SimpleNamespace(
        category="instruction_override",
        attack_unit_ids=("unit-1", "unit-10", "unit-open"),
    )
    fixture = SimpleNamespace(
        candidates=(
            SimpleNamespace(
                chunk_id="chunk-1",
                matched_unit_id="unit-1",
                unit_bindings=lambda: ("unit-1",),
            ),
            SimpleNamespace(
                chunk_id="chunk-10",
                matched_unit_id="unit-10",
                unit_bindings=lambda: ("unit-10",),
            ),
        ),
        open_results=(
            SimpleNamespace(target_id="doc-open", content_unit_id="unit-open"),
        ),
    )
    outcomes = [
        (
            "search",
            SimpleNamespace(
                scan_provenance=(
                    _scan_event("search", "matched", "chunk-10"),
                )
            ),
        ),
        (
            "open",
            SimpleNamespace(
                scan_provenance=(
                    _scan_event("open", "open", "doc-open"),
                )
            ),
        ),
    ]

    assert _reached_attack_unit_ids(case, fixture, outcomes) == {
        "unit-10",
        "unit-open",
    }


def test_live_reach_respects_parent_search_metadata_and_find_surfaces() -> None:
    case = SimpleNamespace(
        category="instruction_override",
        attack_unit_ids=(
            "matched-unit",
            "parent-unit",
            "title-unit",
            "path-unit",
            "section-unit",
            "version-unit",
        ),
    )
    candidate = SimpleNamespace(
        chunk_id="chunk-a",
        matched_unit_id="matched-unit",
        context_unit_id="parent-unit",
        title_unit_id="title-unit",
        source_path_unit_id="path-unit",
        section_unit_id="section-unit",
        version_unit_id="version-unit",
    )
    fixture = SimpleNamespace(candidates=(candidate,), open_results=())
    outcomes = [
        (
            "search",
            SimpleNamespace(
                scan_provenance=(
                    _scan_event("search", "parent", "chunk-a"),
                    _scan_event("search", "metadata", "chunk-a"),
                )
            ),
        ),
        (
            "find",
            SimpleNamespace(
                scan_provenance=(
                    _scan_event("find", "find_preview", "chunk-a"),
                )
            ),
        ),
    ]

    assert _reached_attack_unit_ids(case, fixture, outcomes) == set(
        case.attack_unit_ids
    )


def test_deterministic_live_fixture_has_exact_reach_and_equal_off_on_eligibility(
    paired_live_result,
) -> None:
    _, _, result = paired_live_result
    off_by_id = {item.case_id: item for item in result.guard_off}
    on_by_id = {item.case_id: item for item in result.guard_on}

    assert result.guard_off_summary.attack_unit_reached_guard.numerator == 17
    assert result.guard_on_summary.attack_unit_reached_guard.numerator == 17
    assert result.guard_on_summary.attack_unit_reached_guard.denominator == 28
    assert result.guard_on_summary.attack_unit_unreached_count == 11
    assert {
        case_id: item.attack_unit_reached_guard_count
        for case_id, item in off_by_id.items()
    } == {
        case_id: item.attack_unit_reached_guard_count
        for case_id, item in on_by_id.items()
    }


def test_live_result_serialization_contains_no_prompt_fixture_or_canary_text(
    paired_live_result,
) -> None:
    bundle, _, result = paired_live_result
    serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)

    for case in bundle.dataset.cases:
        if case.document_canary:
            assert case.document_canary not in serialized
        assert case.trace_canary not in serialized
        assert case.question not in serialized
    for fixture in bundle.fixture_manifest.cases:
        for candidate in fixture.candidates:
            assert candidate.matched_text not in serialized
            assert candidate.context_text not in serialized


def test_local_ollama_boundary_allows_only_the_exact_loopback_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()

    def fake_request(self, method, url, *args, **kwargs):
        return sentinel

    monkeypatch.setattr(requests.sessions.Session, "request", fake_request)
    boundary = LocalOllamaOnlyBoundary("http://127.0.0.1:11434/v1")
    with boundary:
        session = requests.Session()
        assert session.request("POST", "http://127.0.0.1:11434/api/chat") is sentinel
        with pytest.raises(RuntimeError, match="blocked non-Ollama HTTP request"):
            session.request("GET", "http://127.0.0.1:11435/api/tags")
        with pytest.raises(RuntimeError, match="blocked external socket"):
            socket.socket().connect(("203.0.113.1", 443))

    assert boundary.allowed_http_request_count == 1
    assert boundary.blocked_attempt_count == 2


def _install_boundary_delegates(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status_code: int = 200,
) -> SimpleNamespace:
    calls = SimpleNamespace(http=[], connect=[], connect_ex=[])

    def fake_request(self, method, url, *args, **kwargs):
        calls.http.append((method, url, args, kwargs))
        return SimpleNamespace(status_code=status_code)

    def fake_connect(self, address):
        calls.connect.append(address)
        return "connected"

    def fake_connect_ex(self, address):
        calls.connect_ex.append(address)
        return 17

    monkeypatch.setattr(requests.sessions.Session, "request", fake_request)
    monkeypatch.setattr(socket.socket, "connect", fake_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", fake_connect_ex)
    return calls


def test_boundary_allows_exact_ipv4_for_http_connect_and_connect_ex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_boundary_delegates(monkeypatch)
    boundary = LocalOllamaOnlyBoundary("http://127.0.0.1:11434/v1")

    with boundary, socket.socket() as sock:
        response = requests.Session().request(
            "POST",
            "http://127.0.0.1:11434/api/chat",
        )
        assert response.status_code == 200
        assert sock.connect(("127.0.0.1", 11434)) == "connected"
        assert sock.connect_ex(("127.0.0.1", 11434)) == 17

    assert len(calls.http) == 1
    assert calls.connect == [("127.0.0.1", 11434)]
    assert calls.connect_ex == [("127.0.0.1", 11434)]
    assert boundary.allowed_http_request_count == 1
    assert boundary.allowed_socket_connect_count == 2
    assert boundary.blocked_attempt_count == 0


def test_ipv4_boundary_blocks_other_loopback_family_external_and_wrong_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_boundary_delegates(monkeypatch)
    boundary = LocalOllamaOnlyBoundary("http://127.0.0.1:11434/v1")

    with boundary, socket.socket() as sock:
        blocked_addresses = (
            ("127.0.0.2", 11434),
            ("::1", 11434, 0, 0),
            ("203.0.113.1", 11434),
            ("127.0.0.1", 11435),
        )
        for index, address in enumerate(blocked_addresses):
            method = sock.connect if index % 2 == 0 else sock.connect_ex
            with pytest.raises(RuntimeError, match="blocked external socket"):
                method(address)

    assert calls.connect == []
    assert calls.connect_ex == []
    assert boundary.allowed_socket_connect_count == 0
    assert boundary.blocked_attempt_count == 4


def test_boundary_allows_only_configured_ipv6_address_and_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_boundary_delegates(monkeypatch)
    boundary = LocalOllamaOnlyBoundary("http://[::1]:11434/v1")

    with boundary, socket.socket(socket.AF_INET6) as sock:
        response = requests.Session().request(
            "POST",
            "http://[0:0:0:0:0:0:0:1]:11434/api/chat",
        )
        assert response.status_code == 200
        assert sock.connect(("::1", 11434, 0, 0)) == "connected"
        assert sock.connect_ex(("::1", 11434, 0, 0)) == 17
        for address in (("127.0.0.1", 11434), ("::2", 11434, 0, 0)):
            with pytest.raises(RuntimeError, match="blocked external socket"):
                sock.connect(address)

    assert len(calls.http) == 1
    assert boundary.allowed_http_request_count == 1
    assert boundary.allowed_socket_connect_count == 2
    assert boundary.blocked_attempt_count == 2


def test_localhost_boundary_freezes_resolution_and_blocks_literal_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_boundary_delegates(monkeypatch)

    def fake_getaddrinfo(host, port, *args, **kwargs):
        assert host == "localhost"
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", port, 0, 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    boundary = LocalOllamaOnlyBoundary("http://localhost:11434/v1")

    with boundary, socket.socket() as sock:
        assert sock.connect(("localhost", 11434)) == "connected"
        with pytest.raises(RuntimeError, match="blocked external socket"):
            sock.connect(("127.0.0.1", 11434))

    assert calls.connect == [("localhost", 11434)]
    assert boundary.allowed_socket_connect_count == 1
    assert boundary.blocked_attempt_count == 1


def test_localhost_http_call_graph_allows_only_its_frozen_resolved_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = SimpleNamespace(http=[], connect=[])

    def fake_getaddrinfo(host, port, *args, **kwargs):
        assert host == "localhost"
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
        ]

    def fake_connect(self, address):
        calls.connect.append(address)
        return "connected"

    def fake_request(self, method, url, *args, **kwargs):
        calls.http.append((method, url, args, kwargs))
        with socket.socket() as sock:
            assert sock.connect(("127.0.0.1", 11434)) == "connected"
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", fake_connect)
    monkeypatch.setattr(requests.sessions.Session, "request", fake_request)
    boundary = LocalOllamaOnlyBoundary("http://localhost:11434/v1")

    with boundary:
        response = requests.Session().request(
            "POST",
            "http://localhost:11434/api/chat",
        )
        assert response.status_code == 200
        with socket.socket() as sock:
            with pytest.raises(RuntimeError, match="blocked external socket"):
                sock.connect(("127.0.0.1", 11434))

    assert len(calls.http) == 1
    assert calls.connect == [("127.0.0.1", 11434)]
    assert boundary.allowed_http_request_count == 1
    assert boundary.allowed_socket_connect_count == 1
    assert boundary.blocked_attempt_count == 1


def test_localhost_boundary_rejects_non_loopback_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("203.0.113.10", 11434),
            )
        ],
    )

    with pytest.raises(ValueError, match="loopback"):
        LocalOllamaOnlyBoundary("http://localhost:11434/v1")


def test_boundary_blocks_credentials_alternate_host_and_host_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_boundary_delegates(monkeypatch)
    boundary = LocalOllamaOnlyBoundary("http://127.0.0.1:11434/v1")

    with boundary:
        session = requests.Session()
        blocked_requests = (
            ("http://user:secret@127.0.0.1:11434/api/chat", {}),
            ("http://localhost:11434/api/chat", {}),
            (
                "http://127.0.0.1:11434/api/chat",
                {"headers": {"Host": "localhost:11434"}},
            ),
        )
        for url, kwargs in blocked_requests:
            with pytest.raises(RuntimeError, match="blocked non-Ollama HTTP"):
                session.request("POST", url, **kwargs)

    assert calls.http == []
    assert boundary.allowed_http_request_count == 0
    assert boundary.blocked_attempt_count == 3


def test_boundary_rejects_explicit_and_session_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_boundary_delegates(monkeypatch)
    boundary = LocalOllamaOnlyBoundary("http://127.0.0.1:11434/v1")

    with boundary:
        session = requests.Session()
        with pytest.raises(RuntimeError, match="blocked HTTP proxy"):
            session.request(
                "POST",
                "http://127.0.0.1:11434/api/chat",
                proxies={"http": "http://127.0.0.1:18080"},
            )
        session.proxies = {"http": "http://127.0.0.1:18080"}
        with pytest.raises(RuntimeError, match="blocked HTTP proxy"):
            session.request("POST", "http://127.0.0.1:11434/api/chat")

    assert calls.http == []
    assert boundary.allowed_http_request_count == 0
    assert boundary.blocked_attempt_count == 2


def test_boundary_blocks_redirect_and_urllib_with_exact_accounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_boundary_delegates(monkeypatch, status_code=302)
    boundary = LocalOllamaOnlyBoundary("http://127.0.0.1:11434/v1")

    with boundary:
        with pytest.raises(RuntimeError, match="blocked Ollama HTTP redirect"):
            requests.Session().request(
                "POST",
                "http://127.0.0.1:11434/api/chat",
                allow_redirects=True,
            )
        with pytest.raises(RuntimeError, match="blocked urllib egress"):
            urllib.request.urlopen("http://127.0.0.1:11434/api/chat")

    assert calls.http[0][3]["allow_redirects"] is False
    assert boundary.allowed_http_request_count == 1
    assert boundary.allowed_socket_connect_count == 0
    assert boundary.blocked_attempt_count == 2


def test_boundary_rejects_nested_activation_and_releases_after_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_boundary_delegates(monkeypatch)
    outer = LocalOllamaOnlyBoundary("http://127.0.0.1:11434/v1")
    inner = LocalOllamaOnlyBoundary("http://127.0.0.1:11434/v1")

    with outer:
        with pytest.raises(RuntimeError, match="already active"):
            with inner:
                raise AssertionError("nested boundary must not activate")

    with inner:
        pass


def test_boundary_rejects_concurrent_activation_without_hanging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_boundary_delegates(monkeypatch)
    outer = LocalOllamaOnlyBoundary("http://127.0.0.1:11434/v1")
    result: Queue[BaseException | None] = Queue()

    def activate_competing_boundary() -> None:
        try:
            with LocalOllamaOnlyBoundary("http://127.0.0.1:11434/v1"):
                pass
        except BaseException as exc:
            result.put(exc)
        else:
            result.put(None)

    with outer:
        worker = threading.Thread(target=activate_competing_boundary)
        worker.start()
        worker.join(timeout=2.0)
        assert worker.is_alive() is False

    error = result.get_nowait()
    assert isinstance(error, RuntimeError)
    assert "already active" in str(error)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://127.0.0.1:11434/v1",
        "http://ollama.internal:11434/v1",
        "http://127.0.0.1:11434@attack.invalid/v1",
        "http://127.0.0.1:11434/v1?redirect=http://attack.invalid",
    ],
)
def test_live_config_rejects_nonlocal_or_ambiguous_model_endpoints(
    endpoint: str,
) -> None:
    with pytest.raises(ValidationError):
        LiveSecurityConfig(
            llm_endpoint=endpoint,
            chat_model="qwen2.5:3b",
        )
