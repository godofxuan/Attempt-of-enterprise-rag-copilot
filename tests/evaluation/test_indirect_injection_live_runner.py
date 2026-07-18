from __future__ import annotations

import hashlib
import json
import re
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from pydantic import ValidationError

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
    evaluate_live_paired,
)


FROZEN_AT = "2026-07-18T00:00:00Z"
FREEZE_HEAD = "a" * 40
FIXTURE_SHA256 = "b" * 64
BUILD_TIME = datetime(2026, 7, 18, 1, 2, 3, tzinfo=timezone.utc)


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
