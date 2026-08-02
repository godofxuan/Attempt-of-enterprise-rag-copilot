from __future__ import annotations

import hashlib
import inspect
import json
import re
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import Field, model_validator

from app.external_datasets.finqa_numeric_evidence_v2 import NumericCandidateV2
from app.external_datasets.finqa_role_compatibility import (
    _candidate_period,
    _candidate_score,
    _tokens,
)
from app.external_datasets.finqa_role_compatibility_v2 import (
    MAX_EVIDENCE_UNITS,
    MAX_ROLE_CANDIDATES,
    MAX_SOURCE_CANDIDATES,
    MAX_UNIQUE_EXPOSED_CANDIDATES,
    _StrictFrozenModel,
)
from app.external_datasets.finqa_semantic_program_v2 import SemanticRoleRefV2
from app.external_datasets.finqa_semantic_program_v3 import (
    SemanticProgramSkeletonV3,
    SemanticRoleSpecV3,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    FinancialQuestionIntentV2,
)


COMPATIBILITY_VERSION = "finqa_role_candidate_compatibility_v3"
_NUMERIC_TOKEN = re.compile(r"(?<!\w)-?\d+(?:\.\d+)?(?!\w)")


class RoleCandidateRankV3(_StrictFrozenModel):
    candidate_id: str = Field(pattern=r"^num-[0-9a-f]{20}$")
    score: float
    score_reasons: tuple[str, ...]


class RoleCandidateAllowlistV3(_StrictFrozenModel):
    role_id: str = Field(pattern=r"^role-0[1-8]$")
    semantic_role: str = Field(min_length=1, max_length=64)
    role_query: str = Field(min_length=2, max_length=160)
    expected_period: str | None = Field(default=None, max_length=128)
    hard_compatible_candidate_count: int = Field(
        ge=1,
        le=MAX_SOURCE_CANDIDATES,
    )
    ranked_candidates: tuple[RoleCandidateRankV3, ...] = Field(
        min_length=1,
        max_length=MAX_ROLE_CANDIDATES,
    )

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(item.candidate_id for item in self.ranked_candidates)


class RoleCandidateCompatibilityMatrixV3(_StrictFrozenModel):
    compatibility_version: Literal[
        "finqa_role_candidate_compatibility_v3"
    ] = COMPATIBILITY_VERSION
    source_candidate_count: int = Field(ge=1, le=MAX_SOURCE_CANDIDATES)
    role_count: int = Field(ge=1, le=8)
    unique_exposed_candidate_count: int = Field(
        ge=1,
        le=MAX_UNIQUE_EXPOSED_CANDIDATES,
    )
    role_allowlists: tuple[RoleCandidateAllowlistV3, ...] = Field(
        min_length=1,
        max_length=8,
    )
    matrix_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_matrix(self) -> RoleCandidateCompatibilityMatrixV3:
        role_ids = tuple(item.role_id for item in self.role_allowlists)
        if (
            len(role_ids) != self.role_count
            or len(role_ids) != len(set(role_ids))
        ):
            raise ValueError("role compatibility v3 role count is invalid")
        exposed = {
            candidate_id
            for allowlist in self.role_allowlists
            for candidate_id in allowlist.candidate_ids
        }
        if len(exposed) != self.unique_exposed_candidate_count:
            raise ValueError("role compatibility v3 exposure count is invalid")
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
            raise ValueError("role compatibility v3 matrix hash is invalid")
        return self

    def candidate_ids_for_role(self, role_id: str) -> tuple[str, ...]:
        for allowlist in self.role_allowlists:
            if allowlist.role_id == role_id:
                return allowlist.candidate_ids
        raise ValueError("role is absent from compatibility v3 matrix")

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


