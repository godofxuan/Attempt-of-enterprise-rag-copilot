from __future__ import annotations

import json

import pytest

from app.agent.citation_verifier import verify_claims
from app.agent.evidence_ledger import build_ledger
from app.agent.generation_v2 import GenerationV2ResponseBuilder
from app.domain.evidence import Claim
from tests.agent_v2.test_citation_verifier import hit
from tests.agent_v2.test_generation_v2 import _replace_state, state_with_evidence, valid_payload


@pytest.mark.parametrize("heading", ["制度要点\n", "  制度要求\r\n  ", "Policy details\n"])
def test_neutral_heading_does_not_hide_an_exact_policy_sentence(heading):
    sentence = "当前制度规定每周最多远程办公 3 天。"
    evidence = hit(
        chunk_id="source", matched_text=heading + sentence, context_text=heading + sentence
    )
    claim = Claim(claim_id="c", text=sentence, cited_chunk_ids=["source"])
    result = verify_claims([claim], [evidence])[0]
    assert result.supported
    assert result.supporting_spans[0].quote == sentence
    span = result.supporting_spans[0]
    assert getattr(evidence.hit, span.field)[span.start : span.end] == sentence


@pytest.mark.parametrize(
    "heading",
    [
        "Only after manager authorization\n",
        "制度要点：仅限经理\n",
        "Policy details for managers only\n",
        "制度要点\nOnly after manager authorization\n",
    ],
)
def test_scoping_line_must_not_be_discarded_as_a_heading(heading):
    sentence = "Employees can approve refunds within 7 days."
    evidence = hit(
        chunk_id="source", matched_text=heading + sentence, context_text=heading + sentence
    )
    claim = Claim(claim_id="c", text=sentence, cited_chunk_ids=["source"])
    assert not verify_claims([claim], [evidence])[0].supported


@pytest.mark.parametrize(
    "source,claim",
    [
        (
            "Refunds arrive in 7 days. Invoices are retained for 30 days.",
            "Refunds arrive in 30 days.",
        ),
        ("Employees submit claims. Managers approve claims.", "Employees approve claims."),
        ("退款7天到账。发票保存30天。", "退款30天到账。"),
        ("员工提交报销；经理批准报销。", "员工批准报销。"),
        (
            "Revenue was 10 million in 2025 and 20 million in 2026.",
            "Revenue was 20 million in 2025.",
        ),
        ("The policy does not say employees can approve claims.", "Employees can approve claims."),
    ],
)
@pytest.mark.parametrize("critical", [True, False])
def test_critical_facts_cannot_be_assembled_from_unbound_words(source, claim, critical):
    result = verify_claims(
        [Claim(claim_id="c", text=claim, critical=critical, cited_chunk_ids=["chunk-remote"])],
        [hit(matched_text=source, context_text=source)],
    )[0]
    assert result.supported is False


@pytest.mark.parametrize(
    "source,claim",
    [
        (
            "Refunds arrive in 7 days. Invoices are retained for 30 days.",
            "Refunds arrive in 7 days.",
        ),
        ("Employees submit claims. Managers approve claims.", "Managers approve claims."),
        ("退款7天到账。发票保存30天。", "退款7天到账。"),
        ("Revenue was 10.5 million.", "Revenue was 10.5 million."),
        ("Managers  approve\tclaims.", "Managers approve claims."),
        (
            'Training quotes "Do not approve." Refunds arrive in 7 days.',
            "Refunds arrive in 7 days.",
        ),
    ],
)
def test_correct_fact_has_a_server_resolved_source_span(source, claim):
    result = verify_claims(
        [Claim(claim_id="c", text=claim, cited_chunk_ids=["chunk-remote"])],
        [hit(matched_text=source, context_text=source)],
    )[0]
    assert result.supported is True
    assert result.support_kind == "exact_span"
    span = result.supporting_spans[0]
    assert source[span.start : span.end] == span.quote
    assert span.version_id == "remote-policy@2026"
    assert span.citation_id == "chunk-remote"


def test_wrong_actor_is_removed_from_generation_not_just_marked_unsupported():
    state = state_with_evidence()
    source = "Employees submit claims. Managers approve claims."
    evidence = hit(matched_text=source, context_text=source)
    state = _replace_state(
        state,
        evidence_by_aspect={"answer": [evidence]},
        ledger=build_ledger(state.analysis, {"answer": [evidence]}),
    )
    wrong = "Employees approve claims."
    response = GenerationV2ResponseBuilder(
        chat_fn=lambda *args, **kwargs: json.dumps(valid_payload(claim_text=wrong)),
        model="fixture",
        max_attempts=1,
    ).build(
        question="Who approves claims?",
        state=state,
        mode="answered",
        stop_reason="completed",
        trace={},
    )
    assert response.mode == "partial"
    assert wrong not in response.model_dump_json()
    assert "Managers approve claims." in response.answer
    assert all(citation.support_kind == "exact_span" for citation in response.citations)
