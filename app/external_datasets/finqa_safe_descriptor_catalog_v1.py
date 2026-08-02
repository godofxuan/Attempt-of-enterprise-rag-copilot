from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa_numeric_evidence_v2 import NumericCandidateV2
from app.security.retrieved_content import RetrievedContentGuard


CATALOG_VERSION = "finqa_safe_descriptor_catalog_v1"
MAX_SOURCE_CANDIDATES = 128
MAX_CATALOG_DESCRIPTORS = 64
MAX_DESCRIPTOR_FIELD_CHARS = 96
MAX_DESCRIPTOR_PERIODS = 16
_NUMBER = re.compile(r"[-+]?\d[\d,.]*(?:%|bps?)?", re.IGNORECASE)
_TOKEN = re.compile(r"[a-z]+(?:['&/-][a-z]+)*", re.IGNORECASE)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class SafeCandidateDescriptorV1(_StrictFrozenModel):
    descriptor_id: str = Field(pattern=r"^desc-[0-9a-f]{16}$")
    metric: str | None = Field(default=None, max_length=96)
    entity: str | None = Field(default=None, max_length=96)
    row_header: str | None = Field(default=None, max_length=96)
    column_header: str | None = Field(default=None, max_length=96)
    periods: tuple[str, ...] = Field(max_length=MAX_DESCRIPTOR_PERIODS)
    source_kind: str = Field(min_length=1, max_length=32)
    candidate_count: int = Field(ge=1, le=MAX_SOURCE_CANDIDATES)


class SafeDescriptorCatalogV1(_StrictFrozenModel):
    catalog_version: str = CATALOG_VERSION
    source_candidate_count: int = Field(ge=1, le=MAX_SOURCE_CANDIDATES)
    represented_candidate_count: int = Field(ge=1, le=MAX_SOURCE_CANDIDATES)
    quarantined_candidate_count: int = Field(ge=0, le=MAX_SOURCE_CANDIDATES)
    descriptor_count: int = Field(ge=1, le=MAX_CATALOG_DESCRIPTORS)
    descriptors: tuple[SafeCandidateDescriptorV1, ...] = Field(
        min_length=1,
        max_length=MAX_CATALOG_DESCRIPTORS,
    )
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_catalog(self) -> SafeDescriptorCatalogV1:
        descriptor_ids = tuple(item.descriptor_id for item in self.descriptors)
        if (
            descriptor_ids != tuple(sorted(descriptor_ids))
            or len(descriptor_ids) != len(set(descriptor_ids))
            or self.descriptor_count != len(descriptor_ids)
        ):
            raise ValueError("safe descriptor catalog IDs are invalid")
        if self.represented_candidate_count != sum(
            item.candidate_count for item in self.descriptors
        ):
            raise ValueError("safe descriptor candidate accounting is invalid")
        if (
            self.represented_candidate_count
            + self.quarantined_candidate_count
            > self.source_candidate_count
        ):
            raise ValueError("safe descriptor source accounting is invalid")
        payload = self.model_dump(mode="json", exclude={"catalog_sha256"})
        expected = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
        if self.catalog_sha256 != expected:
            raise ValueError("safe descriptor catalog hash is invalid")
        return self


