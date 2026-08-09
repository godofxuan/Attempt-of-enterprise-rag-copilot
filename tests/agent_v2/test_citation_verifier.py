from __future__ import annotations

import pytest

from app.agent.citation_verifier import verify_claims
from app.domain.documents import SourceLocator
from app.domain.evidence import Claim
from app.domain.queries import SearchHit
from app.domain.retrieved_security import AdmittedEvidenceChunk
from tests.v2_test_support import admit_search_hit


def hit(**updates) -> AdmittedEvidenceChunk:
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
    return admit_search_hit(SearchHit(**values))


def test_missing_citation_is_a_hard_failure() -> None:
    result = verify_claims(
        [Claim(claim_id="claim-1", text="Remote work is limited to three days.")],
        [hit()],
    )[0]

    assert result.citation_present is False
    assert result.references_visible_evidence is False
    assert result.lexical_support == 0.0
    assert result.supported is False
    assert result.unsupported_reason == "missing_citation"


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
    assert result.unsupported_reason == "invisible_citation"


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
    assert result.unsupported_reason == "no_lexical_support"


def test_one_shared_word_is_insufficient_lexical_support() -> None:
    result = verify_claims(
        [
            Claim(
                claim_id="claim-1",
                text="Policy approvals require finance review.",
                cited_chunk_ids=["chunk-remote"],
            )
        ],
        [
            hit(
                matched_text="Policy archives retain signed records.",
                context_text="Policy archives retain signed records.",
            )
        ],
    )[0]

    assert 0.0 < result.lexical_support < 0.5
    assert result.supported is False
    assert result.unsupported_reason == "insufficient_lexical_support"


def test_numeric_mismatch_rejects_five_days_against_three_days() -> None:
    result = verify_claims(
        [
            Claim(
                claim_id="claim-1",
                text="Employees may work remotely 5 days per month.",
                cited_chunk_ids=["chunk-remote"],
            )
        ],
        [
            hit(
                matched_text="Employees may work remotely 3 days per month.",
                context_text="Employees may work remotely 3 days per month.",
            )
        ],
    )[0]

    assert result.lexical_support > 0.8
    assert result.supported is False
    assert result.unsupported_reason == "numeric_mismatch"


def test_amount_mismatch_rejects_8000_against_5000() -> None:
    result = verify_claims(
        [
            Claim(
                claim_id="claim-1",
                text="The travel reimbursement limit is 8000 yuan.",
                cited_chunk_ids=["chunk-remote"],
            )
        ],
        [
            hit(
                matched_text="The travel reimbursement limit is 5000 yuan.",
                context_text="The travel reimbursement limit is 5000 yuan.",
            )
        ],
    )[0]

    assert result.supported is False
    assert result.unsupported_reason == "numeric_mismatch"


def test_percentage_mismatch_rejects_12_percent_against_10_percent() -> None:
    result = verify_claims(
        [
            Claim(
                claim_id="claim-1",
                text="The approved reimbursement rate is 12%.",
                cited_chunk_ids=["chunk-remote"],
            )
        ],
        [
            hit(
                matched_text="The approved reimbursement rate is 10%.",
                context_text="The approved reimbursement rate is 10%.",
            )
        ],
    )[0]

    assert result.supported is False
    assert result.unsupported_reason == "numeric_mismatch"


def test_negation_mismatch_rejects_allow_against_prohibit() -> None:
    result = verify_claims(
        [
            Claim(
                claim_id="claim-1",
                text="Employees may use unapproved suppliers.",
                cited_chunk_ids=["chunk-remote"],
            )
        ],
        [
            hit(
                matched_text="Employees may not use unapproved suppliers.",
                context_text="Employees may not use unapproved suppliers.",
            )
        ],
    )[0]

    assert result.lexical_support > 0.8
    assert result.supported is False
    assert result.unsupported_reason == "negation_mismatch"


@pytest.mark.parametrize(
    ("claim_text", "evidence_text"),
    [
        (
            "Revenue was 10 million.",
            "Revenue was not 10 million.",
        ),
        (
            "Revenue was not 10 million.",
            "Revenue was 10 million.",
        ),
        (
            "收入为100万元。",
            "收入并非100万元。",
        ),
        (
            "收入并非100万元。",
            "收入为100万元。",
        ),
        (
            "The office is open on weekends.",
            "The office is not open on weekends.",
        ),
        (
            "Policy A applies in 2026.",
            "Policy A does not apply in 2026.",
        ),
        (
            "Employees use unapproved suppliers.",
            "Employees may not use unapproved suppliers.",
        ),
        (
            "The approved quantity is 20 units.",
            "The approved quantity is not 20 units.",
        ),
    ],
    ids=[
        "english-affirmative-vs-negative-numeric",
        "english-negative-vs-affirmative-numeric",
        "chinese-affirmative-vs-negative",
        "chinese-negative-vs-affirmative",
        "english-non-numeric",
        "year",
        "permission-modality",
        "quantity",
    ],
)
def test_asymmetric_explicit_negation_is_a_contradiction(
    claim_text: str,
    evidence_text: str,
) -> None:
    result = verify_claims(
        [
            Claim(
                claim_id="claim-asymmetric-negation",
                text=claim_text,
                cited_chunk_ids=["chunk-remote"],
            )
        ],
        [
            hit(
                matched_text=evidence_text,
                context_text=evidence_text,
            )
        ],
    )[0]

    assert result.supported is False
    assert result.unsupported_reason == "negation_mismatch"


def test_unrelated_negative_sentence_does_not_override_matching_support() -> None:
    result = verify_claims(
        [
            Claim(
                claim_id="claim-revenue",
                text="Revenue was 10 million.",
                cited_chunk_ids=["chunk-remote"],
            )
        ],
        [
            hit(
                parent_chunk_id="parent-revenue",
                matched_text="Revenue was 10 million.",
                context_text=(
                    "Revenue was 10 million. Expenses were not 10 million."
                ),
                context_from_parent=True,
            )
        ],
    )[0]

    assert result.supported is True
    assert result.unsupported_reason is None


def test_date_status_mismatch_rejects_effective_against_repealed() -> None:
    result = verify_claims(
        [
            Claim(
                claim_id="claim-1",
                text="Policy A became effective on 2026-01-01.",
                cited_chunk_ids=["chunk-remote"],
            )
        ],
        [
            hit(
                matched_text="Policy A was repealed on 2026-01-01.",
                context_text="Policy A was repealed on 2026-01-01.",
            )
        ],
    )[0]

    assert result.lexical_support >= 0.5
    assert result.supported is False
    assert result.unsupported_reason == "date_mismatch"


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
