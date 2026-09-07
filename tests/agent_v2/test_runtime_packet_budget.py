import json

import pytest

from app.agent.evidence_ledger import build_ledger
from app.agent.generation_v2 import GenerationV2ResponseBuilder
from app.runtime.model_transport import ModelRequestError
from tests.agent_v2.test_generation_v2 import (
    CapturingChat,
    SequencedChat,
    _replace_state,
    state_with_evidence,
    valid_payload,
)
from tests.v2_test_support import admitted_search_hit


def records(chat):
    content = chat.calls[0]["messages"][1]["content"]
    return json.loads(content.split("]\n", 1)[1].split("\n[END_UNTRUSTED", 1)[0])


def build(chat, *, question=None, state=None, attempts=1):
    state = state or state_with_evidence()
    return GenerationV2ResponseBuilder(
        chat_fn=chat,
        model="fixture",
        max_attempts=attempts,
    ).build(
        question=question or state.analysis.original_question,
        state=state,
        mode="answered",
        stop_reason="completed",
        trace={},
    )


def test_question_overflow_prevents_model_call_and_retains_safe_budget_trace():
    chat = CapturingChat(valid_payload())
    response = build(chat, question="private-question-" * 900)
    assert chat.calls == []
    assert response.mode == "system"
    assert response.trace["generation_error_category"] == "unsupported"
    assert response.trace["generation_attempts"] == 0
    budget = response.trace["prompt_budget"]
    assert budget["estimator"] == "utf8_bytes_upper_bound_v1"
    assert budget["context_floor_tokens"] == 8192
    assert "private-question" not in json.dumps(response.trace)


def test_packet_audit_is_private_stable_and_survives_invalid_shape():
    state = state_with_evidence(include_open=True)
    state = _replace_state(
        state,
        evidence_by_aspect={
            "answer": state.evidence_by_aspect["answer"] * 2,
        },
        open_results=state.open_results * 2,
    )
    first = build(CapturingChat(valid_payload()), state=state)
    failed = build(SequencedChat(["private-invalid-output", "{}"]), state=state, attempts=2)
    assert first.trace["packet_hash"] == failed.trace["packet_hash"]
    assert len(first.trace["packet_hash"]) == 64
    assert failed.trace["generation_attempts"] == 2
    assert failed.trace["generation_error_category"] == "invalid_shape"
    assert failed.trace["retrieved_aspect_coverage"] == {"covered": 1, "required": 1}
    assert failed.trace["packed_aspect_coverage"] == {"covered": 1, "required": 1}
    assert failed.trace["packet_duplicate_reasons"]["chunk"] == 1
    assert failed.trace["packet_duplicate_reasons"]["open_target"] == 1
    assert failed.trace["packet_duplicate_reasons"]["matched_context"] == 1
    serialized = json.dumps(failed.trace)
    for private in ("chunk-a", "doc-a", "Policy A", "private-invalid-output", "documents/"):
        assert private not in serialized


@pytest.mark.parametrize(
    "code,category", [("transport_timeout", "transport"), ("deadline_exhausted", "deadline")]
)
def test_second_call_failure_keeps_attempts_packet_and_bounded_category(code, category):
    chat = SequencedChat(
        ["bad", ModelRequestError(code=code, status_code=None, retryable=False, attempts=3)]
    )
    response = build(chat, attempts=2)
    assert response.trace["generation_attempts"] == 2
    assert response.trace["generation_error_category"] == category
    assert len(response.trace["packet_hash"]) == 64
    assert len(chat.calls) == 2


