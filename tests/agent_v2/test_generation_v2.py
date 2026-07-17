from __future__ import annotations

import json

import pytest

from app.agent.controller_v2 import V2AgentController
from app.agent.evidence_ledger import build_ledger
from app.agent.generation_v2 import GenerationV2ResponseBuilder
from app.domain.queries import OpenResult, QueryAnalysis
from app.runtime.model_transport import ModelRequestError
from tests.v2_test_support import search_hit, user_context


USER = user_context()


def state_with_evidence(*, include_second: bool = False, include_open: bool = False):
    required = ["Policy A", "Policy B"] if include_second else ["answer"]
    queries = list(required)
    intent = "comparison" if include_second else "fact"
    entities = list(required) if include_second else []
    analysis = QueryAnalysis(
        original_question="Compare the current policy limits" if include_second else "What is the current limit?",
        intent=intent,
        entities=entities,
        search_queries=queries,
        required_aspects=required,
        source="rules",
    )
    first = search_hit(
        chunk_id="chunk-a",
        doc_id="doc-a",
        matched_text="Policy A allows remote work three days per month.",
        context_text="Policy A allows remote work three days per month.",
    )
    evidence = {required[0]: [first]}
    if include_second:
        evidence[required[1]] = [
            search_hit(
                chunk_id="chunk-b",
                doc_id="doc-b",
                policy_id="policy-b",
                source_path="documents/doc-b.md",
                matched_text="Policy B allows remote work two days per month.",
                context_text="Policy B allows remote work two days per month.",
                version_id="policy-b@2026",
                fact_ids=["fact-b"],
            )
        ]
    controller = V2AgentController(clock_ms=lambda: 0.0)
    state = controller.initialize(analysis, USER)
    ledger = build_ledger(analysis, evidence)
    open_results = []
    if include_open:
        open_results = [
            OpenResult(
                request_id="open-one",
                target_type="document",
                target_id="doc-a",
                doc_id="doc-a",
                content="Authorized full document context with exceptions.",
                truncated=False,
                source_path="documents/doc-a.md",
                section_path=[],
            )
        ]
    return state.model_copy(
        update={
            "evidence_by_aspect": evidence,
            "ledger": ledger,
            "open_results": open_results,
        }
    )


class CapturingChat:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls = []

    def __call__(
        self,
        model,
        messages,
        *,
        response_format=None,
        think=None,
    ):
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "response_format": response_format,
                "think": think,
            }
        )
        if isinstance(self.payload, Exception):
            raise self.payload
        if isinstance(self.payload, str):
            return self.payload
        return json.dumps(self.payload)


class SequencedChat:
    def __init__(self, payloads) -> None:
        self.payloads = iter(payloads)
        self.calls = []

    def __call__(
        self,
        model,
        messages,
        *,
        response_format=None,
        think=None,
    ):
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "response_format": response_format,
                "think": think,
            }
        )
        payload = next(self.payloads)
        if isinstance(payload, Exception):
            raise payload
        return payload if isinstance(payload, str) else json.dumps(payload)


def valid_payload(*, source_id: str = "S1", claim_text: str | None = None):
    claim_text = claim_text or "Policy A allows remote work three days per month."
    return {
        "answer": claim_text,
        "claims": [
            {
                "claim_id": "claim-1",
                "text": claim_text,
                "critical": True,
                "cited_source_ids": [source_id],
            }
        ],
    }


def test_prompt_contains_only_ledger_selected_visible_evidence() -> None:
    state = state_with_evidence(include_open=True)
    excluded = search_hit(
        chunk_id="excluded-secret-chunk",
        doc_id="excluded-secret-doc",
        source_path="vault/secret.md",
        matched_text="PROJECT NIGHTFALL SECRET SHOULD NEVER REACH THE MODEL",
        context_text="PROJECT NIGHTFALL SECRET SHOULD NEVER REACH THE MODEL",
    )
    state = state.model_copy(
        update={
            "evidence_by_aspect": {
                **state.evidence_by_aspect,
                "not-required": [excluded],
            }
        }
    )
    chat = CapturingChat(valid_payload())
    builder = GenerationV2ResponseBuilder(chat_fn=chat, model="test-model")

    response = builder.build(
        question=state.analysis.original_question,
        state=state,
        mode="answered",
        stop_reason="completed",
        trace={},
    )

    prompt = chat.calls[0]["messages"][1]["content"]
    assert response.mode == "answered"
    assert "intent=fact" in prompt
    assert state.analysis.original_question in prompt
    assert "[S1]" in prompt
    assert "Policy A allows remote work" in prompt
    assert "Authorized full document context" in prompt
    assert "NIGHTFALL" not in prompt
    assert "excluded-secret" not in prompt
    assert chat.calls[0]["response_format"]["type"] == "object"
    assert chat.calls[0]["think"] is False


def test_ollama_sampling_schema_uses_only_grammar_compatible_constraints() -> None:
    state = state_with_evidence()
    chat = CapturingChat(valid_payload())

    GenerationV2ResponseBuilder(chat_fn=chat, model="test-model").build(
        question=state.analysis.original_question,
        state=state,
        mode="answered",
        stop_reason="completed",
        trace={},
    )

    serialized_schema = json.dumps(chat.calls[0]["response_format"])
    unsupported_keywords = {
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "pattern",
        "additionalProperties",
    }
    assert all(keyword not in serialized_schema for keyword in unsupported_keywords)


