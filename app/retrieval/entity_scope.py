from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.queries import SearchRequest, SearchResult


_YEAR_PATTERN = re.compile(r"\b(?:fy\s*)?((?:19|20)\d{2})\b", re.IGNORECASE)


class EntityDocumentBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    policy_id: str = Field(min_length=1)
    years: list[int] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_years(self) -> EntityDocumentBinding:
        if self.years != sorted(set(self.years)):
            raise ValueError("entity document years must be sorted and unique")
        if any(year < 1900 or year > 2100 for year in self.years):
            raise ValueError("entity document year is outside the supported range")
        return self


class EntityCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    entity_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    aliases: list[str] = Field(min_length=1, max_length=30)
    documents: list[EntityDocumentBinding] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_entry(self) -> EntityCatalogEntry:
        normalized_aliases = [_normalize_phrase(alias) for alias in self.aliases]
        if any(not alias for alias in normalized_aliases):
            raise ValueError("entity aliases must contain letters or numbers")
        if len(normalized_aliases) != len(set(normalized_aliases)):
            raise ValueError("entity aliases must be unique after normalization")
        policy_ids = [document.policy_id for document in self.documents]
        if len(policy_ids) != len(set(policy_ids)):
            raise ValueError("entity document policy IDs must be unique")
        return self


class EntityCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str = Field(min_length=1)
    producer: str = Field(min_length=1)
    entries: list[EntityCatalogEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_catalog(self) -> EntityCatalog:
        entity_ids = [entry.entity_id for entry in self.entries]
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("entity IDs must be unique")
        owners: dict[str, str] = {}
        for entry in self.entries:
            for alias in entry.aliases:
                normalized = _normalize_phrase(alias)
                owner = owners.setdefault(normalized, entry.entity_id)
                if owner != entry.entity_id:
                    raise ValueError(
                        f"entity alias {alias!r} is ambiguous across entries"
                    )
        return self

    def resolve(
        self,
        query: str,
        *,
        max_policy_ids: int = 20,
        strict_year_scope: bool = False,
    ) -> EntityScopeResolution | None:
        if max_policy_ids < 1:
            raise ValueError("max_policy_ids must be positive")
        normalized_query = f" {_normalize_phrase(query)} "
        years = sorted(
            {
                int(match.group(1))
                for match in _YEAR_PATTERN.finditer(query)
            }
        )
        matched: list[tuple[EntityCatalogEntry, str]] = []
        for entry in self.entries:
            aliases = sorted(
                entry.aliases,
                key=lambda alias: (-len(_normalize_phrase(alias)), alias.casefold()),
            )
            alias = next(
                (
                    candidate
                    for candidate in aliases
                    if f" {_normalize_phrase(candidate)} " in normalized_query
                ),
                None,
            )
            if alias is not None:
                matched.append((entry, alias))
        if not matched:
            return None

        policy_ids: list[str] = []
        for entry, _ in matched:
            year_documents = [
                document
                for document in entry.documents
                if years and set(document.years).intersection(years)
            ]
            selected = (
                year_documents
                if strict_year_scope and year_documents
                else entry.documents
            )
            policy_ids.extend(document.policy_id for document in selected)
        policy_ids = list(dict.fromkeys(policy_ids))
        if len(policy_ids) > max_policy_ids:
            return None
        return EntityScopeResolution(
            entity_ids=[entry.entity_id for entry, _ in matched],
            matched_aliases=[alias for _, alias in matched],
            years=years,
            policy_ids=policy_ids,
        )

    def canonical_sha256(self) -> str:
        payload = self.model_dump(mode="json")
        encoded = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class EntityScopeResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    entity_ids: list[str] = Field(min_length=1)
    matched_aliases: list[str] = Field(min_length=1)
    years: list[int] = Field(default_factory=list)
    policy_ids: list[str] = Field(min_length=1, max_length=20)


class SearchBackend(Protocol):
    def search(self, request: SearchRequest) -> SearchResult: ...


@dataclass
class EntityScopeCounters:
    query_count: int = 0
    scoped_query_count: int = 0
    year_scoped_query_count: int = 0
    dual_scope_query_count: int = 0


class EntityScopedSearchBackend:
    def __init__(
        self,
        backend: SearchBackend,
        catalog: EntityCatalog,
        *,
        strict_year_scope: bool = False,
    ) -> None:
        self.backend = backend
        self.catalog = catalog
        self.strict_year_scope = strict_year_scope
        self.counters = EntityScopeCounters()

    def search(self, request: SearchRequest) -> SearchResult:
        self.counters.query_count += 1
        resolution = self.catalog.resolve(
            request.query,
            strict_year_scope=self.strict_year_scope,
        )
        if resolution is None:
            return self.backend.search(request)
        self.counters.scoped_query_count += 1
        if resolution.years:
            self.counters.year_scoped_query_count += 1

        existing = request.filters.policy_ids
        broad_policy_ids = _combine_policy_filters(
            resolution.policy_ids,
            existing,
        )
        strict_resolution = (
            self.catalog.resolve(
                request.query,
                strict_year_scope=True,
            )
            if resolution.years and not self.strict_year_scope
            else None
        )
        strict_policy_ids = (
            _combine_policy_filters(strict_resolution.policy_ids, existing)
            if strict_resolution is not None
            else broad_policy_ids
        )
        primary_request = _with_policy_scope(request, strict_policy_ids)
        search_count = 1
        if strict_policy_ids != broad_policy_ids:
            self.counters.dual_scope_query_count += 1
            broad_request = _with_policy_scope(request, broad_policy_ids)
            search_many = getattr(self.backend, "search_many", None)
            if callable(search_many):
                result, broad_result = search_many(
                    [primary_request, broad_request]
                )
            else:
                result = self.backend.search(primary_request)
                broad_result = self.backend.search(broad_request)
            result = _merge_results(result, broad_result, request)
            search_count = 2
        else:
            result = self.backend.search(primary_request)
        stage_counts = {
            **result.stage_counts,
            "entity_scope_entities": len(resolution.entity_ids),
            "entity_scope_policy_ids": len(broad_policy_ids),
            "entity_scope_searches": search_count,
        }
        return result.model_copy(update={"stage_counts": stage_counts})


def _combine_policy_filters(
    resolved: list[str],
    existing: list[str],
) -> list[str]:
    if not existing:
        return resolved
    allowed = set(existing)
    combined = [policy_id for policy_id in resolved if policy_id in allowed]
    if not combined:
        raise ValueError("entity scope conflicts with explicit policy filters")
    return combined


def _with_policy_scope(
    request: SearchRequest,
    policy_ids: list[str],
) -> SearchRequest:
    filters = request.filters.model_copy(update={"policy_ids": policy_ids})
    return request.model_copy(update={"filters": filters})


def _merge_results(
    primary: SearchResult,
    secondary: SearchResult,
    request: SearchRequest,
) -> SearchResult:
    selected = []
    seen_chunks: set[str] = set()
    per_doc: Counter[str] = Counter()
    for hit in [*primary.hits, *secondary.hits]:
        if hit.chunk_id in seen_chunks:
            continue
        if per_doc[hit.doc_id] >= request.max_chunks_per_doc:
            continue
        seen_chunks.add(hit.chunk_id)
        per_doc[hit.doc_id] += 1
        selected.append(hit)
        if len(selected) == request.top_k:
            break
    stage_counts = {
        key: max(primary.stage_counts.get(key, 0), secondary.stage_counts.get(key, 0))
        for key in set(primary.stage_counts) | set(secondary.stage_counts)
    }
    stage_counts["returned"] = len(selected)
    stop_reason = "ok" if selected else secondary.stop_reason
    return primary.model_copy(
        update={
            "hits": selected,
            "visible_candidate_count": max(
                primary.visible_candidate_count,
                secondary.visible_candidate_count,
            ),
            "internal_denied_count": max(
                primary.internal_denied_count,
                secondary.internal_denied_count,
            ),
            "stage_counts": stage_counts,
            "stop_reason": stop_reason,
        }
    )


def _normalize_phrase(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


__all__ = [
    "EntityCatalog",
    "EntityCatalogEntry",
    "EntityDocumentBinding",
    "EntityScopeResolution",
    "EntityScopedSearchBackend",
]
