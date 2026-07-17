from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.documents import DocumentStatus, SourceLocator


QueryIntent = Literal[
    "fact",
    "process",
    "comparison",
    "completeness",
    "no_answer",
    "unsafe",
]
AnalysisSource = Literal["rules", "model", "rules+model"]
TemporalScope = Literal["current", "historical", "as_of", "all"]
RetrievalMode = Literal["bm25", "dense", "hybrid"]
SearchStopReason = Literal["ok", "no_match", "no_visible_evidence", "timeout"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _validate_unique(values: list[str], label: str) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
    return values


class UserContext(StrictModel):
    user_id: str = Field(min_length=1, max_length=200)
    tenant_id: str = Field(min_length=1, max_length=200)
    region: str = Field(min_length=1, max_length=100)
    groups: list[str] = Field(min_length=1, max_length=50)
    roles: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("groups")
    @classmethod
    def validate_groups(cls, values: list[str]) -> list[str]:
        return _validate_unique(values, "groups")

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, values: list[str]) -> list[str]:
        return _validate_unique(values, "roles")


class QueryFilters(StrictModel):
    departments: list[str] = Field(default_factory=list, max_length=20)
    policy_ids: list[str] = Field(default_factory=list, max_length=20)
    statuses: list[DocumentStatus] = Field(default_factory=list, max_length=2)
    temporal_scope: TemporalScope = "current"
    as_of: date | None = None
    authoritative_only: bool = True
    min_authority: int = Field(default=1, ge=1, le=100)

    @field_validator("departments", "policy_ids", "statuses")
    @classmethod
    def validate_unique_lists(cls, values: list[str]) -> list[str]:
        return _validate_unique(values, "filter values")

    @model_validator(mode="after")
    def validate_temporal_scope(self) -> QueryFilters:
        if self.temporal_scope == "as_of" and self.as_of is None:
            raise ValueError("as_of is required for temporal_scope='as_of'")
        if self.temporal_scope != "as_of" and self.as_of is not None:
            raise ValueError("as_of is only valid for temporal_scope='as_of'")
        return self


class QueryAnalysis(StrictModel):
    original_question: str = Field(min_length=1, max_length=2000)
    intent: QueryIntent
    entities: list[str] = Field(default_factory=list, max_length=8)
    search_queries: list[str] = Field(default_factory=list, max_length=4)
    required_aspects: list[str] = Field(default_factory=list, max_length=8)
    filters: QueryFilters = Field(default_factory=QueryFilters)
    risk_flags: list[str] = Field(default_factory=list, max_length=20)
    source: AnalysisSource

    @field_validator("entities", "search_queries", "required_aspects", "risk_flags")
    @classmethod
    def validate_unique_work(cls, values: list[str]) -> list[str]:
        return _validate_unique(values, "analysis values")

    @model_validator(mode="after")
    def validate_intent_work(self) -> QueryAnalysis:
        if self.intent == "unsafe":
            if not self.risk_flags:
                raise ValueError("unsafe analysis requires risk flags")
            if self.search_queries or self.required_aspects:
                raise ValueError("unsafe analysis cannot carry retrieval work")
            return self

        if not self.search_queries:
            raise ValueError("safe analysis requires search_queries")
        if not self.required_aspects:
            raise ValueError("safe analysis requires required_aspects")
        if self.intent == "comparison":
            if len(self.entities) < 2 or len(self.search_queries) < 2:
                raise ValueError(
                    "comparison analysis requires at least two entities and subqueries"
                )
            if not set(self.entities).issubset(self.required_aspects):
                raise ValueError("comparison entities must be required aspects")
        return self


class SearchRequest(StrictModel):
    request_id: str = Field(default="request", min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=1000)
    purpose: str = Field(min_length=1, max_length=500)
    user: UserContext
    filters: QueryFilters = Field(default_factory=QueryFilters)
    top_k: int = Field(default=5, ge=1, le=20)
    candidate_k: int = Field(default=20, ge=1, le=200)
    mode: RetrievalMode = "hybrid"
    include_parent: bool = True
    max_chunks_per_doc: int = Field(default=2, ge=1, le=10)
    timeout_ms: int = Field(default=5000, ge=1, le=120_000)

    @model_validator(mode="after")
    def validate_candidate_count(self) -> SearchRequest:
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be greater than or equal to top_k")
        return self