def test_source_numbering_is_stable_and_maps_back_to_chunk_ids() -> None:
    state = state_with_evidence(include_second=True)
    payload = {
        "answer": "Policy A allows three days; Policy B allows two days.",
        "claims": [
            {
                "claim_id": "claim-a",
                "text": "Policy A allows remote work three days per month.",
                "critical": True,
                "cited_source_ids": ["S1"],
            },
            {
                "claim_id": "claim-b",
                "text": "Policy B allows remote work two days per month.",
                "critical": True,
                "cited_source_ids": ["S2"],
            },
        ],
    }
    chat = CapturingChat(payload)

    response = GenerationV2ResponseBuilder(
        chat_fn=chat,
        model="test-model",
    ).build(
        question=state.analysis.original_question,
        state=state,
        mode="answered",
        stop_reason="completed",
        trace={},
    )

    prompt = chat.calls[0]["messages"][1]["content"]
    assert prompt.index("[S1]") < prompt.index("[S2]")
    assert [claim.cited_chunk_ids for claim in response.claims] == [
        ["chunk-a"],
        ["chunk-b"],
    ]
    assert [source.chunk_id for source in response.sources] == [
        "chunk-a",
        "chunk-b",
    ]
    assert all(citation.supported for citation in response.citations)


def test_parent_and_open_context_are_bounded_before_prompting() -> None:
    state = state_with_evidence(include_open=True)
    long_hit = state.evidence_by_aspect["answer"][0].model_copy(
        update={"context_text": "H" * 1300 + "HIT_TAIL_MUST_BE_GONE"}
    )
    long_open = state.open_results[0].model_copy(
        update={"content": "O" * 2100 + "OPEN_TAIL_MUST_BE_GONE"}
    )
    state = state.model_copy(
        update={
            "evidence_by_aspect": {"answer": [long_hit]},
            "open_results": [long_open],
        }
    )
    chat = CapturingChat(valid_payload())

    GenerationV2ResponseBuilder(chat_fn=chat, model="test-model").build(
        question=state.analysis.original_question,
        state=state,
        mode="answered",
        stop_reason="completed",
        trace={},
    )

    prompt = chat.calls[0]["messages"][1]["content"]
    assert "HIT_TAIL_MUST_BE_GONE" not in prompt
    assert "OPEN_TAIL_MUST_BE_GONE" not in prompt


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        {"answer": "Unsupported", "claims": []},
        valid_payload(source_id="S999"),
        RuntimeError("model failed at D:/secret/model.bin"),
    ],
)
def test_invalid_generation_fails_closed_without_sources(payload) -> None:
    state = state_with_evidence()
    chat = CapturingChat(payload)

    response = GenerationV2ResponseBuilder(
        chat_fn=chat,
        model="test-model",
    ).build(
        question=state.analysis.original_question,
        state=state,
        mode="answered",
        stop_reason="completed",
        trace={},
    )

    assert response.mode == "system"
    assert response.sources == []
    assert "secret" not in response.model_dump_json().casefold()


def test_invalid_first_json_gets_one_bounded_shape_retry() -> None:
    state = state_with_evidence()
    chat = SequencedChat(["not-json", valid_payload()])

    response = GenerationV2ResponseBuilder(
        chat_fn=chat,
        model="test-model",
        max_attempts=2,
    ).build(
        question=state.analysis.original_question,
        state=state,
        mode="answered",
        stop_reason="completed",
        trace={},
    )

    assert response.mode == "answered"
    assert len(chat.calls) == 2
    assert response.trace["generation_attempts"] == 2
    assert "Previous output failed" in chat.calls[1]["messages"][-1]["content"]


def test_two_invalid_generation_shapes_fail_closed_after_exact_bound() -> None:
    state = state_with_evidence()
    chat = SequencedChat(["not-json", {"answer": "missing claims"}])

    response = GenerationV2ResponseBuilder(
        chat_fn=chat,
        model="test-model",
        max_attempts=2,
    ).build(
        question=state.analysis.original_question,
        state=state,
        mode="answered",
        stop_reason="completed",
        trace={},
    )

    assert response.mode == "system"
    assert response.sources == []
    assert response.trace["generation_attempts"] == 2
    assert len(chat.calls) == 2


def test_transport_failure_is_not_retried_by_generation_builder() -> None:
    state = state_with_evidence()
    chat = SequencedChat(
        [
            ModelRequestError(
                code="transport_timeout",
                status_code=None,
                retryable=True,
                attempts=2,
            )
        ]
    )

    response = GenerationV2ResponseBuilder(
        chat_fn=chat,
        model="test-model",
        max_attempts=2,
    ).build(
        question=state.analysis.original_question,
        state=state,
        mode="answered",
        stop_reason="completed",
        trace={},
    )

    assert response.mode == "system"
    assert response.sources == []
    assert len(chat.calls) == 1


def test_critical_claim_with_zero_lexical_support_downgrades_to_partial() -> None:
    state = state_with_evidence()
    chat = CapturingChat(
        valid_payload(claim_text="Travel reimbursement is 9000 yuan.")
    )

    response = GenerationV2ResponseBuilder(
        chat_fn=chat,
        model="test-model",
    ).build(
        question=state.analysis.original_question,
        state=state,
        mode="answered",
        stop_reason="completed",
        trace={},
    )

    assert response.mode == "partial"
    assert response.stop_reason == "partial_evidence"
    assert response.citations[0].supported is False
    assert response.warnings


def test_generation_never_calls_legacy_retrieval(monkeypatch) -> None:
    def fail_legacy(*args, **kwargs):
        raise AssertionError("generation must not call legacy retrieval")

    monkeypatch.setattr("app.retriever.hybrid_search", fail_legacy)
    state = state_with_evidence()
    chat = CapturingChat(valid_payload())

    response = GenerationV2ResponseBuilder(
        chat_fn=chat,
        model="test-model",
    ).build(
        question=state.analysis.original_question,
        state=state,
        mode="answered",
        stop_reason="completed",
        trace={},
    )

    assert response.mode == "answered"
