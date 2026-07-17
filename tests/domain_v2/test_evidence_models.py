import pytest
from pydantic import ValidationError

from app.domain.evidence import (
    AnswerResponse,
    AnswerSource,
    Claim,
    ClaimCitation,
    EvidenceItem,
    EvidenceLedger,
)


def evidence_item(**updates) -> EvidenceItem:
    values = {
        "aspect": "Policy A",
        "chunk_id": "doc-a::child::001",
        "doc_id": "doc-a",
        "relation": "supports",
        "authority_level": 100,
        "version_id": "policy-a@2026",
        "status": "active",
    }
    values.update(updates)
    return EvidenceItem(**values)


def source(**updates) -> AnswerSource:
    values = {
        "doc_id": "doc-a",
        "source_path": "documents/doc-a.md",
        "section_path": ["Policy A", "Scope"],
        "chunk_id": "doc-a::child::001",
        "preview": "Employees may work remotely three days.",
    }
    values.update(updates)
    return AnswerSource(**values)


def test_ledger_requires_exact_supported_missing_partition_and_coverage() -> None:
    with pytest.raises(ValidationError, match="coverage"):
        EvidenceLedger(
            required_aspects=["Policy A", "Policy B"],
            items=[evidence_item()],
            supported_aspects=["Policy A"],
            conflicting_aspects=[],
            missing_aspects=["Policy B"],
            coverage=1.0,
            recommended_action="search",
        )

    ledger = EvidenceLedger(
        required_aspects=["Policy A", "Policy B"],
        items=[evidence_item()],
        supported_aspects=["Policy A"],
        conflicting_aspects=[],
        missing_aspects=["Policy B"],
        coverage=0.5,
        recommended_action="search",
    )
    assert ledger.coverage == 0.5


def test_answer_recommendation_requires_full_nonconflicting_coverage() -> None:
    with pytest.raises(ValidationError, match="answer"):
        EvidenceLedger(
            required_aspects=["Policy A", "Policy B"],
            items=[evidence_item()],
            supported_aspects=["Policy A"],
            conflicting_aspects=[],
            missing_aspects=["Policy B"],
            coverage=0.5,
            recommended_action="answer",
        )


def test_claim_citation_consistency_is_validated() -> None:
    with pytest.raises(ValidationError, match="citation_present"):
        ClaimCitation(
            claim_id="claim-1",
            cited_chunk_ids=[],
            citation_present=True,
            references_visible_evidence=False,
            lexical_support=0.0,
            supported=False,
            unsupported_reason="missing citation",
        )

    citation = ClaimCitation(
        claim_id="claim-1",
        cited_chunk_ids=["doc-a::child::001"],
        citation_present=True,
        references_visible_evidence=True,
        lexical_support=0.8,
        supported=True,
    )
    assert citation.supported is True


def test_answered_response_requires_claims_citations_and_sources() -> None:
    with pytest.raises(ValidationError, match="answered"):
        AnswerResponse(mode="answered", answer="Three days.")

    response = AnswerResponse(
        mode="answered",
        answer="Employees may work remotely three days.",
        claims=[Claim(claim_id="claim-1", text="Remote work is limited to three days.")],
        citations=[
            ClaimCitation(
                claim_id="claim-1",
                cited_chunk_ids=["doc-a::child::001"],
                citation_present=True,
                references_visible_evidence=True,
                lexical_support=0.8,
                supported=True,
            )
        ],
        sources=[source()],
        stop_reason="completed",
    )
    assert response.sources[0].chunk_id == "doc-a::child::001"


@pytest.mark.parametrize("mode", ["unsafe", "permission", "not_found", "system", "budget"])
def test_nonanswer_modes_cannot_expose_sources(mode: str) -> None:
    with pytest.raises(ValidationError, match="sources"):
        AnswerResponse(
            mode=mode,
            answer="No visible evidence.",
            sources=[source()],
            stop_reason=mode,
        )


def test_response_rejects_citation_for_unknown_claim() -> None:
    with pytest.raises(ValidationError, match="claim"):
        AnswerResponse(
            mode="partial",
            answer="Partial evidence.",
            claims=[Claim(claim_id="claim-1", text="Policy A is supported.")],
            citations=[
                ClaimCitation(
                    claim_id="claim-2",
                    cited_chunk_ids=["doc-a::child::001"],
                    citation_present=True,
                    references_visible_evidence=True,
                    lexical_support=0.5,
                    supported=True,
                )
            ],
            sources=[source()],
            stop_reason="partial_evidence",
        )