class SearchHit(StrictModel):
    index_run_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    parent_chunk_id: str | None = None
    policy_id: str | None = None
    source_path: str = Field(min_length=1)
    section_path: list[str] = Field(min_length=1)
    locator: SourceLocator | None = None
    matched_text: str = Field(min_length=1)
    context_text: str = Field(min_length=1)
    context_from_parent: bool = False
    tenant_id: str = Field(min_length=1)
    region: str = Field(min_length=1)
    acl_groups: list[str] = Field(min_length=1)
    version_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: DocumentStatus
    authority_level: int = Field(ge=1, le=100)
    variant: str = Field(min_length=1)
    fact_ids: list[str] = Field(default_factory=list)
    fused_score: float
    dense_score: float | None = None
    bm25_score: float | None = None
    dense_rank: int | None = Field(default=None, ge=1)
    bm25_rank: int | None = Field(default=None, ge=1)

    @field_validator("acl_groups", "fact_ids")
    @classmethod
    def validate_hit_lists(cls, values: list[str]) -> list[str]:
        return _validate_unique(values, "hit values")


class SearchResult(StrictModel):
    request_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    mode: RetrievalMode
    index_run_id: str = Field(min_length=1)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hits: list[SearchHit] = Field(default_factory=list)
    visible_candidate_count: int = Field(ge=0)
    internal_denied_count: int = Field(ge=0, exclude=True)
    stage_counts: dict[str, int] = Field(default_factory=dict)
    stop_reason: SearchStopReason

    @model_validator(mode="after")
    def validate_hits(self) -> SearchResult:
        chunk_ids = [hit.chunk_id for hit in self.hits]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("search result chunk IDs must be unique")
        if any(hit.index_run_id != self.index_run_id for hit in self.hits):
            raise ValueError("search hit index run must match result index run")
        if any(value < 0 for value in self.stage_counts.values()):
            raise ValueError("stage counts must be non-negative")
        if self.stop_reason == "ok" and not self.hits:
            raise ValueError("ok search result requires hits")
        return self


class FindRequest(StrictModel):
    request_id: str = Field(default="request", min_length=1)
    user: UserContext
    doc_id: str = Field(min_length=1)
    pattern: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=5, ge=1, le=20)
    timeout_ms: int = Field(default=3000, ge=1, le=120_000)


class FindMatch(StrictModel):
    doc_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    section_path: list[str] = Field(min_length=1)
    preview: str = Field(min_length=1, max_length=1000)


class FindResult(StrictModel):
    request_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    matches: list[FindMatch] = Field(default_factory=list)
    stop_reason: Literal["ok", "not_found", "timeout"]


class OpenRequest(StrictModel):
    request_id: str = Field(default="request", min_length=1)
    user: UserContext
    target_type: Literal["chunk", "parent", "document"]
    target_id: str = Field(min_length=1)
    max_chars: int = Field(default=4000, ge=1, le=20_000)
    timeout_ms: int = Field(default=3000, ge=1, le=120_000)


class OpenResult(StrictModel):
    request_id: str = Field(min_length=1)
    target_type: Literal["chunk", "parent", "document"]
    target_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    truncated: bool
    source_path: str = Field(min_length=1)
    section_path: list[str] = Field(default_factory=list)


__all__ = [
    "AnalysisSource",
    "FindMatch",
    "FindRequest",
    "FindResult",
    "OpenRequest",
    "OpenResult",
    "QueryAnalysis",
    "QueryFilters",
    "QueryIntent",
    "RetrievalMode",
    "SearchHit",
    "SearchRequest",
    "SearchResult",
    "SearchStopReason",
    "TemporalScope",
    "UserContext",
]
