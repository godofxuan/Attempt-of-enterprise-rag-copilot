from __future__ import annotations

import json
import inspect
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)
from app.external_datasets.finqa_semantic_program_v3 import (
    MAX_ROLE_QUERY_CHARS,
    SemanticProgramSkeletonV3,
    SemanticRoleSpecV3,
)
from app.external_datasets.finqa_typed_planner import (
    parse_typed_planner_payload,
)
from app.ollama_chat import chat_with_ollama


PLANNER_VERSION = "finqa_question_only_role_query_llm_v1"
MAX_QUESTION_CHARS = 2_000
MAX_RESPONSE_CHARS = 8_192
_YEAR = re.compile(r"(?<![a-z0-9])((?:19|20)\d{2})(?![a-z0-9])")

RoleQueryChat = Callable[..., str]


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class PlannedRoleQuery(_StrictModel):
    role_id: str = Field(pattern=r"^role-0[1-8]$")
    role_query: str = Field(min_length=2, max_length=MAX_ROLE_QUERY_CHARS)
    expected_period: str | None = Field(default=None, max_length=128)


class PlannedRoleQueries(_StrictModel):
    roles: tuple[PlannedRoleQuery, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_unique_roles(self) -> PlannedRoleQueries:
        role_ids = tuple(item.role_id for item in self.roles)
        if len(role_ids) != len(set(role_ids)):
            raise ValueError("LLM role-query plan contains duplicate roles")
        return self


@dataclass(frozen=True)
class LLMRoleQueryPlannerResult:
    planner_version: str
    model: str
    skeleton: SemanticProgramSkeletonV3
    generation_calls: int
    latency_ms: float


def _explicit_periods(question: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_YEAR.findall(question)))


def role_query_response_format(
    skeleton: SemanticProgramSkeletonV2,
    *,
    explicit_periods: tuple[str, ...],
) -> dict[str, object]:
    role_ids = [role.role_id for role in skeleton.roles]
    role_schema = {
        "type": "object",
        "properties": {
            "role_id": {
                "type": "string",
                "enum": role_ids,
            },
            "role_query": {
                "type": "string",
                "minLength": 2,
                "maxLength": MAX_ROLE_QUERY_CHARS,
            },
            "expected_period": {
                "anyOf": [
                    {
                        "type": "string",
                        "enum": list(explicit_periods),
                    },
                    {"type": "null"},
                ]
            },
        },
        "required": [
            "role_id",
            "role_query",
            "expected_period",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "roles": {
                "type": "array",
                "minItems": len(role_ids),
                "maxItems": len(role_ids),
                "items": role_schema,
            }
        },
        "required": ["roles"],
        "additionalProperties": False,
    }


