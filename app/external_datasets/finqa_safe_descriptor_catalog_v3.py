from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa_numeric_evidence_v2 import NumericCandidateV2
from app.external_datasets.finqa_safe_descriptor_catalog_v1 import (
    MAX_CATALOG_DESCRIPTORS,
    MAX_DESCRIPTOR_FIELD_CHARS,
    MAX_DESCRIPTOR_PERIODS,
    MAX_SOURCE_CANDIDATES,
    _period,
    _safe_field,
)
from app.security.retrieved_content import RetrievedContentGuard


CATALOG_VERSION = "finqa_safe_descriptor_catalog_v3"
MAX_LOCAL_CONTEXT_HINT_CHARS = 128
MAX_TOPIC_HINT_CHARS = 160
MAX_TOPIC_CONTEXTS = 32
_NUMBER = re.compile(r"[-+]?\d[\d,.]*(?:%|bps?)?", re.IGNORECASE)
_TOKEN = re.compile(r"[a-z]+(?:['&/-][a-z]+)*", re.IGNORECASE)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class RetrievableSafeCandidateDescriptorV3(_StrictFrozenModel):
    descriptor_id: str = Field(pattern=r"^desc-[0-9a-f]{16}$")
    metric: str | None = Field(default=None, max_length=96)
    entity: str | None = Field(default=None, max_length=96)
    row_header: str | None = Field(default=None, max_length=96)
    column_header: str | None = Field(default=None, max_length=96)
    local_context_hint: str | None = Field(
        default=None,
        max_length=MAX_LOCAL_CONTEXT_HINT_CHARS,
    )
    topic_hint: str | None = Field(default=None, max_length=MAX_TOPIC_HINT_CHARS)
    periods: tuple[str, ...] = Field(max_length=MAX_DESCRIPTOR_PERIODS)
    source_kind: str = Field(min_length=1, max_length=32)
    candidate_count: int = Field(ge=1, le=MAX_SOURCE_CANDIDATES)


class RetrievableSafeDescriptorCatalogV3(_StrictFrozenModel):
    catalog_version: str = CATALOG_VERSION
    source_candidate_count: int = Field(ge=1, le=MAX_SOURCE_CANDIDATES)
    represented_candidate_count: int = Field(ge=1, le=MAX_SOURCE_CANDIDATES)
    quarantined_candidate_count: int = Field(ge=0, le=MAX_SOURCE_CANDIDATES)
    descriptor_count: int = Field(ge=1, le=MAX_CATALOG_DESCRIPTORS)
    descriptors: tuple[RetrievableSafeCandidateDescriptorV3, ...] = Field(
        min_length=1,
        max_length=MAX_CATALOG_DESCRIPTORS,
    )
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_catalog(self) -> RetrievableSafeDescriptorCatalogV3:
        descriptor_ids = tuple(item.descriptor_id for item in self.descriptors)
        if (
            descriptor_ids != tuple(sorted(descriptor_ids))
            or len(descriptor_ids) != len(set(descriptor_ids))
            or self.descriptor_count != len(descriptor_ids)
        ):
            raise ValueError("retrievable descriptor catalog IDs are invalid")
        if self.represented_candidate_count != sum(
            item.candidate_count for item in self.descriptors
        ):
            raise ValueError("retrievable descriptor accounting is invalid")
        if (
            self.represented_candidate_count + self.quarantined_candidate_count
            > self.source_candidate_count
        ):
            raise ValueError("retrievable descriptor source accounting is invalid")
        payload = self.model_dump(mode="json", exclude={"catalog_sha256"})
        if self.catalog_sha256 != hashlib.sha256(
            _canonical_bytes(payload)
        ).hexdigest():
            raise ValueError("retrievable descriptor catalog hash is invalid")
        return self


