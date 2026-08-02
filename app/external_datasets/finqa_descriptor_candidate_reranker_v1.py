from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa_numeric_evidence_v2 import NumericCandidateV2
from app.external_datasets.finqa_role_compatibility import (
    _candidate_score,
    _role_anchor_tokens,
    _tokens,
)
from app.external_datasets.finqa_role_compatibility_v2 import (
    _expected_period_v2,
    hard_compatible_candidates_for_role_v2,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeDescriptorCatalogBuildV3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
    SemanticRoleSpecV2,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    FinancialQuestionIntentV2,
)


RERANKER_VERSION = "finqa_descriptor_candidate_reranker_v1"
MAX_SELECTED_DESCRIPTORS = 4
MAX_RANKED_CANDIDATES = 8
MAX_SOURCE_CANDIDATES = 128
LOCAL_CONTEXT_RADIUS_CHARS = 160
MAX_DESCRIPTOR_PRIORITY_STEP = 8.0


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class DescriptorAwareCandidateRankV1(_StrictFrozenModel):
    candidate_id: str = Field(pattern=r"^num-[0-9a-f]{20}$")
    descriptor_id: str = Field(pattern=r"^desc-[0-9a-f]{16}$")
    descriptor_rank: int = Field(ge=1, le=MAX_SELECTED_DESCRIPTORS)
    in_descriptor_rank: int = Field(ge=1, le=MAX_SOURCE_CANDIDATES)
    score: float
    score_reasons: tuple[str, ...]


class DescriptorAwareCandidateRerankerResultV1(_StrictFrozenModel):
    reranker_version: str = RERANKER_VERSION
    role_id: str = Field(pattern=r"^role-0[1-8]$")
    selected_descriptor_ids: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_SELECTED_DESCRIPTORS,
    )
    considered_candidate_count: int = Field(ge=0, le=MAX_SOURCE_CANDIDATES)
    ranked_candidates: tuple[DescriptorAwareCandidateRankV1, ...] = Field(
        min_length=0,
        max_length=MAX_RANKED_CANDIDATES,
    )
    generation_calls: int = Field(default=0, ge=0, le=0)
    candidate_identity_preserved: bool = True

    @model_validator(mode="after")
    def validate_unique_candidates(
        self,
    ) -> DescriptorAwareCandidateRerankerResultV1:
        candidate_ids = tuple(item.candidate_id for item in self.ranked_candidates)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("descriptor-aware reranker duplicated a candidate")
        if any(
            item.descriptor_id not in self.selected_descriptor_ids
            for item in self.ranked_candidates
        ):
            raise ValueError("descriptor-aware reranker escaped descriptor scope")
        return self

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(item.candidate_id for item in self.ranked_candidates)


def _candidate_local_context(
    candidate: NumericCandidateV2,
    evidence_context: str,
) -> str:
    span = candidate.provenance_span
    if evidence_context[span.start : span.end] == candidate.raw_text:
        candidate_start = span.start
        candidate_end = span.end
    else:
        candidate_start = evidence_context.casefold().find(
            candidate.raw_text.casefold()
        )
        if candidate_start < 0:
            return evidence_context
        candidate_end = candidate_start + len(candidate.raw_text)
    start = max(0, candidate_start - LOCAL_CONTEXT_RADIUS_CHARS)
    end = min(
        len(evidence_context),
        candidate_end + LOCAL_CONTEXT_RADIUS_CHARS,
    )
    return evidence_context[start:end]


