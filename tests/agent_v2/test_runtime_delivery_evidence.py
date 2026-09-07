from __future__ import annotations

import json

import pytest

from app.agent.evidence_ledger import build_ledger
from app.agent.generation_v2 import GenerationV2ResponseBuilder, _bounded_json_record
from app.domain.evidence_packet import DeliveredEvidence
from tests.agent_v2.test_generation_v2 import (
    TEST_NONCE,
    _replace_state,
    evidence_records_from_prompt,
    state_with_evidence,
    valid_payload,
)
from tests.v2_test_support import admit_open_result, admitted_search_hit, open_result


@pytest.mark.parametrize("field", ["matched_text", "context_text"])
def test_packet_does_not_allow_replacing_admitted_text(field):
    evidence = admitted_search_hit()
    values = {"anchor": evidence, "matched_text": evidence.hit.matched_text}
    values[field] = "This was never admitted."
    with pytest.raises(ValueError, match="belong to its source"):
        DeliveredEvidence(**values)


def test_open_cannot_borrow_a_different_document_anchor():
    with pytest.raises(ValueError, match="match its admitted document"):
        DeliveredEvidence(
            anchor=admitted_search_hit(doc_id="another-doc"),
            opened=admit_open_result(open_result(content="Approved evidence.")),
            matched_text="Approved evidence.",
        )


def test_json_budget_does_not_turn_an_unfinished_sentence_into_a_fact():
    head = "Policy A requires manager approval. "
    record = {
        "source_id": "S1",
        "context_text": "",
        "matched_text": head
        + "Employees can approve "
        + "routine requests " * 40
        + "only after review.",
    }
    packed = _bounded_json_record(record, 150)
    assert packed is not None
    assert json.loads(packed)["matched_text"].strip() == head.strip()


def test_an_opened_fact_can_be_published_with_its_actual_source():
    fact = "Policy A allows 9 remote work days per quarter."
    state = _replace_state(
        state_with_evidence(),
        open_results=[admit_open_result(open_result(content=fact))],
    )

    def chat(model, messages, **kwargs):
        records = evidence_records_from_prompt(messages[1]["content"], TEST_NONCE)
        source = next(record for record in records if fact in str(record))
        return json.dumps(valid_payload(source_id=source["source_id"], claim_text=fact))

    response = GenerationV2ResponseBuilder(
        chat_fn=chat,
        model="fixture",
        max_attempts=1,
        nonce_factory=lambda: TEST_NONCE,
    ).build(
        question="What is the quarterly remote work allowance?",
        state=state,
        mode="answered",
        stop_reason="completed",
        trace={},
    )
    assert response.mode == "answered"
    assert response.answer == fact
    assert all(citation.supported for citation in response.citations)
    assert any(fact in source.preview for source in response.sources)


def test_long_first_aspect_does_not_remove_the_second_or_claim_complete_answer():
    state = state_with_evidence(include_second=True)
    text = "Policy A allows remote work three days per month. " + "Policy background. " * 65
    evidence = {
        "Policy A": [
            admitted_search_hit(
                chunk_id=f"a-{index}",
                doc_id=f"a-doc-{index}",
                matched_text=text,
                context_text=text,
            )
            for index in range(5)
        ],
        "Policy B": state.evidence_by_aspect["Policy B"],
    }
    state = _replace_state(
        state, evidence_by_aspect=evidence, ledger=build_ledger(state.analysis, evidence)
    )
    delivered = []

    def chat(model, messages, **kwargs):
        delivered.extend(evidence_records_from_prompt(messages[1]["content"], TEST_NONCE))
        return json.dumps(valid_payload())

    response = GenerationV2ResponseBuilder(
        chat_fn=chat,
        model="fixture",
        max_attempts=1,
        nonce_factory=lambda: TEST_NONCE,
    ).build(
        question=state.analysis.original_question,
        state=state,
        mode="answered",
        stop_reason="completed",
        trace={},
    )
    assert {row["aspect"] for row in delivered} == {"Policy A", "Policy B"}
    assert response.mode == "partial"
    assert response.stop_reason == "partial_evidence"


def test_extractive_fallback_cannot_publish_a_truncated_source_tail():
    state = state_with_evidence()
    text = "Policy A allows remote work three days per month. " * 30
    tail = "Refunds are available for 97 days."
    evidence = admitted_search_hit(matched_text=text + tail, context_text=text + tail)
    state = _replace_state(
        state,
        evidence_by_aspect={"answer": [evidence]},
        ledger=build_ledger(state.analysis, {"answer": [evidence]}),
    )
    delivered = []

    def chat(model, messages, **kwargs):
        delivered.extend(evidence_records_from_prompt(messages[1]["content"], TEST_NONCE))
        return json.dumps(valid_payload(claim_text=tail))

    response = GenerationV2ResponseBuilder(
        chat_fn=chat,
        model="fixture",
        max_attempts=1,
        nonce_factory=lambda: TEST_NONCE,
    ).build(
        question=state.analysis.original_question,
        state=state,
        mode="answered",
        stop_reason="completed",
        trace={},
    )
    assert tail not in str(delivered)
    assert response.mode == "partial"
    assert tail not in response.answer
    assert all(claim.text in row["matched_text"] for claim in response.claims for row in delivered)
