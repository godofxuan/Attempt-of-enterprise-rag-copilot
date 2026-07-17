from __future__ import annotations

import pytest

from app.agent.citation_verifier import verify_claims
from app.domain.documents import SourceLocator
from app.domain.evidence import Claim
from app.domain.queries import SearchHit


def hit(**updates) -> SearchHit:
    values = {
        "index_run_id": "run-one",
        "chunk_id": "chunk-remote",
        "doc_id": "doc-remote",
        "parent_chunk_id": None,
        "policy_id": "remote-policy",
        "source_path": "documents/remote.md",
        "section_path": ["Remote Work", "Limit"],
        "locator": SourceLocator(kind="paragraph", start=1),
        "matched_text": "Employees may work remotely three days per month.",
        "context_text": "Employees may work remotely three days per month.",
        "context_from_parent": False,
        "tenant_id": "tenant-one",
        "region": "cn",
        "acl_groups": ["employees"],
        "version_id": "remote-policy@2026",
        "version": "2026",
        "status": "active",
        "authority_level": 100,
        "variant": "authoritative",
        "fact_ids": ["remote-days"],
        "fused_score": 1.0,
        "bm25_score": 1.0,
        "bm25_rank": 1,
    }
    values.update(updates)
    return SearchHit(**values)


def test_missing_citation_is_a_hard_failure() -> None:
    result = verify_claims(
        [Claim(claim_id="claim-1", text="Remote work is limited to three days.")],
        [hit()],
    )[0]

    assert result.citation_present is False
    assert result.references_visible_evidence is False
    assert result.lexical_support == 0.0
    assert result.supported is False
    assert result.unsupported_reason == "missing citation"


def test_unknown_or_denied_reference_is_indistinguishable() -> None:
    result = verify_claims(
        [
            Claim(
                claim_id="claim-1",
                text="The board approved Project NIGHTFALL.",
                cited_chunk_ids=["secret-board-chunk"],
            )
        ],
        [hit()],
    )[0]

    assert result.citation_present is True
    assert result.references_visible_evidence is False
    assert result.lexical_support == 0.0
    assert result.supported is False
    assert result.unsupported_reason == "citation does not reference visible evidence"


def test_visible_reference_with_lexical_support_passes() -> None:
    result = verify_claims(
        [
            Claim(
                claim_id="claim-1",
                text="Employees may work remotely three days per month.",
                cited_chunk_ids=["chunk-remote"],
            )
        ],
        [hit()],
    )[0]

    assert result.references_visible_evidence is True
    assert result.lexical_support > 0.8
    assert result.supported is True
    assert result.unsupported_reason is None


def test_visible_reference_without_lexical_overlap_is_not_semantic_support() -> None:
    result = verify_claims(
        [
            Claim(
                claim_id="claim-1",
                text="The travel budget is 9000 yuan.",
                cited_chunk_ids=["chunk-remote"],
            )
        ],
        [hit()],
    )[0]

    assert result.references_visible_evidence is True
    assert result.lexical_support == 0.0
    assert result.supported is False
    assert result.unsupported_reason == "citation has no lexical support"


def test_multiple_claims_and_duplicate_citations_are_stable() -> None:
    second_hit = hit(
        chunk_id="chunk-approval",
        doc_id="doc-approval",
        matched_text="Managers approve remote work requests.",
        context_text="Managers approve remote work requests.",
    )
    results = verify_claims(
        [
            Claim(
                claim_id="claim-days",
                text="Employees may work remotely three days per month.",
                cited_chunk_ids=["chunk-remote", "chunk-remote"],
            ),
            Claim(
                claim_id="claim-approval",
                text="Managers approve remote work requests.",
                cited_chunk_ids=["chunk-approval"],
            ),
        ],
        [hit(), second_hit],
    )

    assert [result.claim_id for result in results] == [
        "claim-days",
        "claim-approval",
    ]
    assert results[0].cited_chunk_ids == ["chunk-remote"]
    assert all(result.supported for result in results)


def test_mixed_visible_and_unknown_references_fail_correctness() -> None:
    result = verify_claims(
        [
            Claim(
                claim_id="claim-1",
                text="Employees may work remotely three days per month.",
                cited_chunk_ids=["chunk-remote", "unknown-chunk"],
            )
        ],
        [hit()],
    )[0]

    assert result.references_visible_evidence is False
    assert result.supported is False


def test_duplicate_visible_chunk_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="visible chunk IDs"):
        verify_claims(
            [Claim(claim_id="claim-1", text="A claim")],
            [hit(), hit()],
        )
