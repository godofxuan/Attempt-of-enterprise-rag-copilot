from __future__ import annotations

import hashlib
import inspect
import json
import re
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa_numeric_evidence_v2 import NumericCandidateV2
from app.external_datasets.finqa_role_compatibility import (
    _candidate_period,
    _candidate_score,
    _expected_period,
    _role_anchor_tokens,
    _tokens,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
    SemanticRoleBindingsV2,
    SemanticRoleRefV2,
    SemanticRoleSpecV2,
)
from app.external_datasets.finqa_typed_planner import (
    parse_typed_planner_payload,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    FinancialQuestionIntentV2,
)
from app.external_datasets.finqa_typed_program import StepRef


COMPATIBILITY_VERSION = "finqa_role_candidate_compatibility_v2"
MAX_SOURCE_CANDIDATES = 128
MAX_ROLE_CANDIDATES = 8
MAX_UNIQUE_EXPOSED_CANDIDATES = 32
MAX_EVIDENCE_UNITS = 32
MAX_RESPONSE_CHARS = 8_192
CapabilityRoute = Literal[
    "TYPED_NUMERIC",
    "B0_BOOLEAN_COMPARISON_FALLBACK",
    "B0_SYMBOLIC_TABLE_AGGREGATION_FALLBACK",
]
_BOOLEAN_COMPARISON = re.compile(
    r"\b(?:did|does|do)\b.{0,300}\b"
    r"(?:outperform|exceed|greater\s+than|less\s+than)\b",
    re.IGNORECASE,
)
_SYMBOLIC_TABLE_AGGREGATION = re.compile(
    r"\bwhat\s+(?:is|was)\s+the\s+average\b.{0,200}\b"
    r"(?:expected\s+life|contractual\s+life|exercise\s+price)\b",
    re.IGNORECASE,
)
_DIRECT_YEAR_COMPARISON = re.compile(
    r"\b(?P<new>(?:19|20)\d{2})\b.{0,40}\b"
    r"(?:compared?\s+to|versus|vs\.?)\s+"
    r"(?P<old>(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_FROM_TO_YEAR_COMPARISON = re.compile(
    r"\bfrom\s+(?P<old>(?:19|20)\d{2})\s+to\s+"
    r"(?P<new>(?:19|20)\d{2})\b",
    re.IGNORECASE,
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class RoleCandidateRankV2(_StrictFrozenModel):
    candidate_id: str = Field(pattern=r"^num-[0-9a-f]{20}$")
    score: float
    score_reasons: tuple[str, ...]


class RoleCandidateAllowlistV2(_StrictFrozenModel):
    role_id: str = Field(pattern=r"^role-0[1-8]$")
    semantic_role: str = Field(min_length=1, max_length=64)
    period_role: Literal["target", "start", "end", "none"]
    expected_period: str | None = Field(default=None, max_length=128)
    hard_compatible_candidate_count: int = Field(
        ge=1,
        le=MAX_SOURCE_CANDIDATES,
    )
    ranked_candidates: tuple[RoleCandidateRankV2, ...] = Field(
        min_length=1,
        max_length=MAX_ROLE_CANDIDATES,
    )

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(item.candidate_id for item in self.ranked_candidates)


class RoleCandidateCompatibilityMatrixV2(_StrictFrozenModel):
    compatibility_version: Literal[
        "finqa_role_candidate_compatibility_v2"
    ] = COMPATIBILITY_VERSION
    source_candidate_count: int = Field(ge=1, le=MAX_SOURCE_CANDIDATES)
    role_count: int = Field(ge=1, le=8)
    unique_exposed_candidate_count: int = Field(
        ge=1,
        le=MAX_UNIQUE_EXPOSED_CANDIDATES,
    )
    role_allowlists: tuple[RoleCandidateAllowlistV2, ...] = Field(
        min_length=1,
        max_length=8,
    )
    matrix_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_matrix(self) -> RoleCandidateCompatibilityMatrixV2:
        role_ids = tuple(item.role_id for item in self.role_allowlists)
        if (
            len(role_ids) != self.role_count
            or len(role_ids) != len(set(role_ids))
        ):
            raise ValueError("role compatibility v2 role count is invalid")
        exposed = {
            candidate_id
            for allowlist in self.role_allowlists
            for candidate_id in allowlist.candidate_ids
        }
        if len(exposed) != self.unique_exposed_candidate_count:
            raise ValueError("role compatibility v2 exposure count is invalid")
        for allowlist in self.role_allowlists:
            if len(allowlist.candidate_ids) != len(
                set(allowlist.candidate_ids)
            ):
                raise ValueError("role compatibility v2 allowlist is duplicated")
        payload = {
            "compatibility_version": self.compatibility_version,
            "source_candidate_count": self.source_candidate_count,
            "role_count": self.role_count,
            "unique_exposed_candidate_count": (
                self.unique_exposed_candidate_count
            ),
            "role_allowlists": [
                item.model_dump(mode="json")
                for item in self.role_allowlists
            ],
        }
        expected = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
        if self.matrix_sha256 != expected:
            raise ValueError("role compatibility v2 matrix hash is invalid")
        return self

    def candidate_ids_for_role(self, role_id: str) -> tuple[str, ...]:
        for allowlist in self.role_allowlists:
            if allowlist.role_id == role_id:
                return allowlist.candidate_ids
        raise ValueError("role is absent from compatibility v2 matrix")

    def allowed_candidate_ids_by_role(self) -> dict[str, tuple[str, ...]]:
        return {
            item.role_id: item.candidate_ids
            for item in self.role_allowlists
        }


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def route_finqa_numeric_capability(question: str) -> CapabilityRoute:
    question = question.strip()
    if not question or len(question) > 2_000:
        raise ValueError("capability route question is outside budget")
    if _BOOLEAN_COMPARISON.search(question):
        return "B0_BOOLEAN_COMPARISON_FALLBACK"
    if _SYMBOLIC_TABLE_AGGREGATION.search(question):
        return "B0_SYMBOLIC_TABLE_AGGREGATION_FALLBACK"
    return "TYPED_NUMERIC"


def verify_no_gold_runtime_inputs_v2() -> bool:
    functions = (
        route_finqa_numeric_capability,
        build_role_candidate_compatibility_matrix_v2,
    )
    forbidden = ("gold", "answer", "case_id", "gold_evidence")
    for function in functions:
        parameters = inspect.signature(function).parameters
        source = inspect.getsource(function).casefold()
        if any(
            token in parameter.casefold()
            for parameter in parameters
            for token in forbidden
        ) or any(f"{token}=" in source for token in forbidden):
            return False
    return True


def _denominator_role_ids(
    skeleton: SemanticProgramSkeletonV2,
) -> set[str]:
    result: set[str] = set()
    for step in skeleton.steps:
        if step.operation not in {"DIV", "RATIO", "PERCENT_CHANGE"}:
            continue
        denominator = step.arguments[1]
        if isinstance(denominator, SemanticRoleRefV2):
            result.add(denominator.role_id)
    return result


def validate_semantic_skeleton_compatibility_v2(
    *,
    skeleton: SemanticProgramSkeletonV2,
    intent: FinancialQuestionIntentV2,
) -> None:
    for role in skeleton.roles:
        if role.semantic_role == "new_value" and role.period_role == "start":
            raise ValueError("new_value role cannot use start period")
        if role.semantic_role == "old_value" and role.period_role == "end":
            raise ValueError("old_value role cannot use end period")
        if (
            role.semantic_role
            in {"part", "total", "component", "factor", "divisor"}
            and role.period_role in {"start", "end"}
        ):
            raise ValueError("non-temporal role has temporal period role")
    if intent.operation_family == "percent_change":
        by_id = {item.role_id: item for item in skeleton.roles}
        for step in skeleton.steps:
            if step.operation not in {"SUB", "PERCENT_CHANGE"}:
                continue
            first, second = step.arguments
            if (
                isinstance(first, SemanticRoleRefV2)
                and isinstance(second, SemanticRoleRefV2)
                and by_id[first.role_id].semantic_role == "old_value"
                and by_id[second.role_id].semantic_role == "new_value"
            ):
                raise ValueError("percent-change roles are reversed")


def _expected_period_v2(
    *,
    question: str,
    role: SemanticRoleSpecV2,
    intent: FinancialQuestionIntentV2,
) -> str | None:
    match = _FROM_TO_YEAR_COMPARISON.search(question)
    if match is None:
        match = _DIRECT_YEAR_COMPARISON.search(question)
    if match is not None:
        if role.period_role == "start":
            return match.group("old")
        if role.period_role == "end":
            return match.group("new")
    return _expected_period(role, intent)


def hard_compatible_candidates_for_role_v2(
    *,
    role: SemanticRoleSpecV2,
    skeleton: SemanticProgramSkeletonV2,
    candidates: Sequence[NumericCandidateV2],
    intent: FinancialQuestionIntentV2,
    question: str | None = None,
) -> tuple[NumericCandidateV2, ...]:
    expected_period = (
        _expected_period_v2(
            question=question,
            role=role,
            intent=intent,
        )
        if question is not None
        else _expected_period(role, intent)
    )
    denominator_roles = _denominator_role_ids(skeleton)
    return tuple(
        candidate
        for candidate in candidates
        if not (
            expected_period is not None
            and (period := _candidate_period(candidate)) is not None
            and period != expected_period
        )
        and not (
            role.role_id in denominator_roles
            and candidate.normalized_value == 0
        )
    )


def build_role_candidate_compatibility_matrix_v2(
    *,
    question: str,
    skeleton: SemanticProgramSkeletonV2,
    candidates: Sequence[NumericCandidateV2],
    admitted_evidence_ids: set[str],
    intent: FinancialQuestionIntentV2,
    evidence_context_by_id: Mapping[str, str],
) -> RoleCandidateCompatibilityMatrixV2:
    question = question.strip()
    if (
        not question
        or len(question) > 2_000
        or not candidates
        or len(candidates) > MAX_SOURCE_CANDIDATES
    ):
        raise ValueError("role compatibility v2 input budget is invalid")
    if len(admitted_evidence_ids) > MAX_EVIDENCE_UNITS:
        raise ValueError("role compatibility v2 evidence budget is invalid")
    if set(evidence_context_by_id) - admitted_evidence_ids:
        raise ValueError("role compatibility v2 context is not admitted")
    candidate_ids = [item.candidate_id for item in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("role compatibility v2 candidate IDs are duplicated")
    usable = tuple(
        item
        for item in candidates
        if item.role == "operand"
        and item.evidence_id in admitted_evidence_ids
    )
    if len(usable) != len(candidates):
        raise ValueError(
            "role compatibility v2 contains non-admitted candidate"
        )
    validate_semantic_skeleton_compatibility_v2(
        skeleton=skeleton,
        intent=intent,
    )
    question_tokens = _tokens(question)
    evidence_rank = {
        evidence_id: index
        for index, evidence_id in enumerate(evidence_context_by_id)
    }
    allowlists: list[RoleCandidateAllowlistV2] = []
    for role in skeleton.roles:
        expected_period = _expected_period_v2(
            question=question,
            role=role,
            intent=intent,
        )
        anchor_tokens = _role_anchor_tokens(question, role.semantic_role)
        hard = hard_compatible_candidates_for_role_v2(
            role=role,
            skeleton=skeleton,
            candidates=usable,
            intent=intent,
            question=question,
        )
        if not hard:
            raise ValueError(
                f"role compatibility v2 has empty allowlist for {role.role_id}"
            )
        scored: list[tuple[float, str, NumericCandidateV2, tuple[str, ...]]] = []
        for candidate in hard:
            score, reasons = _candidate_score(
                question_tokens=question_tokens,
                anchor_tokens=anchor_tokens,
                candidate=candidate,
                expected_period=expected_period,
                evidence_context=evidence_context_by_id.get(
                    candidate.evidence_id
                ),
                evidence_rank=evidence_rank.get(
                    candidate.evidence_id,
                    len(evidence_rank),
                ),
            )
            scored.append((score, candidate.candidate_id, candidate, reasons))
        scored.sort(key=lambda item: (-item[0], item[1]))
        allowlists.append(
            RoleCandidateAllowlistV2(
                role_id=role.role_id,
                semantic_role=role.semantic_role,
                period_role=role.period_role,
                expected_period=expected_period,
                hard_compatible_candidate_count=len(hard),
                ranked_candidates=tuple(
                    RoleCandidateRankV2(
                        candidate_id=item[2].candidate_id,
                        score=item[0],
                        score_reasons=item[3],
                    )
                    for item in scored[:MAX_ROLE_CANDIDATES]
                ),
            )
        )
    unique_exposed = {
        candidate_id
        for allowlist in allowlists
        for candidate_id in allowlist.candidate_ids
    }
    if len(unique_exposed) > MAX_UNIQUE_EXPOSED_CANDIDATES:
        raise ValueError("role compatibility v2 exposure budget exceeded")
    payload = {
        "compatibility_version": COMPATIBILITY_VERSION,
        "source_candidate_count": len(candidates),
        "role_count": len(skeleton.roles),
        "unique_exposed_candidate_count": len(unique_exposed),
        "role_allowlists": [
            item.model_dump(mode="json") for item in allowlists
        ],
    }
    return RoleCandidateCompatibilityMatrixV2(
        **payload,
        matrix_sha256=hashlib.sha256(_canonical_json_bytes(payload)).hexdigest(),
    )


def role_binding_response_format_by_role_v2(
    matrix: RoleCandidateCompatibilityMatrixV2,
) -> dict[str, object]:
    alternatives = [
        {
            "type": "object",
            "properties": {
                "role_id": {
                    "type": "string",
                    "enum": [allowlist.role_id],
                },
                "candidate_id": {
                    "type": "string",
                    "enum": list(allowlist.candidate_ids),
                },
            },
            "required": ["role_id", "candidate_id"],
            "additionalProperties": False,
        }
        for allowlist in matrix.role_allowlists
    ]
    return {
        "type": "object",
        "properties": {
            "bindings": {
                "type": "array",
                "minItems": matrix.role_count,
                "maxItems": matrix.role_count,
                "items": {"anyOf": alternatives},
            }
        },
        "required": ["bindings"],
        "additionalProperties": False,
    }


def parse_role_bindings_by_role_v2(
    raw: str,
    *,
    matrix: RoleCandidateCompatibilityMatrixV2,
) -> SemanticRoleBindingsV2:
    if len(raw) > MAX_RESPONSE_CHARS:
        raise ValueError("role binding v2 response exceeds budget")
    payload = parse_typed_planner_payload(raw)
    try:
        bindings = SemanticRoleBindingsV2.model_validate(payload)
    except ValueError as exc:
        raise ValueError("role binding v2 schema is invalid") from exc
    expected = {
        allowlist.role_id: set(allowlist.candidate_ids)
        for allowlist in matrix.role_allowlists
    }
    actual = {item.role_id: item.candidate_id for item in bindings.bindings}
    if set(actual) != set(expected):
        raise ValueError("role bindings v2 do not cover exact role set")
    if any(
        actual[role_id] not in candidates
        for role_id, candidates in expected.items()
    ):
        raise ValueError("role binding v2 violates role-specific allowlist")
    return bindings


def verify_role_exact_parser_enforcement_v2() -> bool:
    allowlists = (
        RoleCandidateAllowlistV2(
            role_id="role-01",
            semantic_role="new_value",
            period_role="end",
            expected_period="2020",
            hard_compatible_candidate_count=1,
            ranked_candidates=(
                RoleCandidateRankV2(
                    candidate_id=f"num-{'a' * 20}",
                    score=1.0,
                    score_reasons=("synthetic_contract",),
                ),
            ),
        ),
        RoleCandidateAllowlistV2(
            role_id="role-02",
            semantic_role="old_value",
            period_role="start",
            expected_period="2019",
            hard_compatible_candidate_count=1,
            ranked_candidates=(
                RoleCandidateRankV2(
                    candidate_id=f"num-{'b' * 20}",
                    score=1.0,
                    score_reasons=("synthetic_contract",),
                ),
            ),
        ),
    )
    payload = {
        "compatibility_version": COMPATIBILITY_VERSION,
        "source_candidate_count": 2,
        "role_count": 2,
        "unique_exposed_candidate_count": 2,
        "role_allowlists": [
            item.model_dump(mode="json") for item in allowlists
        ],
    }
    matrix = RoleCandidateCompatibilityMatrixV2(
        **payload,
        matrix_sha256=hashlib.sha256(_canonical_json_bytes(payload)).hexdigest(),
    )
    invalid = json.dumps(
        {
            "bindings": [
                {
                    "role_id": "role-01",
                    "candidate_id": f"num-{'b' * 20}",
                },
                {
                    "role_id": "role-02",
                    "candidate_id": f"num-{'b' * 20}",
                },
            ]
        },
        separators=(",", ":"),
    )
    try:
        parse_role_bindings_by_role_v2(invalid, matrix=matrix)
    except ValueError:
        return True
    return False


__all__ = [
    "COMPATIBILITY_VERSION",
    "CapabilityRoute",
    "MAX_ROLE_CANDIDATES",
    "MAX_SOURCE_CANDIDATES",
    "MAX_UNIQUE_EXPOSED_CANDIDATES",
    "RoleCandidateAllowlistV2",
    "RoleCandidateCompatibilityMatrixV2",
    "RoleCandidateRankV2",
    "build_role_candidate_compatibility_matrix_v2",
    "hard_compatible_candidates_for_role_v2",
    "parse_role_bindings_by_role_v2",
    "role_binding_response_format_by_role_v2",
    "route_finqa_numeric_capability",
    "validate_semantic_skeleton_compatibility_v2",
    "verify_no_gold_runtime_inputs_v2",
    "verify_role_exact_parser_enforcement_v2",
]
