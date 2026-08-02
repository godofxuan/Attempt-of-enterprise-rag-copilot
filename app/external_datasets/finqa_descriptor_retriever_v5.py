from __future__ import annotations

import re
import time

from app.external_datasets.finqa_descriptor_retriever_v1 import (
    DescriptorRankV1,
    DeterministicDescriptorRetrieverResultV1,
    RoleDescriptorRankingV1,
)
from app.external_datasets.finqa_descriptor_retriever_v2 import (
    _financial_tokens,
    _role_anchor_tokens_v2,
    _score_descriptor_v2,
)
from app.external_datasets.finqa_descriptor_selector_v1 import (
    DescriptorSelectionsV1,
    RoleDescriptorSelectionV1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeCandidateDescriptorV3,
    RetrievableSafeDescriptorCatalogV3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)


RETRIEVER_VERSION = "finqa_deterministic_descriptor_retriever_v5"
MAX_DESCRIPTOR_REFS_PER_ROLE = 4
MAX_QUESTION_CHARS = 2_000
_PERIOD = re.compile(r"\b(?:19|20)\d{2}\b")


def _primary_text(descriptor: RetrievableSafeCandidateDescriptorV3) -> str:
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


def _weighted_overlap(
    *,
    query_tokens: frozenset[str],
    field_tokens: frozenset[str],
    token_weight: float,
    coverage_weight: float,
) -> float:
    overlap = query_tokens & field_tokens
    if not overlap:
        return 0.0
    return (
        len(overlap) * token_weight
        + coverage_weight * len(overlap) / max(1, len(query_tokens))
    )


def _score_descriptor_v5(
    *,
    question: str,
    question_tokens: frozenset[str],
    anchor_tokens: frozenset[str],
    semantic_role: str,
    question_periods: frozenset[str],
    descriptor: RetrievableSafeCandidateDescriptorV3,
) -> tuple[float, tuple[str, ...]]:
    primary_tokens = _financial_tokens(_primary_text(descriptor))
    local_tokens = _financial_tokens(descriptor.local_context_hint)
    topic_tokens = _financial_tokens(descriptor.topic_hint)
    score, baseline_reasons = _score_descriptor_v2(
        question=question,
        question_tokens=question_tokens,
        anchor_tokens=anchor_tokens,
        semantic_role=semantic_role,
        question_periods=question_periods,
        descriptor=descriptor,
    )
    reasons = list(baseline_reasons)
    has_primary_signal = bool(
        question_tokens & primary_tokens or anchor_tokens & primary_tokens
    )
    if has_primary_signal:
        return score, tuple(reasons)

    local_question = _weighted_overlap(
        query_tokens=question_tokens,
        field_tokens=local_tokens,
        token_weight=4.0,
        coverage_weight=8.0,
    )
    if local_question:
        score += local_question
        reasons.append("local_context_question_overlap")
    topic_question = _weighted_overlap(
        query_tokens=question_tokens,
        field_tokens=topic_tokens,
        token_weight=2.5,
        coverage_weight=5.0,
    )
    if topic_question:
        score += topic_question
        reasons.append("topic_question_overlap")

    normalized_question = " ".join(question.casefold().split())
    for field in (
        descriptor.metric,
        descriptor.entity,
        descriptor.row_header,
        descriptor.column_header,
    ):
        if field and len(_financial_tokens(field)) >= 2 and field in normalized_question:
            score += 32.0
            reasons.append("exact_primary_phrase")
            break

    primary_anchor = _weighted_overlap(
        query_tokens=anchor_tokens,
        field_tokens=primary_tokens,
        token_weight=20.0,
        coverage_weight=90.0,
    )
    if primary_anchor:
        score += primary_anchor
        reasons.append("primary_role_anchor_overlap")
    local_anchor = _weighted_overlap(
        query_tokens=anchor_tokens,
        field_tokens=local_tokens,
        token_weight=14.0,
        coverage_weight=65.0,
    )
    if local_anchor:
        score += local_anchor
        reasons.append("local_context_role_anchor_overlap")
    topic_anchor = _weighted_overlap(
        query_tokens=anchor_tokens,
        field_tokens=topic_tokens,
        token_weight=10.0,
        coverage_weight=45.0,
    )
    if topic_anchor:
        score += topic_anchor
        reasons.append("topic_role_anchor_overlap")
    return score, tuple(reasons)


class DeterministicFinQADescriptorRetrieverV5:
    model = "deterministic-host-retriever-v5"

    def select(
        self,
        *,
        question: str,
        skeleton: SemanticProgramSkeletonV2,
        catalog: RetrievableSafeDescriptorCatalogV3,
    ) -> DeterministicDescriptorRetrieverResultV1:
        normalized_question = " ".join(question.split())
        if not normalized_question or len(normalized_question) > MAX_QUESTION_CHARS:
            raise ValueError("descriptor retriever v5 question is outside budget")
        started = time.perf_counter()
        question_tokens = _financial_tokens(normalized_question)
        question_periods = frozenset(_PERIOD.findall(normalized_question))
        rankings = []
        selections = []
        for role in skeleton.roles:
            anchor_tokens = _role_anchor_tokens_v2(
                normalized_question,
                role.semantic_role,
            )
            scored = []
            for descriptor in catalog.descriptors:
                score, reasons = _score_descriptor_v5(
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
            rankings.append(
                RoleDescriptorRankingV1(
                    role_id=role.role_id,
                    ranked_descriptors=ranked,
                )
            )
            selections.append(
                RoleDescriptorSelectionV1(
                    role_id=role.role_id,
                    descriptor_ids=tuple(
                        item.descriptor_id
                        for item in ranked[:MAX_DESCRIPTOR_REFS_PER_ROLE]
                    ),
                )
            )
        return DeterministicDescriptorRetrieverResultV1(
            retriever_version=RETRIEVER_VERSION,
            model=self.model,
            selections=DescriptorSelectionsV1(selections=tuple(selections)),
            rankings=tuple(rankings),
            generation_calls=0,
            latency_ms=(time.perf_counter() - started) * 1_000,
        )


__all__ = [
    "DeterministicFinQADescriptorRetrieverV5",
    "RETRIEVER_VERSION",
]
