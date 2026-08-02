from __future__ import annotations

import inspect
import re

from app.external_datasets.finqa_role_compatibility import (
    _role_anchor_tokens,
    _tokens,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
    SemanticRoleSpecV2,
)
from app.external_datasets.finqa_semantic_program_v3 import (
    MAX_ROLE_QUERY_CHARS,
    SemanticProgramSkeletonV3,
    SemanticRoleSpecV3,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    FinancialQuestionIntentV2,
    extract_financial_question_intent_v2,
)


PLANNER_VERSION = "finqa_question_only_role_query_planner_v1"
MAX_QUESTION_CHARS = 2_000

_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_FROM_TO = re.compile(
    r"\bfrom\s+(?P<start>(?:19|20)\d{2})\s+to\s+"
    r"(?P<end>(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_BETWEEN = re.compile(
    r"\bbetween\s+(?P<start>(?:19|20)\d{2})\s+and\s+"
    r"(?P<end>(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_YEAR_RANGE = re.compile(
    r"\b(?P<start>(?:19|20)\d{2})\s*-\s*"
    r"(?P<end>(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_CONSIDERING_YEARS = re.compile(
    r"\byears?\s+(?P<start>(?:19|20)\d{2})\s+and\s+"
    r"(?P<end>(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_PORTION = re.compile(
    r"what\s+(?:portion|percentage|percent)\s+of\s+"
    r"(?P<total>.+?)\s+(?:was|were|is|are)\s+"
    r"(?P<part>.+?)(?:\?|$)",
    re.IGNORECASE,
)
_PERCENT_TO = re.compile(
    r"(?:percentage|percent)\s+of\s+(?P<part>.+?)\s+to\s+"
    r"(?P<total>.+?)(?:\?|$)",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"[a-z][a-z0-9]*", re.IGNORECASE)
_QUERY_NOISE = {
    "amount",
    "annual",
    "average",
    "change",
    "compare",
    "compared",
    "considering",
    "decrease",
    "difference",
    "growth",
    "increase",
    "million",
    "millions",
    "percentage",
    "percent",
    "ratio",
    "rate",
    "sum",
    "total",
    "variation",
    "year",
    "years",
}


def _ordered_subject_tokens(question: str) -> tuple[str, ...]:
    result: list[str] = []
    for token in _TOKEN.findall(question.casefold()):
        if (
            token in _QUERY_NOISE
            or token.isdigit()
            or token in result
            or token not in _tokens(token)
        ):
            continue
        result.append(token)
    return tuple(result)


def _period_pair(question: str) -> tuple[str, str, str] | None:
    for label, pattern in (
        ("from_to", _FROM_TO),
        ("between", _BETWEEN),
        ("range", _YEAR_RANGE),
        ("considering", _CONSIDERING_YEARS),
    ):
        match = pattern.search(question)
        if match is not None:
            return match.group("start"), match.group("end"), label
    years = tuple(dict.fromkeys(_YEAR.findall(question)))
    if len(years) == 2:
        return years[0], years[1], "two_years"
    return None


def _explicit_anchor_tokens(
    question: str,
    semantic_role: str,
) -> tuple[str, ...]:
    if semantic_role not in {"part", "total"}:
        return ()
    group = semantic_role
    for pattern in (_PORTION, _PERCENT_TO):
        match = pattern.search(question)
        if match is not None:
            return tuple(sorted(_tokens(match.group(group))))
    return tuple(sorted(_role_anchor_tokens(question, semantic_role)))


def _expected_period(
    *,
    question: str,
    role: SemanticRoleSpecV2,
    role_index: int,
    same_role_count: int,
    intent: FinancialQuestionIntentV2,
) -> str | None:
    pair = _period_pair(question)
    if role.period_role == "start":
        return intent.start_period or (pair[0] if pair else None)
    if role.period_role == "end":
        return intent.end_period or (pair[1] if pair else None)
    if (
        pair is not None
        and role.semantic_role
        in {"comparison_left", "comparison_right"}
    ):
        start, end, relation = pair
        if relation == "between":
            return (
                start
                if role.semantic_role == "comparison_left"
                else end
            )
        return (
            end
            if role.semantic_role == "comparison_left"
            else start
        )
    years = tuple(dict.fromkeys(_YEAR.findall(question)))
    if same_role_count > 1 and len(years) == same_role_count:
        return years[role_index]
    if len(years) == 1:
        return years[0]
    return intent.target_period


def _role_query(
    *,
    question: str,
    role: SemanticRoleSpecV2,
    expected_period: str | None,
) -> str:
    anchor = _explicit_anchor_tokens(question, role.semantic_role)
    subject = _ordered_subject_tokens(question)
    tokens = list(anchor or subject)
    role_label = role.semantic_role.replace("_", " ")
    if not tokens:
        tokens.extend(role_label.split())
    if expected_period is not None and expected_period not in tokens:
        tokens.append(expected_period)
    query = " ".join(tokens)
    if len(query) > MAX_ROLE_QUERY_CHARS:
        query = query[:MAX_ROLE_QUERY_CHARS].rsplit(" ", 1)[0]
    return query or role_label


def plan_role_queries_from_question(
    *,
    question: str,
    skeleton: SemanticProgramSkeletonV2,
    intent: FinancialQuestionIntentV2 | None = None,
) -> SemanticProgramSkeletonV3:
    normalized_question = " ".join(question.split())
    if (
        not normalized_question
        or len(normalized_question) > MAX_QUESTION_CHARS
    ):
        raise ValueError("role-query planner question is outside budget")
    resolved_intent = intent or extract_financial_question_intent_v2(
        normalized_question
    )
    counts: dict[str, int] = {}
    for role in skeleton.roles:
        counts[role.semantic_role] = counts.get(role.semantic_role, 0) + 1
    offsets: dict[str, int] = {}
    planned_roles = []
    for role in skeleton.roles:
        role_index = offsets.get(role.semantic_role, 0)
        offsets[role.semantic_role] = role_index + 1
        period = _expected_period(
            question=normalized_question,
            role=role,
            role_index=role_index,
            same_role_count=counts[role.semantic_role],
            intent=resolved_intent,
        )
        planned_roles.append(
            SemanticRoleSpecV3(
                role_id=role.role_id,
                semantic_role=role.semantic_role,
                period_role=role.period_role,
                role_query=_role_query(
                    question=normalized_question,
                    role=role,
                    expected_period=period,
                ),
                expected_period=period,
            )
        )
    return SemanticProgramSkeletonV3(
        roles=tuple(planned_roles),
        steps=skeleton.steps,
        output_step_id=skeleton.output_step_id,
    )


def verify_question_only_role_query_planner() -> bool:
    function = plan_role_queries_from_question
    forbidden = (
        "answer",
        "candidate",
        "case_id",
        "evidence",
        "gold",
    )
    parameters = inspect.signature(function).parameters
    source = inspect.getsource(function).casefold()
    return not (
        any(
            token in parameter.casefold()
            for parameter in parameters
            for token in forbidden
        )
        or any(f"{token}=" in source for token in forbidden)
    )


__all__ = [
    "PLANNER_VERSION",
    "plan_role_queries_from_question",
    "verify_question_only_role_query_planner",
]
