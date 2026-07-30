from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal

from app.external_datasets.finqa_typed_contract_v2 import (
    FinancialQuestionIntentV2,
)
from app.external_datasets.finqa_typed_program import NumericCandidate


SHORTLIST_VERSION = "finqa_numeric_evidence_shortlist_v2"
MAX_INPUT_CANDIDATES = 128
MAX_OUTPUT_CANDIDATES = 24
MAX_EVIDENCE_UNITS = 32
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "did",
    "do",
    "for",
    "from",
    "how",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "were",
    "what",
    "which",
    "with",
}
_COMMON_EVIDENCE_SCALARS = {
    Decimal("1"),
    Decimal("100"),
    Decimal("1000"),
    Decimal("10000"),
}


def _tokens(value: str | None) -> set[str]:
    if value is None:
        return set()
    return {
        token
        for token in _TOKEN_PATTERN.findall(value.casefold())
        if token not in _STOPWORDS and len(token) > 1
    }


def _candidate_period(candidate: NumericCandidate) -> str | None:
    if candidate.period is not None:
        return candidate.period.casefold().strip()
    if candidate.fiscal_year is not None:
        return str(candidate.fiscal_year)
    return None


def question_conditioned_numeric_evidence_shortlist_v2(
    *,
    question: str,
    candidates: Sequence[NumericCandidate],
    admitted_evidence_ids: set[str],
    intent: FinancialQuestionIntentV2,
    evidence_context_by_id: Mapping[str, str] | None = None,
) -> tuple[NumericCandidate, ...]:
    if len(candidates) > MAX_INPUT_CANDIDATES:
        raise ValueError("numeric evidence candidate budget exceeded")
    if len(admitted_evidence_ids) > MAX_EVIDENCE_UNITS:
        raise ValueError("numeric evidence unit budget exceeded")
    candidate_ids = [candidate.candidate_id for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("numeric evidence candidate IDs must be unique")
    usable = tuple(
        candidate
        for candidate in candidates
        if candidate.role == "operand"
        and candidate.evidence_id in admitted_evidence_ids
    )
    if not usable:
        raise ValueError("numeric evidence shortlist has no operand candidate")

    question_tokens = _tokens(question)
    evidence_context = evidence_context_by_id or {}
    if set(evidence_context) - admitted_evidence_ids:
        raise ValueError("shortlist context contains non-admitted evidence")
    evidence_rank = {
        evidence_id: index
        for index, evidence_id in enumerate(evidence_context)
    }
    allowed_periods: set[str] | None = None
    if intent.target_period is not None:
        allowed_periods = {intent.target_period.casefold().strip()}
    elif intent.start_period is not None and intent.end_period is not None:
        allowed_periods = {
            intent.start_period.casefold().strip(),
            intent.end_period.casefold().strip(),
        }

    scored: list[tuple[float, int, int, NumericCandidate]] = []
    for source_index, candidate in enumerate(usable):
        period = _candidate_period(candidate)
        if (
            allowed_periods is not None
            and period is not None
            and period not in allowed_periods
        ):
            continue
        metric_tokens = _tokens(candidate.metric or candidate.row_header)
        context_tokens = _tokens(evidence_context.get(candidate.evidence_id))
        metric_overlap = len(question_tokens.intersection(metric_tokens))
        context_overlap = len(question_tokens.intersection(context_tokens))
        score = 0.0
        if metric_tokens:
            score += 12.0 * metric_overlap / len(metric_tokens)
        score += min(context_overlap, 8) * 1.5
        if allowed_periods is not None:
            score += 8.0 if period in allowed_periods else 1.0
        if candidate.source_kind == "table_cell":
            score += 2.0
        if (
            candidate.normalized_value.copy_abs()
            in _COMMON_EVIDENCE_SCALARS
            and candidate.unit in {"unknown", "ratio"}
        ):
            score += 2.0
        rank = evidence_rank.get(candidate.evidence_id, len(evidence_rank))
        score += max(0, 5 - rank) * 0.5
        scored.append((score, rank, source_index, candidate))
    if not scored:
        raise ValueError("numeric evidence shortlist has no compatible candidate")
    scored.sort(
        key=lambda item: (
            -item[0],
            item[1],
            item[2],
            item[3].candidate_id,
        )
    )
    return tuple(item[3] for item in scored[:MAX_OUTPUT_CANDIDATES])


__all__ = [
    "MAX_EVIDENCE_UNITS",
    "MAX_INPUT_CANDIDATES",
    "MAX_OUTPUT_CANDIDATES",
    "SHORTLIST_VERSION",
    "question_conditioned_numeric_evidence_shortlist_v2",
]