def rerank_descriptor_candidates_v1(
    *,
    question: str,
    role: SemanticRoleSpecV2,
    skeleton: SemanticProgramSkeletonV2,
    selected_descriptor_ids: tuple[str, ...],
    catalog_build: RetrievableSafeDescriptorCatalogBuildV3,
    candidates: Sequence[NumericCandidateV2],
    intent: FinancialQuestionIntentV2,
    evidence_context_by_id: Mapping[str, str],
    evidence_rank_by_id: Mapping[str, int] | None = None,
    descriptor_priority_step: float = 0.0,
    candidate_local_weight: float = 1.0,
) -> DescriptorAwareCandidateRerankerResultV1:
    normalized_question = " ".join(question.split())
    if not normalized_question or len(normalized_question) > 2_000:
        raise ValueError("descriptor-aware reranker question is outside budget")
    if (
        not selected_descriptor_ids
        or len(selected_descriptor_ids) > MAX_SELECTED_DESCRIPTORS
        or len(selected_descriptor_ids) != len(set(selected_descriptor_ids))
    ):
        raise ValueError("descriptor-aware reranker selection is invalid")
    if not set(selected_descriptor_ids).issubset(
        catalog_build.candidate_ids_by_descriptor
    ):
        raise ValueError("descriptor-aware reranker selection is outside catalog")
    if not candidates or len(candidates) > MAX_SOURCE_CANDIDATES:
        raise ValueError("descriptor-aware reranker source budget is invalid")
    if not 0.0 <= descriptor_priority_step <= MAX_DESCRIPTOR_PRIORITY_STEP:
        raise ValueError("descriptor-aware reranker priority step is invalid")
    if not 0.0 <= candidate_local_weight <= 1.0:
        raise ValueError("descriptor-aware reranker local weight is invalid")
    candidate_by_id = {item.candidate_id: item for item in candidates}
    if len(candidate_by_id) != len(candidates):
        raise ValueError("descriptor-aware reranker candidates are duplicated")
    selected_candidate_ids = tuple(
        candidate_id
        for descriptor_id in selected_descriptor_ids
        for candidate_id in catalog_build.candidate_ids_by_descriptor[
            descriptor_id
        ]
    )
    if (
        len(selected_candidate_ids) != len(set(selected_candidate_ids))
        or not set(selected_candidate_ids).issubset(candidate_by_id)
    ):
        raise ValueError("descriptor-aware reranker mapping is invalid")
    if any(
        candidate_by_id[candidate_id].evidence_id not in evidence_context_by_id
        for candidate_id in selected_candidate_ids
    ):
        raise ValueError("descriptor-aware reranker context is incomplete")

    expected_period = _expected_period_v2(
        question=normalized_question,
        role=role,
        intent=intent,
    )
    hard_compatible_ids = {
        item.candidate_id
        for item in hard_compatible_candidates_for_role_v2(
            role=role,
            skeleton=skeleton,
            candidates=candidates,
            intent=intent,
            question=normalized_question,
        )
    }
    if evidence_rank_by_id is None:
        stable_evidence_rank = {
            evidence_id: index
            for index, evidence_id in enumerate(sorted(evidence_context_by_id))
        }
    else:
        stable_evidence_rank = dict(evidence_rank_by_id)
        if (
            not set(stable_evidence_rank).issubset(evidence_context_by_id)
            or any(
                not isinstance(rank, int) or rank < 0
                for rank in stable_evidence_rank.values()
            )
            or len(stable_evidence_rank.values())
            != len(set(stable_evidence_rank.values()))
            or any(
                candidate_by_id[candidate_id].evidence_id
                not in stable_evidence_rank
                for candidate_id in selected_candidate_ids
            )
        ):
            raise ValueError("descriptor-aware reranker evidence ranks are invalid")
    question_tokens = _tokens(normalized_question)
    anchor_tokens = _role_anchor_tokens(
        normalized_question,
        role.semantic_role,
    )
    ranked_groups: list[list[DescriptorAwareCandidateRankV1]] = []
    for descriptor_rank, descriptor_id in enumerate(
        selected_descriptor_ids,
        start=1,
    ):
        scored: list[tuple[float, str, tuple[str, ...]]] = []
        for candidate_id in catalog_build.candidate_ids_by_descriptor[
            descriptor_id
        ]:
            if candidate_id not in hard_compatible_ids:
                continue
            candidate = candidate_by_id[candidate_id]
            score, reasons = _candidate_score(
                question_tokens=question_tokens,
                anchor_tokens=anchor_tokens,
                candidate=candidate,
                expected_period=expected_period,
                evidence_context=evidence_context_by_id.get(candidate.evidence_id),
                evidence_rank=stable_evidence_rank[candidate.evidence_id],
            )
            local_tokens = _tokens(
                _candidate_local_context(
                    candidate,
                    evidence_context_by_id[candidate.evidence_id],
                )
            )
            local_question_overlap = len(question_tokens & local_tokens)
            local_anchor_overlap = len(anchor_tokens & local_tokens)
            expanded_reasons = list(reasons)
            if local_question_overlap and candidate_local_weight:
                score += candidate_local_weight * min(
                    12.0,
                    local_question_overlap * 2.0,
                )
                expanded_reasons.append("candidate_local_question_overlap")
            if anchor_tokens and local_anchor_overlap and candidate_local_weight:
                score += candidate_local_weight * min(
                    14.0,
                    local_anchor_overlap * 3.5,
                )
                expanded_reasons.append("candidate_local_role_anchor_overlap")
            priority_bonus = (
                MAX_SELECTED_DESCRIPTORS - descriptor_rank
            ) * descriptor_priority_step
            if priority_bonus:
                score += priority_bonus
                expanded_reasons.append("selected_descriptor_rank_prior")
            scored.append((score, candidate_id, tuple(expanded_reasons)))
        scored.sort(key=lambda item: (-item[0], item[1]))
        ranked_groups.append(
            [
                DescriptorAwareCandidateRankV1(
                    candidate_id=candidate_id,
                    descriptor_id=descriptor_id,
                    descriptor_rank=descriptor_rank,
                    in_descriptor_rank=in_descriptor_rank,
                    score=score,
                    score_reasons=reasons,
                )
                for in_descriptor_rank, (score, candidate_id, reasons) in enumerate(
                    scored,
                    start=1,
                )
            ]
        )

    all_ranked = [item for group in ranked_groups for item in group]
    all_ranked.sort(
        key=lambda item: (-item.score, item.descriptor_rank, item.candidate_id)
    )
    selected = all_ranked[:MAX_RANKED_CANDIDATES]
    nonempty_descriptor_ids = {
        group[0].descriptor_id for group in ranked_groups if group
    }
    for descriptor_id in selected_descriptor_ids:
        if (
            descriptor_id not in nonempty_descriptor_ids
            or any(item.descriptor_id == descriptor_id for item in selected)
        ):
            continue
        counts = {
            selected_id: sum(
                item.descriptor_id == selected_id for item in selected
            )
            for selected_id in selected_descriptor_ids
        }
        replacement_index = next(
            (
                index
                for index in range(len(selected) - 1, -1, -1)
                if counts[selected[index].descriptor_id] > 1
            ),
            None,
        )
        if replacement_index is None:
            break
        replacement = next(
            group[0]
            for group in ranked_groups
            if group and group[0].descriptor_id == descriptor_id
        )
        selected[replacement_index] = replacement
        selected.sort(
            key=lambda item: (-item.score, item.descriptor_rank, item.candidate_id)
        )
    return DescriptorAwareCandidateRerankerResultV1(
        role_id=role.role_id,
        selected_descriptor_ids=selected_descriptor_ids,
        considered_candidate_count=sum(len(group) for group in ranked_groups),
        ranked_candidates=tuple(selected),
        candidate_identity_preserved=True,
    )


__all__ = [
    "DescriptorAwareCandidateRankV1",
    "DescriptorAwareCandidateRerankerResultV1",
    "RERANKER_VERSION",
    "rerank_descriptor_candidates_v1",
]
