from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.queries import (
    QueryFilters,
    SearchRequest,
    SearchResult,
    UserContext,
)
from app.retrieval.entity_scope import (
    EntityCatalog,
    EntityCatalogEntry,
    EntityDocumentBinding,
    EntityScopedSearchBackend,
)


def _catalog() -> EntityCatalog:
    return EntityCatalog(
        schema_version="test_entity_catalog_v1",
        producer="tests",
        entries=[
            EntityCatalogEntry(
                entity_id="johnson-johnson",
                display_name="Johnson & Johnson",
                aliases=["Johnson & Johnson", "JnJ", "J&J"],
                documents=[
                    EntityDocumentBinding(
                        policy_id="jnj-2021",
                        years=[2021],
                    ),
                    EntityDocumentBinding(
                        policy_id="jnj-2022",
                        years=[2022],
                    ),
                ],
            ),
            EntityCatalogEntry(
                entity_id="american-express",
                display_name="American Express",
                aliases=["American Express", "AMEX"],
                documents=[
                    EntityDocumentBinding(
                        policy_id="amex-2022",
                        years=[2022],
                    )
                ],
            ),
        ],
    )


def _request(query: str, *, policy_ids: list[str] | None = None) -> SearchRequest:
    return SearchRequest(
        request_id="entity-scope-test",
        query=query,
        purpose="test entity metadata scoping",
        user=UserContext(
            user_id="user",
            tenant_id="tenant",
            region="global",
            groups=["finance"],
        ),
        filters=QueryFilters(
            policy_ids=policy_ids or [],
            temporal_scope="all",
        ),
        top_k=5,
        candidate_k=20,
    )


class CapturingBackend:
    def __init__(self) -> None:
        self.requests: list[SearchRequest] = []

    def search(self, request: SearchRequest) -> SearchResult:
        self.requests.append(request)
        return SearchResult(
            request_id=request.request_id,
            query=request.query,
            mode=request.mode,
            index_run_id="test-index",
            manifest_sha256="a" * 64,
            hits=[],
            visible_candidate_count=0,
            internal_denied_count=0,
            stage_counts={"metadata_visible": 0},
            stop_reason="no_match",
        )


def test_entity_catalog_resolves_public_alias_and_fiscal_year() -> None:
    resolution = _catalog().resolve(
        "Are JnJ's FY2022 financials those of a high growth company?",
        strict_year_scope=True,
    )

    assert resolution is not None
    assert resolution.entity_ids == ["johnson-johnson"]
    assert resolution.matched_aliases == ["JnJ"]
    assert resolution.years == [2022]
    assert resolution.policy_ids == ["jnj-2022"]


def test_entity_catalog_treats_year_as_soft_scope_by_default() -> None:
    resolution = _catalog().resolve(
        "Is growth in JnJ's adjusted EPS expected to accelerate in FY2023?"
    )

    assert resolution is not None
    assert resolution.years == [2023]
    assert resolution.policy_ids == ["jnj-2021", "jnj-2022"]


def test_entity_catalog_keeps_all_entity_documents_without_year() -> None:
    resolution = _catalog().resolve("Compare Johnson & Johnson and AMEX")

    assert resolution is not None
    assert resolution.entity_ids == ["johnson-johnson", "american-express"]
    assert resolution.policy_ids == ["jnj-2021", "jnj-2022", "amex-2022"]


def test_entity_catalog_does_not_scope_unknown_query() -> None:
    assert _catalog().resolve("What is the travel approval process?") is None


def test_entity_catalog_rejects_alias_ambiguity() -> None:
    with pytest.raises(ValidationError, match="ambiguous"):
        EntityCatalog(
            schema_version="test_entity_catalog_v1",
            producer="tests",
            entries=[
                EntityCatalogEntry(
                    entity_id="one",
                    display_name="One",
                    aliases=["shared"],
                    documents=[
                        EntityDocumentBinding(policy_id="one-policy", years=[])
                    ],
                ),
                EntityCatalogEntry(
                    entity_id="two",
                    display_name="Two",
                    aliases=["Shared"],
                    documents=[
                        EntityDocumentBinding(policy_id="two-policy", years=[])
                    ],
                ),
            ],
        )


def test_scoped_backend_applies_policy_filter_and_emits_stage_counts() -> None:
    backend = CapturingBackend()
    scoped = EntityScopedSearchBackend(backend, _catalog())

    result = scoped.search(_request("What changed for AMEX in FY2022?"))

    assert backend.requests[0].filters.policy_ids == ["amex-2022"]
    assert backend.requests[0].filters.temporal_scope == "all"
    assert result.stage_counts["entity_scope_entities"] == 1
    assert result.stage_counts["entity_scope_policy_ids"] == 1
    assert result.stage_counts["entity_scope_searches"] == 1
    assert scoped.counters.scoped_query_count == 1
    assert scoped.counters.year_scoped_query_count == 1


def test_scoped_backend_uses_exact_year_then_entity_wide_fallback() -> None:
    backend = CapturingBackend()
    scoped = EntityScopedSearchBackend(backend, _catalog())

    result = scoped.search(_request("What changed for JnJ in FY2022?"))

    assert [request.filters.policy_ids for request in backend.requests] == [
        ["jnj-2022"],
        ["jnj-2021", "jnj-2022"],
    ]
    assert result.stage_counts["entity_scope_searches"] == 2
    assert scoped.counters.dual_scope_query_count == 1


def test_scoped_backend_refuses_conflicting_explicit_policy_filter() -> None:
    scoped = EntityScopedSearchBackend(CapturingBackend(), _catalog())

    with pytest.raises(ValueError, match="conflicts"):
        scoped.search(
            _request(
                "What changed for AMEX in FY2022?",
                policy_ids=["jnj-2022"],
            )
        )
