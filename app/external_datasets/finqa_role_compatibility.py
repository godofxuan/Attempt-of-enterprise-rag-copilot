from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa_numeric_evidence_v2 import NumericCandidateV2
from app.external_datasets.finqa_semantic_program import (
    SemanticProgramSkeleton,
    SemanticRoleBindings,
    SemanticRoleName,
    SemanticRoleSpec,
    SemanticRoleRef,
)
from app.external_datasets.finqa_typed_planner import (
    parse_typed_planner_payload,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    FinancialQuestionIntentV2,
)
from app.external_datasets.finqa_typed_program import StepRef


COMPATIBILITY_VERSION = "finqa_role_candidate_compatibility_v1"
MAX_GLOBAL_CANDIDATES = 24
MAX_ROLE_CANDIDATES = 8
MAX_EVIDENCE_UNITS = 32
MAX_RESPONSE_CHARS = 8_192
_TOKEN = re.compile(r"[a-z][a-z0-9]*", re.IGNORECASE)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "between",
    "by",
    "did",
    "do",
    "does",
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
_PART_TOTAL_PATTERNS = (
    re.compile(
        r"what\s+(?:percentage|percent)\s+of\s+(?P<total>.+?)\s+"
        r"(?:was|were|is|are)\s+(?P<part>.+?)(?:\?|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<part>.+?)\s+as\s+(?:a\s+)?(?:percentage|percent)\s+of\s+"
        r"(?P<total>.+?)(?:\?|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:ratio\s+of)\s+(?P<part>.+?)\s+to\s+"
        r"(?P<total>.+?)(?:\?|$)",
        re.IGNORECASE,
    ),
)
_COMPARISON_PATTERNS = (
    re.compile(
        r"difference\s+between\s+(?P<left>.+?)\s+and\s+"
        r"(?P<right>.+?)(?:\?|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"how\s+much\s+(?:more|less)\s+(?:was|were|is|are)\s+"
        r"(?P<left>.+?)\s+than\s+(?P<right>.+?)(?:\?|$)",
        re.IGNORECASE,
    ),
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class RoleCandidateRank(_StrictFrozenModel):
    candidate_id: str = Field(pattern=r"^num-[0-9a-f]{20}$")
    score: float
    score_reasons: tuple[str, ...]


class RoleCandidateAllowlist(_StrictFrozenModel):
    role_id: str = Field(pattern=r"^role-0[1-6]$")
    semantic_role: SemanticRoleName
    period_role: Literal["target", "start", "end", "none"]
    expected_period: str | None = Field(default=None, max_length=128)
    hard_compatible_candidate_count: int = Field(ge=1, le=MAX_GLOBAL_CANDIDATES)
    ranked_candidates: tuple[RoleCandidateRank, ...] = Field(
        min_length=1,
        max_length=MAX_ROLE_CANDIDATES,
    )

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(item.candidate_id for item in self.ranked_candidates)


class RoleCandidateCompatibilityMatrix(_StrictFrozenModel):
    compatibility_version: Literal[
        "finqa_role_candidate_compatibility_v1"
    ] = COMPATIBILITY_VERSION
    global_candidate_count: int = Field(ge=1, le=MAX_GLOBAL_CANDIDATES)
    role_count: int = Field(ge=2, le=6)
    role_allowlists: tuple[RoleCandidateAllowlist, ...] = Field(
        min_length=2,
        max_length=6,
    )
    matrix_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_matrix(self) -> RoleCandidateCompatibilityMatrix:
        role_ids = tuple(item.role_id for item in self.role_allowlists)
        if (
            len(role_ids) != self.role_count
            or len(role_ids) != len(set(role_ids))
        ):
            raise ValueError("role compatibility matrix role count is invalid")
        for allowlist in self.role_allowlists:
            candidate_ids = allowlist.candidate_ids
            if len(candidate_ids) != len(set(candidate_ids)):
                raise ValueError("role compatibility allowlist is duplicated")
        payload = {
            "compatibility_version": self.compatibility_version,
            "global_candidate_count": self.global_candidate_count,
            "role_count": self.role_count,
            "role_allowlists": [
                item.model_dump(mode="json")
                for item in self.role_allowlists
            ],
        }
        expected = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
        if self.matrix_sha256 != expected:
            raise ValueError("role compatibility matrix hash is invalid")
        return self

    def candidate_ids_for_role(self, role_id: str) -> tuple[str, ...]:
        for allowlist in self.role_allowlists:
            if allowlist.role_id == role_id:
                return allowlist.candidate_ids
        raise ValueError("role is absent from compatibility matrix")


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _tokens(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    return frozenset(
        token
        for token in _TOKEN.findall(value.casefold())
        if token not in _STOPWORDS and len(token) > 1
    )


def _candidate_period(candidate: NumericCandidateV2) -> str | None:
    if candidate.period is not None:
        return candidate.period.casefold().strip()
    if candidate.fiscal_year is not None:
        return str(candidate.fiscal_year)
    return None


def _expected_period(
    role: SemanticRoleSpec,
    intent: FinancialQuestionIntentV2,
) -> str | None:
    value = {
        "target": intent.target_period,
        "start": intent.start_period,
        "end": intent.end_period,
        "none": None,
    }[role.period_role]
    return value.casefold().strip() if value is not None else None


def _role_anchor_tokens(
    question: str,
    semantic_role: SemanticRoleName,
) -> frozenset[str]:
    if semantic_role in {"part", "total"}:
        group = semantic_role
        for pattern in _PART_TOTAL_PATTERNS:
            match = pattern.search(question)
            if match is not None:
                return _tokens(match.group(group))
    if semantic_role in {"comparison_left", "comparison_right"}:
        group = "left" if semantic_role == "comparison_left" else "right"
        for pattern in _COMPARISON_PATTERNS:
            match = pattern.search(question)
            if match is not None:
                return _tokens(match.group(group))
    return frozenset()


def _denominator_role_ids(
    skeleton: SemanticProgramSkeleton,
) -> set[str]:
    result: set[str] = set()
    for step in skeleton.steps:
        if step.operation not in {"DIV", "RATIO", "PERCENT_CHANGE"}:
            continue
        denominator = step.arguments[1]
        if isinstance(denominator, SemanticRoleRef):
            result.add(denominator.role_id)
    return result


def hard_compatible_candidates_for_role(
    *,
    role: SemanticRoleSpec,
    skeleton: SemanticProgramSkeleton,
    candidates: Sequence[NumericCandidateV2],
    intent: FinancialQuestionIntentV2,
) -> tuple[NumericCandidateV2, ...]:
    expected_period = _expected_period(role, intent)
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


def validate_semantic_skeleton_compatibility(
    *,
    skeleton: SemanticProgramSkeleton,
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
            raise ValueError("non-temporal semantic role has temporal period role")
    if intent.operation_family == "percent_change":
        by_id = {item.role_id: item for item in skeleton.roles}
        for step in skeleton.steps:
            if step.operation not in {"SUB", "PERCENT_CHANGE"}:
                continue
            first, second = step.arguments
            if (
                isinstance(first, SemanticRoleRef)
                and isinstance(second, SemanticRoleRef)
                and by_id[first.role_id].semantic_role == "old_value"
                and by_id[second.role_id].semantic_role == "new_value"
            ):
                raise ValueError("percent-change temporal roles are reversed")


def _candidate_score(
    *,
    question_tokens: frozenset[str],
    anchor_tokens: frozenset[str],
    candidate: NumericCandidateV2,
    expected_period: str | None,
    evidence_context: str | None,
    evidence_rank: int,
) -> tuple[float, tuple[str, ...]]:
    descriptor_tokens = _tokens(
        " ".join(
            item
            for item in (
                candidate.metric,
                candidate.entity,
                candidate.row_header,
                candidate.column_header,
            )
            if item
        )
    )
    context_tokens = _tokens(evidence_context)
    score = 0.0
    reasons: list[str] = []
    descriptor_overlap = len(question_tokens & descriptor_tokens)
    if descriptor_tokens and descriptor_overlap:
        score += min(12.0, 12.0 * descriptor_overlap / len(descriptor_tokens))
        reasons.append("question_descriptor_overlap")
    context_overlap = len(question_tokens & context_tokens)
    if context_overlap:
        score += min(8.0, context_overlap * 1.0)
        reasons.append("question_context_overlap")
    anchor_overlap = len(anchor_tokens & descriptor_tokens)
    if anchor_tokens and anchor_overlap:
        score += min(18.0, 18.0 * anchor_overlap / len(anchor_tokens))
        reasons.append("role_anchor_descriptor_overlap")
    anchor_context_overlap = len(anchor_tokens & context_tokens)
    if anchor_tokens and anchor_context_overlap:
        score += min(6.0, anchor_context_overlap * 1.5)
        reasons.append("role_anchor_context_overlap")
    period = _candidate_period(candidate)
    if expected_period is not None:
        if period == expected_period:
            score += 30.0
            reasons.append("exact_period")
        elif period is None:
            score += 1.0
            reasons.append("unknown_period_retained")
    if candidate.source_kind == "table_cell":
        score += 2.0
        reasons.append("table_cell")
    score += max(0.0, 2.0 - min(evidence_rank, 4) * 0.5)
    if evidence_rank < 4:
        reasons.append("early_admitted_evidence")
    return score, tuple(reasons)


def build_role_candidate_compatibility_matrix(
    *,
    question: str,
    skeleton: SemanticProgramSkeleton,
    candidates: Sequence[NumericCandidateV2],
    admitted_evidence_ids: set[str],
    intent: FinancialQuestionIntentV2,
    evidence_context_by_id: Mapping[str, str],
    max_candidates_per_role: int = MAX_ROLE_CANDIDATES,
) -> RoleCandidateCompatibilityMatrix:
    question = question.strip()
    if not question or len(question) > 2_000:
        raise ValueError("role compatibility question is outside budget")
    if (
        not candidates
        or len(candidates) > MAX_GLOBAL_CANDIDATES
        or not 1 <= max_candidates_per_role <= MAX_ROLE_CANDIDATES
    ):
        raise ValueError("role compatibility candidate budget is invalid")
    if len(admitted_evidence_ids) > MAX_EVIDENCE_UNITS:
        raise ValueError("role compatibility evidence budget is invalid")
    if set(evidence_context_by_id) - admitted_evidence_ids:
        raise ValueError("role compatibility context is not fully admitted")
    candidate_ids = [item.candidate_id for item in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("role compatibility candidate IDs are duplicated")
    usable = tuple(
        candidate
        for candidate in candidates
        if candidate.role == "operand"
        and candidate.evidence_id in admitted_evidence_ids
    )
    if len(usable) != len(candidates):
        raise ValueError(
            "role compatibility input contains non-admitted or non-operand candidate"
        )
    validate_semantic_skeleton_compatibility(
        skeleton=skeleton,
        intent=intent,
    )

    question_tokens = _tokens(question)
    evidence_rank = {
        evidence_id: index
        for index, evidence_id in enumerate(evidence_context_by_id)
    }
    allowlists: list[RoleCandidateAllowlist] = []
    for role in skeleton.roles:
        expected_period = _expected_period(role, intent)
        anchor_tokens = _role_anchor_tokens(question, role.semantic_role)
        scored: list[tuple[float, str, NumericCandidateV2, tuple[str, ...]]] = []
        hard_compatible = hard_compatible_candidates_for_role(
            role=role,
            skeleton=skeleton,
            candidates=usable,
            intent=intent,
        )
        for candidate in hard_compatible:
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
        if not scored:
            raise ValueError(
                f"role compatibility has empty allowlist for {role.role_id}"
            )
        scored.sort(key=lambda item: (-item[0], item[1]))
        ranked = tuple(
            RoleCandidateRank(
                candidate_id=item[2].candidate_id,
                score=item[0],
                score_reasons=item[3],
            )
            for item in scored[:max_candidates_per_role]
        )
        allowlists.append(
            RoleCandidateAllowlist(
                role_id=role.role_id,
                semantic_role=role.semantic_role,
                period_role=role.period_role,
                expected_period=expected_period,
                hard_compatible_candidate_count=len(hard_compatible),
                ranked_candidates=ranked,
            )
        )
    payload = {
        "compatibility_version": COMPATIBILITY_VERSION,
        "global_candidate_count": len(candidates),
        "role_count": len(skeleton.roles),
        "role_allowlists": [
            item.model_dump(mode="json") for item in allowlists
        ],
    }
    return RoleCandidateCompatibilityMatrix(
        **payload,
        matrix_sha256=hashlib.sha256(_canonical_json_bytes(payload)).hexdigest(),
    )


def role_binding_response_format_by_role(
    matrix: RoleCandidateCompatibilityMatrix,
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


def parse_role_bindings_by_role(
    raw: str,
    *,
    matrix: RoleCandidateCompatibilityMatrix,
) -> SemanticRoleBindings:
    if len(raw) > MAX_RESPONSE_CHARS:
        raise ValueError("role binding response exceeds budget")
    payload = parse_typed_planner_payload(raw)
    try:
        bindings = SemanticRoleBindings.model_validate(payload)
    except ValueError as exc:
        raise ValueError("role binding response schema is invalid") from exc
    expected = {
        allowlist.role_id: set(allowlist.candidate_ids)
        for allowlist in matrix.role_allowlists
    }
    actual = {item.role_id: item.candidate_id for item in bindings.bindings}
    if set(actual) != set(expected):
        raise ValueError("role bindings do not cover the exact role set")
    if any(
        actual[role_id] not in candidates
        for role_id, candidates in expected.items()
    ):
        raise ValueError("role binding violates a role-specific allowlist")
    return bindings


def verify_role_exact_parser_enforcement() -> bool:
    allowlists = (
        RoleCandidateAllowlist(
            role_id="role-01",
            semantic_role="new_value",
            period_role="end",
            expected_period="2020",
            hard_compatible_candidate_count=1,
            ranked_candidates=(
                RoleCandidateRank(
                    candidate_id=f"num-{'a' * 20}",
                    score=1.0,
                    score_reasons=("synthetic_contract",),
                ),
            ),
        ),
        RoleCandidateAllowlist(
            role_id="role-02",
            semantic_role="old_value",
            period_role="start",
            expected_period="2019",
            hard_compatible_candidate_count=1,
            ranked_candidates=(
                RoleCandidateRank(
                    candidate_id=f"num-{'b' * 20}",
                    score=1.0,
                    score_reasons=("synthetic_contract",),
                ),
            ),
        ),
    )
    payload = {
        "compatibility_version": COMPATIBILITY_VERSION,
        "global_candidate_count": 2,
        "role_count": 2,
        "role_allowlists": [
            item.model_dump(mode="json") for item in allowlists
        ],
    }
    matrix = RoleCandidateCompatibilityMatrix(
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
        parse_role_bindings_by_role(invalid, matrix=matrix)
    except ValueError:
        return True
    return False


__all__ = [
    "COMPATIBILITY_VERSION",
    "MAX_GLOBAL_CANDIDATES",
    "MAX_ROLE_CANDIDATES",
    "RoleCandidateAllowlist",
    "RoleCandidateCompatibilityMatrix",
    "RoleCandidateRank",
    "build_role_candidate_compatibility_matrix",
    "hard_compatible_candidates_for_role",
    "parse_role_bindings_by_role",
    "role_binding_response_format_by_role",
    "validate_semantic_skeleton_compatibility",
    "verify_role_exact_parser_enforcement",
]
