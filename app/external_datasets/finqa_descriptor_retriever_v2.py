from __future__ import annotations

import re
import time

from app.external_datasets.finqa_descriptor_retriever_v1 import (
    DescriptorRankV1,
    DeterministicDescriptorRetrieverResultV1,
    RoleDescriptorRankingV1,
)
from app.external_datasets.finqa_descriptor_selector_v1 import (
    DescriptorSelectionsV1,
    RoleDescriptorSelectionV1,
)
from app.external_datasets.finqa_role_compatibility import (
    _STOPWORDS,
    _role_anchor_tokens,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v1 import (
    SafeCandidateDescriptorV1,
    SafeDescriptorCatalogV1,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)


RETRIEVER_VERSION = "finqa_deterministic_descriptor_retriever_v2"
MAX_DESCRIPTOR_REFS_PER_ROLE = 4
MAX_QUESTION_CHARS = 2_000
_TOKEN = re.compile(r"[a-z]+(?:[&/-][a-z]+)*", re.IGNORECASE)
_PERIOD = re.compile(r"\b(?:19|20)\d{2}\b")
_EXTENDED_PART_TOTAL = re.compile(
    r"(?:percentage|percent)\s+of\s+(?P<total>.+?)\s+that\s+"
    r"(?:was|were|is|are)\s+(?P<part>.+?)(?:\?|$)",
    re.IGNORECASE,
)
_SEMANTIC_HINTS = {
    "total": frozenset({"total", "overall", "aggregate", "net"}),
    "old_value": frozenset(
        {"old", "prior", "previous", "begin", "beginning", "january"}
    ),
    "new_value": frozenset(
        {"new", "current", "end", "ending", "december"}
    ),
    "divisor": frozenset({"divisor", "base"}),
}


def _stem(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
    if token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
        return token[:-1]
    return token


def _financial_tokens(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    result: set[str] = set()
    for raw in _TOKEN.findall(value.casefold()):
        parts = tuple(part for part in re.split(r"[&/-]", raw) if part)
        variants = {raw, "".join(parts), *parts}
        for token in variants:
            normalized = _stem(token)
            if len(normalized) > 1 and normalized not in _STOPWORDS:
                result.add(normalized)
    return frozenset(result)


def _role_anchor_tokens_v2(
    question: str,
    semantic_role: str,
) -> frozenset[str]:
    if semantic_role in {"part", "total"}:
        match = _EXTENDED_PART_TOTAL.search(question)
        if match is not None:
            return _financial_tokens(match.group(semantic_role))
    return frozenset(
        _stem(token)
        for token in _role_anchor_tokens(question, semantic_role)
    )


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


def _score_descriptor_v2(
    *,
    question: str,
    question_tokens: frozenset[str],
    anchor_tokens: frozenset[str],
    semantic_role: str,
    question_periods: frozenset[str],
    descriptor: SafeCandidateDescriptorV1,
) -> tuple[float, tuple[str, ...]]:
    descriptor_tokens = _financial_tokens(_descriptor_text(descriptor))
    overlap = question_tokens & descriptor_tokens
    score = 0.0
    reasons: list[str] = []
    if overlap:
        score += len(overlap) * 6.0
        score += 12.0 * len(overlap) / max(1, len(descriptor_tokens))
        reasons.append("normalized_question_overlap")

    normalized_question = " ".join(question.casefold().split())
    for field in (
        descriptor.metric,
        descriptor.entity,
        descriptor.row_header,
        descriptor.column_header,
    ):
        if field and len(_financial_tokens(field)) >= 2 and field in normalized_question:
            score += 30.0
            reasons.append("exact_field_phrase")
            break

    anchor_overlap = anchor_tokens & descriptor_tokens
    if anchor_overlap:
        score += len(anchor_overlap) * 18.0
        score += 80.0 * len(anchor_overlap) / max(1, len(anchor_tokens))
        reasons.append("extended_role_anchor_overlap")

    semantic_overlap = _SEMANTIC_HINTS.get(
        semantic_role, frozenset()
    ) & descriptor_tokens
    if semantic_overlap:
        score += len(semantic_overlap) * 2.0
        reasons.append("semantic_role_hint_v2")

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


class DeterministicFinQADescriptorRetrieverV2:
    model = "deterministic-host-retriever-v2"

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
            raise ValueError("descriptor retriever v2 question is outside budget")
        started = time.perf_counter()
        question_tokens = _financial_tokens(normalized_question)
        question_periods = frozenset(_PERIOD.findall(normalized_question))
        rankings = []
        selections = []
        for role in skeleton.roles:
            anchor_tokens = _role_anchor_tokens_v2(
                normalized_question, role.semantic_role
            )
            scored = []
            for descriptor in catalog.descriptors:
                score, reasons = _score_descriptor_v2(
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
    "DeterministicFinQADescriptorRetrieverV2",
    "RETRIEVER_VERSION",
]