@dataclass(frozen=True)
class SafeDescriptorCatalogBuildV1:
    catalog: SafeDescriptorCatalogV1
    candidate_ids_by_descriptor: dict[str, tuple[str, ...]]

    def candidate_ids_for_descriptors(
        self,
        descriptor_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        if (
            not descriptor_ids
            or len(descriptor_ids) != len(set(descriptor_ids))
        ):
            raise ValueError("descriptor selection must be unique and non-empty")
        allowed = set(self.candidate_ids_by_descriptor)
        if not set(descriptor_ids).issubset(allowed):
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


def _safe_field(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", value).casefold()
    without_numbers = _NUMBER.sub(" ", normalized)
    tokens = _TOKEN.findall(without_numbers)
    result = " ".join(tokens)[:MAX_DESCRIPTOR_FIELD_CHARS].strip()
    return result if len(result) >= 2 else None


def _period(candidate: NumericCandidateV2) -> str | None:
    if candidate.period is not None:
        value = " ".join(candidate.period.split())[:MAX_DESCRIPTOR_FIELD_CHARS]
        return value or None
    if candidate.fiscal_year is not None:
        return str(candidate.fiscal_year)
    return None


def _semantic_key(candidate: NumericCandidateV2) -> tuple[str | None, ...]:
    return (
        _safe_field(candidate.metric),
        _safe_field(candidate.entity),
        _safe_field(candidate.row_header),
        _safe_field(candidate.column_header),
        candidate.source_kind,
    )


def _descriptor_id(key: tuple[str | None, ...]) -> str:
    digest = hashlib.sha256(_canonical_bytes(key)).hexdigest()[:16]
    return f"desc-{digest}"


def build_safe_descriptor_catalog_v1(
    *,
    candidates: tuple[NumericCandidateV2, ...],
    admitted_evidence_ids: set[str],
    guard: RetrievedContentGuard,
) -> SafeDescriptorCatalogBuildV1:
    if not candidates or len(candidates) > MAX_SOURCE_CANDIDATES:
        raise ValueError("safe descriptor source candidate budget is invalid")
    candidate_ids = tuple(item.candidate_id for item in candidates)
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("safe descriptor source candidates are duplicated")
    if any(
        candidate.role != "operand"
        or candidate.evidence_id not in admitted_evidence_ids
        for candidate in candidates
    ):
        raise ValueError("safe descriptor source candidate is not admitted")

    grouped: dict[tuple[str | None, ...], list[NumericCandidateV2]] = {}
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
        key = _semantic_key(candidate)
        safe_projection = "\n".join(value for value in key if value)
        if guard.scan(safe_projection).disposition != "ADMIT":
            quarantined += 1
            continue
        grouped.setdefault(key, []).append(candidate)

    ranked_groups = sorted(
        grouped.items(),
        key=lambda item: (-len(item[1]), _descriptor_id(item[0])),
    )[:MAX_CATALOG_DESCRIPTORS]
    descriptors = []
    mapping: dict[str, tuple[str, ...]] = {}
    for key, members in ranked_groups:
        descriptor_id = _descriptor_id(key)
        metric, entity, row_header, column_header, source_kind = key
        periods = tuple(
            sorted(
                {
                    period
                    for candidate in members
                    if (period := _period(candidate)) is not None
                }
            )[:MAX_DESCRIPTOR_PERIODS]
        )
        member_ids = tuple(sorted(item.candidate_id for item in members))
        descriptors.append(
            SafeCandidateDescriptorV1(
                descriptor_id=descriptor_id,
                metric=metric,
                entity=entity,
                row_header=row_header,
                column_header=column_header,
                periods=periods,
                source_kind=source_kind,
                candidate_count=len(member_ids),
            )
        )
        mapping[descriptor_id] = member_ids
    descriptors.sort(key=lambda item: item.descriptor_id)
    if not descriptors:
        raise ValueError("safe descriptor catalog is empty")
    payload = {
        "catalog_version": CATALOG_VERSION,
        "source_candidate_count": len(candidates),
        "represented_candidate_count": sum(
            item.candidate_count for item in descriptors
        ),
        "quarantined_candidate_count": quarantined,
        "descriptor_count": len(descriptors),
        "descriptors": [
            item.model_dump(mode="json") for item in descriptors
        ],
    }
    catalog = SafeDescriptorCatalogV1(
        **payload,
        catalog_sha256=hashlib.sha256(_canonical_bytes(payload)).hexdigest(),
    )
    return SafeDescriptorCatalogBuildV1(
        catalog=catalog,
        candidate_ids_by_descriptor=mapping,
    )


def catalog_prompt_payload_v1(
    catalog: SafeDescriptorCatalogV1,
) -> dict[str, object]:
    return {
        "catalog_version": catalog.catalog_version,
        "descriptors": [
            descriptor.model_dump(
                mode="json",
                exclude={"candidate_count"},
            )
            for descriptor in catalog.descriptors
        ],
    }


__all__ = [
    "CATALOG_VERSION",
    "MAX_CATALOG_DESCRIPTORS",
    "MAX_DESCRIPTOR_FIELD_CHARS",
    "SafeCandidateDescriptorV1",
    "SafeDescriptorCatalogBuildV1",
    "SafeDescriptorCatalogV1",
    "build_safe_descriptor_catalog_v1",
    "catalog_prompt_payload_v1",
]