@dataclass(frozen=True)
class RetrievableSafeDescriptorCatalogBuildV3:
    catalog: RetrievableSafeDescriptorCatalogV3
    candidate_ids_by_descriptor: dict[str, tuple[str, ...]]

    def candidate_ids_for_descriptors(
        self,
        descriptor_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not descriptor_ids or len(descriptor_ids) != len(set(descriptor_ids)):
            raise ValueError("descriptor selection must be unique and non-empty")
        if not set(descriptor_ids).issubset(self.candidate_ids_by_descriptor):
            raise ValueError("descriptor selection is outside the catalog")
        return tuple(
            candidate_id
            for descriptor_id in descriptor_ids
            for candidate_id in self.candidate_ids_by_descriptor[descriptor_id]
        )


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _safe_tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return tuple(_TOKEN.findall(_NUMBER.sub(" ", normalized)))


def _bounded_tokens(tokens: tuple[str, ...], max_chars: int) -> str | None:
    selected: list[str] = []
    used = 0
    for token in tokens:
        added = len(token) + (1 if selected else 0)
        if used + added > max_chars:
            break
        selected.append(token)
        used += added
    result = " ".join(selected)
    return result if len(result) >= 2 else None


def _bounded_suffix(tokens: tuple[str, ...], max_chars: int) -> tuple[str, ...]:
    selected: list[str] = []
    used = 0
    for token in reversed(tokens):
        added = len(token) + (1 if selected else 0)
        if used + added > max_chars:
            break
        selected.append(token)
        used += added
    return tuple(reversed(selected))


def _balanced_local_context_hint(
    *,
    context: str,
    raw_text: str,
) -> str | None:
    normalized_context = unicodedata.normalize("NFKC", context)
    normalized_raw = unicodedata.normalize("NFKC", raw_text)
    position = normalized_context.casefold().find(normalized_raw.casefold())
    if position < 0:
        return _bounded_tokens(
            _safe_tokens(normalized_context),
            MAX_LOCAL_CONTEXT_HINT_CHARS,
        )

    left = _safe_tokens(normalized_context[:position])
    right = _safe_tokens(normalized_context[position + len(normalized_raw) :])
    side_budget = (MAX_LOCAL_CONTEXT_HINT_CHARS - 1) // 2
    selected = _bounded_suffix(left, side_budget) + _safe_tokens(normalized_raw)
    right_text = _bounded_tokens(right, side_budget)
    selected += tuple(right_text.split() if right_text else ())
    return _bounded_tokens(selected, MAX_LOCAL_CONTEXT_HINT_CHARS)


def _base_key(candidate: NumericCandidateV2) -> tuple[str | None, ...]:
    return (
        _safe_field(candidate.metric),
        _safe_field(candidate.entity),
        _safe_field(candidate.row_header),
        _safe_field(candidate.column_header),
        candidate.source_kind,
    )


def _descriptor_id(key: tuple[str | None, ...]) -> str:
    return f"desc-{hashlib.sha256(_canonical_bytes(key)).hexdigest()[:16]}"


def _topic_hint_for_group(
    *,
    base_key: tuple[str | None, ...],
    evidence_context_by_id: Mapping[str, str],
    guard: RetrievedContentGuard,
) -> str | None:
    descriptor_tokens = {
        token
        for value in base_key[:4]
        if value
        for token in _safe_tokens(value)
    }
    ranked: list[tuple[int, float, str, str]] = []
    narrative_contexts = sorted(
        (
            (evidence_id, context)
            for evidence_id, context in evidence_context_by_id.items()
            if evidence_id.startswith("text_")
        ),
        key=lambda item: item[0],
    )[:MAX_TOPIC_CONTEXTS]
    for evidence_id, context in narrative_contexts:
        hint = _bounded_tokens(_safe_tokens(context), MAX_TOPIC_HINT_CHARS)
        if hint is None or guard.scan(hint).disposition != "ADMIT":
            continue
        hint_tokens = set(_safe_tokens(hint))
        overlap = descriptor_tokens & hint_tokens
        coverage = len(overlap) / max(1, len(descriptor_tokens))
        ranked.append((len(overlap), coverage, evidence_id, hint))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2], item[3]))
    return ranked[0][3]


