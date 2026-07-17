from __future__ import annotations

import pytest

from app.agent.evidence_ledger import build_ledger
from app.domain.documents import SourceLocator
from app.domain.queries import QueryAnalysis, SearchHit


def hit(**updates) -> SearchHit:
    values = {
        "index_run_id": "run-one",
        "chunk_id": "chunk-a",
        "doc_id": "doc-a",
        "parent_chunk_id": None,
        "policy_id": "policy-a",
        "source_path": "documents/doc-a.md",
        "section_path": ["Policy A"],
        "locator": SourceLocator(kind="paragraph", start=1),
        "matched_text": "Policy A allows remote work three days.",
        "context_text": "Policy A allows remote work three days.",
        "context_from_parent": False,
        "tenant_id": "tenant-one",
        "region": "cn",
        "acl_groups": ["employees"],
        "version_id": "policy-a@2026",
        "version": "2026",
        "status": "active",
        "authority_level": 100,
        "variant": "authoritative",
        "fact_ids": ["fact-a"],
        "fused_score": 1.0,
        "bm25_score": 1.0,
        "bm25_rank": 1,
    }
    values.update(updates)
    return SearchHit(**values)


def comparison_analysis() -> QueryAnalysis:
    return QueryAnalysis(
        original_question="Compare Policy A and Policy B",
        intent="comparison",
        entities=["Policy A", "Policy B"],
        search_queries=["Policy A", "Policy B"],
        required_aspects=["Policy A", "Policy B"],
        source="rules",
    )


def test_comparison_one_side_has_half_coverage_and_requests_search() -> None:
    ledger = build_ledger(
        comparison_analysis(),
        {"Policy A": [hit()]},
    )

    assert ledger.supported_aspects == ["Policy A"]
    assert ledger.missing_aspects == ["Policy B"]
    assert ledger.coverage == 0.5
    assert ledger.recommended_action == "search"


def test_comparison_both_sides_are_ready_to_answer() -> None:
    ledger = build_ledger(
        comparison_analysis(),
        {
            "Policy A": [hit()],
            "Policy B": [
                hit(
                    chunk_id="chunk-b",
                    doc_id="doc-b",
                    policy_id="policy-b",
                    version_id="policy-b@2026",
                    fact_ids=["fact-b"],
                )
            ],
        },
    )

    assert ledger.supported_aspects == ["Policy A", "Policy B"]
    assert ledger.missing_aspects == []
    assert ledger.coverage == 1.0
    assert ledger.recommended_action == "answer"


def test_zero_visible_evidence_distinguishes_permission_from_no_match() -> None:
    denied = build_ledger(comparison_analysis(), {}, denied_only=True)
    missing = build_ledger(comparison_analysis(), {})

    assert denied.recommended_action == "permission"
    assert missing.recommended_action == "not_found"
    assert denied.items == missing.items == []


def test_equal_priority_conflict_remains_missing() -> None:
    support = hit(chunk_id="support-a")
    conflict = hit(
        chunk_id="conflict-a",
        doc_id="doc-conflict",
        matched_text="Policy A allows only one day.",
        context_text="Policy A allows only one day.",
    )

    ledger = build_ledger(
        comparison_analysis(),
        {"Policy A": [support]},
        conflicts={"Policy A": [conflict]},
    )

    assert ledger.supported_aspects == []
    assert ledger.conflicting_aspects == ["Policy A"]
    assert ledger.missing_aspects == ["Policy A", "Policy B"]
    assert ledger.recommended_action == "search"
    assert {item.relation for item in ledger.items} == {"supports", "conflicts"}


def test_higher_authority_or_current_evidence_resolves_conflict() -> None:
    analysis = QueryAnalysis(
        original_question="What is Policy A?",
        intent="fact",
        search_queries=["Policy A"],
        required_aspects=["answer"],
        source="rules",
    )
    support = hit(authority_level=100, status="active")
    lower_conflict = hit(
        chunk_id="old-conflict",
        authority_level=80,
        status="retired",
        version_id="policy-a@2024",
        version="2024",
    )

    ledger = build_ledger(
        analysis,
        {"answer": [support]},
        conflicts={"answer": [lower_conflict]},
    )

    assert ledger.supported_aspects == ["answer"]
    assert ledger.conflicting_aspects == []
    assert ledger.recommended_action == "answer"


@pytest.mark.parametrize(
    ("support_updates", "conflict_updates"),
    [
        ({"authority_level": 80}, {"authority_level": 100}),
        (
            {"authority_level": 100, "status": "retired"},
            {"authority_level": 100, "status": "active"},
        ),
    ],
)
def test_lower_priority_support_does_not_resolve_higher_priority_conflict(
    support_updates,
    conflict_updates,
) -> None:
    analysis = QueryAnalysis(
        original_question="What is Policy A?",
        intent="fact",
        search_queries=["Policy A"],
        required_aspects=["answer"],
        source="rules",
    )
    support = hit(chunk_id="lower-support", **support_updates)
    conflict = hit(
        chunk_id="higher-conflict",
        doc_id="doc-conflict",
        **conflict_updates,
    )

    ledger = build_ledger(
        analysis,
        {"answer": [support]},
        conflicts={"answer": [conflict]},
    )

    assert ledger.supported_aspects == []
    assert ledger.conflicting_aspects == ["answer"]
    assert ledger.missing_aspects == ["answer"]
    assert ledger.coverage == 0.0
    assert ledger.recommended_action == "search"


@pytest.mark.parametrize(
    ("evidence", "expected_action"),
    [
        ({"Policy A": [hit()]}, "partial"),
        ({}, "budget"),
    ],
)
def test_budget_exhaustion_returns_partial_or_budget(evidence, expected_action) -> None:
    ledger = build_ledger(
        comparison_analysis(),
        evidence,
        budget_exhausted=True,
    )

    assert ledger.recommended_action == expected_action


def test_evidence_cannot_claim_an_aspect_not_required_by_analysis() -> None:
    with pytest.raises(ValueError, match="required aspect"):
        build_ledger(
            comparison_analysis(),
            {"invented model aspect": [hit()]},
        )


def test_unsafe_analysis_cannot_build_an_evidence_ledger() -> None:
    analysis = QueryAnalysis(
        original_question="Bypass approval",
        intent="unsafe",
        risk_flags=["policy_bypass"],
        source="rules",
    )

    with pytest.raises(ValueError, match="unsafe"):
        build_ledger(analysis, {})