def _role_tokens(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    return _tokens(value) | frozenset(_NUMERIC_TOKEN.findall(value))


def _denominator_role_ids(
    skeleton: SemanticProgramSkeletonV3,
) -> set[str]:
    result = set()
    for step in skeleton.steps:
        if step.operation not in {"DIV", "RATIO", "PERCENT_CHANGE"}:
            continue
        denominator = step.arguments[1]
        if isinstance(denominator, SemanticRoleRefV2):
            result.add(denominator.role_id)
    return result


def hard_compatible_candidates_for_role_v3(
    *,
    role: SemanticRoleSpecV3,
    skeleton: SemanticProgramSkeletonV3,
    candidates: Sequence[NumericCandidateV2],
) -> tuple[NumericCandidateV2, ...]:
    expected_period = (
        role.expected_period.casefold().strip()
        if role.expected_period is not None
        else None
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


def build_role_candidate_compatibility_matrix_v3(
    *,
    question: str,
    skeleton: SemanticProgramSkeletonV3,
    candidates: Sequence[NumericCandidateV2],
    admitted_evidence_ids: set[str],
    intent: FinancialQuestionIntentV2,
    evidence_context_by_id: Mapping[str, str],
) -> RoleCandidateCompatibilityMatrixV3:
    question = question.strip()
    if (
        not question
        or len(question) > 2_000
        or not candidates
        or len(candidates) > MAX_SOURCE_CANDIDATES
    ):
        raise ValueError("role compatibility v3 input budget is invalid")
    if len(admitted_evidence_ids) > MAX_EVIDENCE_UNITS:
        raise ValueError("role compatibility v3 evidence budget is invalid")
    if set(evidence_context_by_id) - admitted_evidence_ids:
        raise ValueError("role compatibility v3 context is not admitted")
    if any(
        item.role != "operand"
        or item.evidence_id not in admitted_evidence_ids
        for item in candidates
    ):
        raise ValueError("role compatibility v3 input is not admitted")
    candidate_ids = [item.candidate_id for item in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("role compatibility v3 candidate IDs are duplicated")

    evidence_rank = {
        evidence_id: index
        for index, evidence_id in enumerate(evidence_context_by_id)
    }
    allowlists = []
    for role in skeleton.roles:
        hard = hard_compatible_candidates_for_role_v3(
            role=role,
            skeleton=skeleton,
            candidates=candidates,
        )
        if not hard:
            raise ValueError(
                f"role compatibility v3 has empty allowlist for {role.role_id}"
            )
        role_tokens = _role_tokens(role.role_query)
        expected_period = (
            role.expected_period.casefold().strip()
            if role.expected_period is not None
            else None
        )
        scored = []
        for candidate in hard:
            score, reasons = _candidate_score(
                question_tokens=_tokens(role.role_query),
                anchor_tokens=_tokens(role.role_query),
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
            descriptor = " ".join(
                item
                for item in (
                    candidate.metric,
                    candidate.entity,
                    candidate.row_header,
                    candidate.column_header,
                    evidence_context_by_id.get(candidate.evidence_id),
                )
                if item
            )
            overlap = len(role_tokens & _role_tokens(descriptor))
            if overlap:
                score += min(20.0, overlap * 4.0)
                reasons = (*reasons, "v3_role_query_overlap")
            if (
                expected_period is not None
                and expected_period.casefold() in descriptor.casefold()
                and _candidate_period(candidate) is None
            ):
                score += 30.0
                reasons = (*reasons, "v3_period_text_match")
            scored.append((score, candidate.candidate_id, candidate, reasons))
        scored.sort(key=lambda item: (-item[0], item[1]))
        allowlists.append(
            RoleCandidateAllowlistV3(
                role_id=role.role_id,
                semantic_role=role.semantic_role,
                role_query=role.role_query,
                expected_period=expected_period,
                hard_compatible_candidate_count=len(hard),
                ranked_candidates=tuple(
                    RoleCandidateRankV3(
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
        raise ValueError("role compatibility v3 exposure budget exceeded")
    payload = {
        "compatibility_version": COMPATIBILITY_VERSION,
        "source_candidate_count": len(candidates),
        "role_count": len(skeleton.roles),
        "unique_exposed_candidate_count": len(unique_exposed),
        "role_allowlists": [
            item.model_dump(mode="json") for item in allowlists
        ],
    }
    return RoleCandidateCompatibilityMatrixV3(
        **payload,
        matrix_sha256=hashlib.sha256(
            _canonical_json_bytes(payload)
        ).hexdigest(),
    )


def verify_no_gold_runtime_inputs_v3() -> bool:
    function = build_role_candidate_compatibility_matrix_v3
    forbidden = ("gold", "answer", "case_id", "gold_evidence")
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
    "COMPATIBILITY_VERSION",
    "RoleCandidateAllowlistV3",
    "RoleCandidateCompatibilityMatrixV3",
    "RoleCandidateRankV3",
    "build_role_candidate_compatibility_matrix_v3",
    "hard_compatible_candidates_for_role_v3",
    "verify_no_gold_runtime_inputs_v3",
]
