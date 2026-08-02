from __future__ import annotations

import re
import time
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from app.external_datasets.finqa_descriptor_selector_v1 import (
    DescriptorSelectionsV1,
    RoleDescriptorSelectionV1,
)
from app.external_datasets.finqa_role_compatibility import (
    _role_anchor_tokens,
    _tokens,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v1 import (
    MAX_CATALOG_DESCRIPTORS,
    SafeCandidateDescriptorV1,
    SafeDescriptorCatalogV1,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)


RETRIEVER_VERSION = "finqa_deterministic_descriptor_retriever_v1"
MAX_DESCRIPTOR_REFS_PER_ROLE = 4
MAX_QUESTION_CHARS = 2_000
_PERIOD = re.compile(r"\b(?:19|20)\d{2}\b")
_SEMANTIC_HINTS = {
    "total": frozenset({"total", "overall", "aggregate", "net"}),
    "old_value": frozenset({"old", "prior", "previous", "beginning"}),
    "new_value": frozenset({"new", "current", "ending"}),
    "divisor": frozenset({"divisor", "base"}),
}


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class DescriptorRankV1(_StrictFrozenModel):
    descriptor_id: str = Field(pattern=r"^desc-[0-9a-f]{16}$")
    score: float
    score_reasons: tuple[str, ...]


class RoleDescriptorRankingV1(_StrictFrozenModel):
    role_id: str = Field(pattern=r"^role-0[1-8]$")
    ranked_descriptors: tuple[DescriptorRankV1, ...] = Field(
        min_length=1,
        max_length=MAX_CATALOG_DESCRIPTORS,
    )


@dataclass(frozen=True)
class DeterministicDescriptorRetrieverResultV1:
    retriever_version: str
    model: str
    selections: DescriptorSelectionsV1
    rankings: tuple[RoleDescriptorRankingV1, ...]
    generation_calls: int
    latency_ms: float


def _descriptor_text(descriptor: SafeCandidateDescriptorV1) -> str:
    return " ".join(
        value
        for value in (
            descriptor.metric,
            descriptor.entity,
            descriptor.row_header,
            descriptor.column_header,
        )
        if value
    )


def _score_descriptor(
    *,
    question: str,
    question_tokens: frozenset[str],
    anchor_tokens: frozenset[str],
    semantic_role: str,
    question_periods: frozenset[str],
    descriptor: SafeCandidateDescriptorV1,
) -> tuple[float, tuple[str, ...]]:
    descriptor_text = _descriptor_text(descriptor)
    descriptor_tokens = _tokens(descriptor_text)
    overlap = question_tokens & descriptor_tokens
    score = 0.0
    reasons: list[str] = []

    if overlap:
        score += len(overlap) * 6.0
        score += 12.0 * len(overlap) / max(1, len(descriptor_tokens))
        reasons.append("question_token_overlap")

    normalized_question = " ".join(question.casefold().split())
    for field in (
        descriptor.metric,
        descriptor.entity,
        descriptor.row_header,
        descriptor.column_header,
    ):
        if field and len(_tokens(field)) >= 2 and field in normalized_question:
            score += 30.0
            reasons.append("exact_field_phrase")
            break

    anchor_overlap = anchor_tokens & descriptor_tokens
    if anchor_overlap:
        score += len(anchor_overlap) * 18.0
        score += 80.0 * len(anchor_overlap) / max(1, len(anchor_tokens))
        reasons.append("role_anchor_overlap")

    semantic_overlap = _SEMANTIC_HINTS.get(
        semantic_role, frozenset()
    ) & descriptor_tokens
    if semantic_overlap:
        score += len(semantic_overlap) * 2.0
        reasons.append("semantic_role_hint")

    descriptor_periods = frozenset(descriptor.periods)
    if question_periods and question_periods & descriptor_periods:
        score += 8.0
        reasons.append("question_period_match")
    elif question_periods and descriptor_periods:
        score -= 1.0
        reasons.append("question_period_mismatch_soft")

    if descriptor.source_kind == "table_cell":
        score += 0.5
        reasons.append("table_cell")
    return score, tuple(reasons)


class DeterministicFinQADescriptorRetrieverV1:
    model = "deterministic-host-retriever"

    def select(
        self,
        *,
        question: str,
        skeleton: SemanticProgramSkeletonV2,
        catalog: SafeDescriptorCatalogV1,
    ) -> DeterministicDescriptorRetrieverResultV1:
        normalized_question = " ".join(question.split())
        if (
            not normalized_question
            or len(normalized_question) > MAX_QUESTION_CHARS
        ):
            raise ValueError("descriptor retriever question is outside budget")
        if not catalog.descriptors:
            raise ValueError("descriptor retriever catalog is empty")

        started = time.perf_counter()
        question_tokens = _tokens(normalized_question)
        question_periods = frozenset(_PERIOD.findall(normalized_question))
        rankings: list[RoleDescriptorRankingV1] = []
        selections: list[RoleDescriptorSelectionV1] = []
        for role in skeleton.roles:
            anchor_tokens = _role_anchor_tokens(
                normalized_question,
                role.semantic_role,
            )
            scored = []
            for descriptor in catalog.descriptors:
                score, reasons = _score_descriptor(
                    question=normalized_question,
                    question_tokens=question_tokens,
                    anchor_tokens=anchor_tokens,
                    semantic_role=role.semantic_role,
                    question_periods=question_periods,
                    descriptor=descriptor,
                )
                scored.append(
                    DescriptorRankV1(
                        descriptor_id=descriptor.descriptor_id,
                        score=score,
                        score_reasons=reasons,
                    )
                )
            scored.sort(key=lambda item: (-item.score, item.descriptor_id))
            ranked = tuple(scored)
            selected = tuple(
                item.descriptor_id
                for item in ranked[:MAX_DESCRIPTOR_REFS_PER_ROLE]
            )
            rankings.append(
                RoleDescriptorRankingV1(
                    role_id=role.role_id,
                    ranked_descriptors=ranked,
                )
            )
            selections.append(
                RoleDescriptorSelectionV1(
                    role_id=role.role_id,
                    descriptor_ids=selected,
                )
            )
        latency_ms = (time.perf_counter() - started) * 1_000
        return DeterministicDescriptorRetrieverResultV1(
            retriever_version=RETRIEVER_VERSION,
            model=self.model,
            selections=DescriptorSelectionsV1(
                selections=tuple(selections),
            ),
            rankings=tuple(rankings),
            generation_calls=0,
            latency_ms=latency_ms,
        )


__all__ = [
    "DescriptorRankV1",
    "DeterministicDescriptorRetrieverResultV1",
    "DeterministicFinQADescriptorRetrieverV1",
    "RETRIEVER_VERSION",
    "RoleDescriptorRankingV1",
]
