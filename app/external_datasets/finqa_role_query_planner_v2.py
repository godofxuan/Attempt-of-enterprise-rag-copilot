from __future__ import annotations

import inspect
import re

from app.external_datasets.finqa_role_compatibility import _tokens
from app.external_datasets.finqa_role_query_planner_v1 import (
    MAX_QUESTION_CHARS,
    _explicit_anchor_tokens,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
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


PLANNER_VERSION = "finqa_question_only_role_query_planner_v2"
_TOKEN = re.compile(r"[a-z][a-z0-9]*", re.IGNORECASE)


def _ordered_query_tokens(question: str) -> tuple[str, ...]:
    result: list[str] = []
    for token in _TOKEN.findall(question.casefold()):
        if token in result or token not in _tokens(token):
            continue
        result.append(token)
    return tuple(result)


def _declared_period(
    period_role: str,
    intent: FinancialQuestionIntentV2,
) -> str | None:
    return {
        "target": intent.target_period,
        "start": intent.start_period,
        "end": intent.end_period,
        "none": None,
    }[period_role]


def _build_query(
    *,
    question: str,
    semantic_role: str,
    expected_period: str | None,
) -> str:
    anchor = _explicit_anchor_tokens(question, semantic_role)
    tokens = list(anchor or _ordered_query_tokens(question))
    if not tokens:
        tokens.extend(semantic_role.replace("_", " ").split())
    if expected_period is not None and expected_period not in tokens:
        tokens.append(expected_period)
    query = " ".join(tokens)
    if len(query) > MAX_ROLE_QUERY_CHARS:
        query = query[:MAX_ROLE_QUERY_CHARS].rsplit(" ", 1)[0]
    return query or semantic_role.replace("_", " ")


def plan_role_queries_from_question_v2(
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
        raise ValueError("role-query planner v2 question is outside budget")
    resolved_intent = intent or extract_financial_question_intent_v2(
        normalized_question
    )
    roles = tuple(
        SemanticRoleSpecV3(
            role_id=role.role_id,
            semantic_role=role.semantic_role,
            period_role=role.period_role,
            role_query=_build_query(
                question=normalized_question,
                semantic_role=role.semantic_role,
                expected_period=_declared_period(
                    role.period_role,
                    resolved_intent,
                ),
            ),
            expected_period=_declared_period(
                role.period_role,
                resolved_intent,
            ),
        )
        for role in skeleton.roles
    )
    return SemanticProgramSkeletonV3(
        roles=roles,
        steps=skeleton.steps,
        output_step_id=skeleton.output_step_id,
    )


def verify_question_only_role_query_planner_v2() -> bool:
    function = plan_role_queries_from_question_v2
    forbidden = ("answer", "candidate", "case_id", "evidence", "gold")
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
    "plan_role_queries_from_question_v2",
    "verify_question_only_role_query_planner_v2",
]