def build_role_query_messages(
    *,
    question: str,
    skeleton: SemanticProgramSkeletonV2,
) -> list[dict[str, str]]:
    role_payload = [
        {
            "role_id": role.role_id,
            "semantic_role": role.semantic_role,
            "period_role": role.period_role,
        }
        for role in skeleton.roles
    ]
    step_payload = [
        {
            "step_id": step.step_id,
            "operation": step.operation,
            "arguments": [
                (
                    {"role_id": argument.role_id}
                    if hasattr(argument, "role_id")
                    else (
                        {"step_id": argument.step_id}
                        if hasattr(argument, "step_id")
                        else {"constant": True}
                    )
                )
                for argument in step.arguments
            ],
        }
        for step in skeleton.steps
    ]
    system = (
        "You produce short evidence-search queries for typed financial operand "
        "roles. Use only the user question and the provided value-free role and "
        "operation structure. Never request or emit candidate IDs, evidence IDs, "
        "step IDs inside role_query, numeric answer values, formulas, code, or "
        "instructions. role_query should name the exact metric, entity, qualifier, "
        "and role-specific meaning needed to find that operand. Distinguish part "
        "from total, new from old, and separate entities in comparisons. "
        "expected_period must be one period written explicitly in the question, "
        "or null when the role cannot be mapped confidently. Do not treat possessive "
        "OCR text such as company 2019s as a year. Return only the required JSON."
    )
    user = json.dumps(
        {
            "question": question,
            "roles": role_payload,
            "operations": step_payload,
            "explicit_periods": list(_explicit_periods(question)),
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_role_query_response(
    raw: str,
    *,
    skeleton: SemanticProgramSkeletonV2,
    explicit_periods: tuple[str, ...],
) -> PlannedRoleQueries:
    if len(raw) > MAX_RESPONSE_CHARS:
        raise ValueError("LLM role-query response exceeds budget")
    payload = parse_typed_planner_payload(raw)
    plan = PlannedRoleQueries.model_validate(payload)
    expected_role_ids = tuple(role.role_id for role in skeleton.roles)
    if tuple(item.role_id for item in plan.roles) != expected_role_ids:
        raise ValueError("LLM role-query response does not preserve role order")
    allowed_periods = set(explicit_periods)
    if any(
        item.expected_period is not None
        and item.expected_period not in allowed_periods
        for item in plan.roles
    ):
        raise ValueError("LLM role-query response invented a period")
    return plan


class LocalFinQARoleQueryPlannerV1:
    def __init__(
        self,
        *,
        model: str,
        chat_fn: RoleQueryChat = chat_with_ollama,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not model.strip() or len(model.strip()) > 200:
            raise ValueError("LLM role-query model is invalid")
        if not 1 <= timeout_seconds <= 300:
            raise ValueError("LLM role-query timeout is invalid")
        self.model = model.strip()
        self.chat_fn = chat_fn
        self.timeout_seconds = timeout_seconds

    def plan(
        self,
        *,
        question: str,
        skeleton: SemanticProgramSkeletonV2,
    ) -> LLMRoleQueryPlannerResult:
        normalized_question = " ".join(question.split())
        if (
            not normalized_question
            or len(normalized_question) > MAX_QUESTION_CHARS
        ):
            raise ValueError("LLM role-query question is outside budget")
        periods = _explicit_periods(normalized_question)
        messages = build_role_query_messages(
            question=normalized_question,
            skeleton=skeleton,
        )
        response_format = role_query_response_format(
            skeleton,
            explicit_periods=periods,
        )
        started = time.perf_counter()
        raw = self.chat_fn(
            self.model,
            messages,
            response_format=response_format,
            think=False,
            timeout_seconds=self.timeout_seconds,
        )
        latency_ms = (time.perf_counter() - started) * 1_000
        plan = parse_role_query_response(
            raw,
            skeleton=skeleton,
            explicit_periods=periods,
        )
        role_by_id = {role.role_id: role for role in skeleton.roles}
        planned_roles = tuple(
            SemanticRoleSpecV3(
                role_id=item.role_id,
                semantic_role=role_by_id[item.role_id].semantic_role,
                period_role=role_by_id[item.role_id].period_role,
                role_query=item.role_query,
                expected_period=item.expected_period,
            )
            for item in plan.roles
        )
        return LLMRoleQueryPlannerResult(
            planner_version=PLANNER_VERSION,
            model=self.model,
            skeleton=SemanticProgramSkeletonV3(
                roles=planned_roles,
                steps=skeleton.steps,
                output_step_id=skeleton.output_step_id,
            ),
            generation_calls=1,
            latency_ms=latency_ms,
        )


def verify_question_only_llm_role_query_planner() -> bool:
    functions = (
        build_role_query_messages,
        LocalFinQARoleQueryPlannerV1.plan,
    )
    forbidden = ("answer", "candidate=", "case_id", "evidence=", "gold")
    for function in functions:
        parameters = inspect.signature(function).parameters
        source = inspect.getsource(function).casefold()
        if any(
            token.rstrip("=") in parameter.casefold()
            for parameter in parameters
            for token in forbidden
        ) or any(token in source for token in forbidden if token.endswith("=")):
            return False
    return True


__all__ = [
    "LLMRoleQueryPlannerResult",
    "LocalFinQARoleQueryPlannerV1",
    "PLANNER_VERSION",
    "PlannedRoleQueries",
    "PlannedRoleQuery",
    "build_role_query_messages",
    "parse_role_query_response",
    "role_query_response_format",
    "verify_question_only_llm_role_query_planner",
]