@pytest.mark.parametrize(
    "unit",
    [
        "Policy background. ",
        "\u653f\u7b56\u80cc\u666f\u8bf4\u660e\u3002",
        'Quoted "policy" \\ background. ',
    ],
)
def test_full_serialized_prompt_and_retry_fit_with_multilingual_evidence(unit):
    state = state_with_evidence(include_second=True)
    text = "Policy A allows remote work three days per month. " + unit * 300
    evidence = {
        "Policy A": [
            admitted_search_hit(chunk_id=f"a-{i}", matched_text=text, context_text=text)
            for i in range(9)
        ],
        "Policy B": state.evidence_by_aspect["Policy B"],
    }
    state = _replace_state(
        state, evidence_by_aspect=evidence, ledger=build_ledger(state.analysis, evidence)
    )
    chat = SequencedChat(["bad", valid_payload()])
    response = build(
        chat, state=state, attempts=2, question='Compare "Policy A" and Policy B. ' * 20
    )
    assert len(chat.calls) == 2
    rows = records(chat)
    assert {row["aspect"] for row in rows} == {"Policy A", "Policy B"}
    assert len(rows) <= 8
    for call in chat.calls:
        # Default JSON separators are larger than production's compact encoding.
        total = len(json.dumps(call["messages"], ensure_ascii=False).encode("utf-8"))
        total += (
            len(json.dumps(call["response_format"], ensure_ascii=False).encode("utf-8"))
            + 1024
            + 512
        )
        assert total <= 8192
    assert response.trace["prompt_evidence_chars"] <= 8000
    assert response.trace["packet_truncation_reasons"]["unit_limit"] > 0
    assert response.trace["packed_aspect_coverage"]["covered"] == 2


def test_eight_source_limit_and_dropped_table_are_audited():
    state = state_with_evidence()
    hits = [admitted_search_hit(chunk_id=f"private-{i}") for i in range(10)]
    state = _replace_state(state, evidence_by_aspect={"answer": hits})
    chat = CapturingChat(valid_payload())
    response = build(chat, state=state)
    assert len(records(chat)) == 8
    assert response.trace["packet_drop_reasons"]["source_limit"] == 2
    table = "| Department | Limit |\n" + "| Finance | 100 |\n" * 200
    state = _replace_state(
        state,
        evidence_by_aspect={
            "answer": [admitted_search_hit(matched_text=table, context_text=table)]
        },
    )
    chat = CapturingChat(valid_payload())
    response = build(chat, state=state)
    assert chat.calls == []
    assert response.trace["packet_drop_reasons"]["no_complete_unit"] == 1
    assert response.trace["packed_aspect_coverage"]["covered"] == 0


def test_deadline_before_retry_preserves_first_attempt(monkeypatch):
    remaining = iter([10, 0])
    monkeypatch.setattr("app.agent.generation_v2.remaining_seconds", lambda: next(remaining))
    chat = SequencedChat(["bad", valid_payload()])
    response = build(chat, attempts=2)
    assert len(chat.calls) == 1
    assert response.trace["generation_attempts"] == 1
    assert response.trace["generation_error_category"] == "deadline"


def test_long_metadata_is_not_silently_cut_and_packet_hash_binds_identity():
    state = state_with_evidence()
    long_aspect = "private-aspect-" * 20
    analysis = state.analysis.model_copy(update={"required_aspects": [long_aspect]})
    evidence = {long_aspect: state.evidence_by_aspect["answer"]}
    state = _replace_state(
        state,
        analysis=analysis,
        evidence_by_aspect=evidence,
        ledger=build_ledger(analysis, evidence),
    )
    chat = CapturingChat(valid_payload())
    response = build(chat, state=state, question="Question detail. " * 280)
    assert chat.calls == []
    assert response.trace["packet_drop_reasons"]["packet_budget"] == 1
    assert "private-aspect" not in json.dumps(response.trace)
    first = build(CapturingChat(valid_payload()))
    state = state_with_evidence()
    hit = admitted_search_hit(
        chunk_id="changed-private-identity",
        matched_text=state.evidence_by_aspect["answer"][0].hit.matched_text,
        context_text=state.evidence_by_aspect["answer"][0].hit.context_text,
    )
    state = _replace_state(state, evidence_by_aspect={"answer": [hit]})
    second = build(CapturingChat(valid_payload()), state=state)
    assert first.trace["packet_hash"] != second.trace["packet_hash"]