def build_retrievable_safe_descriptor_catalog_v3(
    *,
    candidates: tuple[NumericCandidateV2, ...],
    admitted_evidence_ids: set[str],
    evidence_context_by_id: Mapping[str, str],
    guard: RetrievedContentGuard,
) -> RetrievableSafeDescriptorCatalogBuildV3:
    if not candidates or len(candidates) > MAX_SOURCE_CANDIDATES:
        raise ValueError("retrievable descriptor source budget is invalid")
    candidate_ids = tuple(item.candidate_id for item in candidates)
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("retrievable descriptor source candidates are duplicated")
    if set(evidence_context_by_id) - admitted_evidence_ids:
        raise ValueError("retrievable descriptor text is not admitted")
    if any(
        guard.scan(context).disposition != "ADMIT"
        for context in evidence_context_by_id.values()
    ):
        raise ValueError("retrievable descriptor context failed Guard admission")
    if any(
        item.role != "operand" or item.evidence_id not in admitted_evidence_ids
        for item in candidates
    ):
        raise ValueError("retrievable descriptor source candidate is not admitted")
    if any(
        item.evidence_id not in evidence_context_by_id for item in candidates
    ):
        raise ValueError("retrievable descriptor candidate context is incomplete")

    grouped: dict[
        tuple[str | None, ...],
        list[tuple[NumericCandidateV2, str | None]],
    ] = {}
    quarantined = 0
    for candidate in candidates:
        raw_projection = "\n".join(
            value
            for value in (
                candidate.metric,
                candidate.entity,
                candidate.row_header,
                candidate.column_header,
            )
            if value
        )
        if guard.scan(raw_projection).disposition != "ADMIT":
            quarantined += 1
            continue
        local_hint = None
        context = evidence_context_by_id[candidate.evidence_id]
        local_hint = _balanced_local_context_hint(
            context=context,
            raw_text=candidate.raw_text,
        )
        base_key = _base_key(candidate)
        safe_projection = "\n".join(
            value for value in (*base_key, local_hint) if value
        )
        if guard.scan(safe_projection).disposition != "ADMIT":
            quarantined += 1
            continue
        structured = any(base_key[:4])
        context_fingerprint = hashlib.sha256(
            _canonical_bytes(_safe_tokens(context))
        ).hexdigest()
        grouping_key = (
            base_key
            if structured
            else (*base_key, f"context-{context_fingerprint}")
        )
        grouped.setdefault(grouping_key, []).append((candidate, local_hint))

    ranked_groups = sorted(
        grouped.items(),
        key=lambda item: (-len(item[1]), _descriptor_id(item[0])),
    )[:MAX_CATALOG_DESCRIPTORS]
    descriptors: list[RetrievableSafeCandidateDescriptorV3] = []
    mapping: dict[str, tuple[str, ...]] = {}
    for key, members in ranked_groups:
        descriptor_id = _descriptor_id(key)
        base_key = key[:5]
        metric, entity, row_header, column_header, source_kind = base_key
        local_hints = tuple(
            sorted({hint for _, hint in members if hint is not None})
        )
        local_hint = (
            max(local_hints, key=lambda value: (len(value), value))
            if local_hints
            else None
        )
        topic_hint = _topic_hint_for_group(
            base_key=base_key,
            evidence_context_by_id=evidence_context_by_id,
            guard=guard,
        )
        periods = tuple(
            sorted(
                {
                    period
                    for candidate, _ in members
                    if (period := _period(candidate)) is not None
                }
            )[:MAX_DESCRIPTOR_PERIODS]
        )
        member_ids = tuple(sorted(candidate.candidate_id for candidate, _ in members))
        descriptors.append(
            RetrievableSafeCandidateDescriptorV3(
                descriptor_id=descriptor_id,
                metric=metric,
                entity=entity,
                row_header=row_header,
                column_header=column_header,
                local_context_hint=local_hint,
                topic_hint=topic_hint,
                periods=periods,
                source_kind=source_kind,
                candidate_count=len(member_ids),
            )
        )
        mapping[descriptor_id] = member_ids
    descriptors.sort(key=lambda item: item.descriptor_id)
    if not descriptors:
        raise ValueError("retrievable descriptor catalog is empty")
    payload = {
        "catalog_version": CATALOG_VERSION,
        "source_candidate_count": len(candidates),
        "represented_candidate_count": sum(
            item.candidate_count for item in descriptors
        ),
        "quarantined_candidate_count": quarantined,
        "descriptor_count": len(descriptors),
        "descriptors": [item.model_dump(mode="json") for item in descriptors],
    }
    catalog = RetrievableSafeDescriptorCatalogV3(
        **payload,
        catalog_sha256=hashlib.sha256(_canonical_bytes(payload)).hexdigest(),
    )
    return RetrievableSafeDescriptorCatalogBuildV3(
        catalog=catalog,
        candidate_ids_by_descriptor=mapping,
    )


def catalog_prompt_payload_v3(
    catalog: RetrievableSafeDescriptorCatalogV3,
) -> dict[str, object]:
    return {
        "catalog_version": catalog.catalog_version,
        "descriptors": [
            descriptor.model_dump(mode="json", exclude={"candidate_count"})
            for descriptor in catalog.descriptors
        ],
    }


__all__ = [
    "CATALOG_VERSION",
    "MAX_LOCAL_CONTEXT_HINT_CHARS",
    "MAX_TOPIC_CONTEXTS",
    "MAX_TOPIC_HINT_CHARS",
    "RetrievableSafeCandidateDescriptorV3",
    "RetrievableSafeDescriptorCatalogBuildV3",
    "RetrievableSafeDescriptorCatalogV3",
    "build_retrievable_safe_descriptor_catalog_v3",
    "catalog_prompt_payload_v3",
]
