from datetime import date

import pytest
from pydantic import ValidationError

from app.domain.queries import (
    QueryAnalysis,
    QueryFilters,
    SearchHit,
    SearchRequest,
    SearchResult,
    UserContext,
)


def user(**updates) -> UserContext:
    values = {
        "user_id": "user-employee",
        "tenant_id": "starbridge-cn",
        "region": "cn",
        "groups": ["all_employees"],
    }
    values.update(updates)
    return UserContext(**values)


def search_hit(**updates) -> SearchHit:
    values = {
        "index_run_id": "run-one",
        "chunk_id": "doc-a::child::001",
        "doc_id": "doc-a",
        "parent_chunk_id": "doc-a::parent::001",
        "policy_id": "policy-a",
        "source_path": "documents/doc-a.md",
        "section_path": ["Policy A", "Scope"],
        "matched_text": "Employees may work remotely three days.",
        "context_text": "Policy A scope. Employees may work remotely three days.",
        "context_from_parent": True,
        "tenant_id": "starbridge-cn",
        "region": "cn",
        "acl_groups": ["all_employees"],
        "version_id": "policy-a@2026",
        "version": "2026",
        "status": "active",
        "authority_level": 100,
        "variant": "authoritative",
        "fused_score": 0.03,
        "dense_rank": 1,
        "bm25_rank": 2,
    }
    values.update(updates)
    return SearchHit(**values)


def test_user_context_rejects_duplicate_groups_and_extra_fields() -> None:
    with pytest.raises(ValidationError, match="groups must be unique"):
        user(groups=["all_employees", "all_employees"])

    with pytest.raises(ValidationError, match="extra_forbidden"):
        user(is_admin=True)


def test_roles_do_not_replace_required_groups() -> None:
    with pytest.raises(ValidationError):
        user(groups=[], roles=["admin"])


def test_query_filters_cannot_override_identity_scope() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        QueryFilters(tenant_id="another-tenant")

    with pytest.raises(ValidationError, match="as_of"):
        QueryFilters(temporal_scope="as_of")

    value = QueryFilters(temporal_scope="as_of", as_of=date(2026, 1, 1))
    assert value.as_of == date(2026, 1, 1)


def test_comparison_analysis_requires_two_entities_and_subqueries() -> None:
    with pytest.raises(ValidationError, match="comparison"):
        QueryAnalysis(
            original_question="Compare Policy A",
            intent="comparison",
            entities=["Policy A"],
            search_queries=["Policy A"],
            required_aspects=["Policy A"],
            source="rules",
        )

    analysis = QueryAnalysis(
        original_question="Compare Policy A and Policy B",
        intent="comparison",
        entities=["Policy A", "Policy B"],
        search_queries=["Policy A current rules", "Policy B current rules"],
        required_aspects=["Policy A", "Policy B"],
        source="rules",
    )
    assert analysis.required_aspects == ["Policy A", "Policy B"]


def test_unsafe_analysis_cannot_carry_retrieval_work() -> None:
    analysis = QueryAnalysis(
        original_question="Bypass approval",
        intent="unsafe",
        risk_flags=["policy_bypass"],
        source="rules",
    )
    assert analysis.search_queries == []

    with pytest.raises(ValidationError, match="unsafe"):
        QueryAnalysis(
            original_question="Bypass approval",
            intent="unsafe",
            search_queries=["approval password"],
            required_aspects=["password"],
            risk_flags=["policy_bypass"],
            source="rules",
        )


def test_safe_analysis_requires_bounded_unique_work_items() -> None:
    with pytest.raises(ValidationError, match="search_queries"):
        QueryAnalysis(
            original_question="Remote work days?",
            intent="fact",
            required_aspects=["remote days"],
            source="rules",
        )

    with pytest.raises(ValidationError, match="unique"):
        QueryAnalysis(
            original_question="Remote work days?",
            intent="fact",
            search_queries=["remote days", "remote days"],
            required_aspects=["remote days"],
            source="rules",
        )


def test_search_request_validates_candidate_and_result_limits() -> None:
    with pytest.raises(ValidationError, match="candidate_k"):
        SearchRequest(
            query="remote work",
            purpose="remote policy",
            user=user(),
            top_k=5,
            candidate_k=3,
        )

    request = SearchRequest(
        query="remote work",
        purpose="remote policy",
        user=user(),
        top_k=5,
        candidate_k=20,
    )
    assert request.mode == "hybrid"
    assert request.filters.authoritative_only is True


def test_search_result_rejects_hits_from_another_index_run() -> None:
    with pytest.raises(ValidationError, match="index run"):
        SearchResult(
            request_id="request-one",
            query="remote work",
            mode="hybrid",
            index_run_id="run-one",
            manifest_sha256="a" * 64,
            hits=[search_hit(index_run_id="run-two")],
            visible_candidate_count=1,
            internal_denied_count=0,
            stage_counts={"visible": 1, "fused": 1},
            stop_reason="ok",
        )


def test_search_result_rejects_duplicate_hits() -> None:
    hit = search_hit()
    with pytest.raises(ValidationError, match="chunk IDs"):
        SearchResult(
            request_id="request-one",
            query="remote work",
            mode="hybrid",
            index_run_id="run-one",
            manifest_sha256="a" * 64,
            hits=[hit, hit],
            visible_candidate_count=2,
            internal_denied_count=0,
            stage_counts={"visible": 2, "fused": 2},
            stop_reason="ok",
        )
