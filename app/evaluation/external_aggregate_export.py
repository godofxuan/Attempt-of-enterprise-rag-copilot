from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.evaluation.contracts import StrictModel

_PRIVATE_PAYLOAD_KEYS = frozenset(
    {
        "answer",
        "answers",
        "article_text",
        "case_id",
        "case_ids",
        "company_ids",
        "document_ids",
        "failures",
        "per_case",
        "question",
        "questions",
        "source_path",
        "source_paths",
        "text",
    }
)


class SourceCI(StrictModel):
    run_id: int = Field(gt=0)
    url: str = Field(pattern=r"^https://github\.com/[^/]+/[^/]+/actions/runs/[0-9]+$")
    status: Literal["completed"] = "completed"
    conclusion: Literal["success"] = "success"


class AggregateEvidenceReference(StrictModel):
    schema_version: Literal["enterprise-rag.aggregate-evidence-reference/1.0"] = (
        "enterprise-rag.aggregate-evidence-reference/1.0"
    )
    evidence_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    source_repository: str = Field(pattern=r"^https://github\.com/[^/]+/[^/]+$")
    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_ci: SourceCI
    artifact_path: str = Field(min_length=1, max_length=240)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_schema: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]{0,127}$")
    producing_code_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_scope: str = Field(min_length=1, max_length=500)
    case_count: int = Field(gt=0)
    decision: str = Field(min_length=1, max_length=200)
    allowed_claims: tuple[str, ...] = Field(min_length=1)
    forbidden_claims: tuple[str, ...] = Field(min_length=1)
    payload_granularity: Literal["aggregate_only"] = "aggregate_only"
    formal_case_results: Literal["INPUT_REQUIRED"] = "INPUT_REQUIRED"
    contains_private_case_payload: Literal[False] = False

    @field_validator("artifact_path")
    @classmethod
    def validate_artifact_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or "\\" in value
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("artifact_path must be a normalized repository-relative POSIX path")
        return value

    @field_validator("allowed_claims", "forbidden_claims")
    @classmethod
    def validate_unique_claims(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("claims must not be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("claims must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_ci_identity(self) -> AggregateEvidenceReference:
        expected_suffix = f"/actions/runs/{self.source_ci.run_id}"
        if not self.source_ci.url.startswith(f"{self.source_repository}/"):
            raise ValueError("source_ci.url must belong to source_repository")
        if not self.source_ci.url.endswith(expected_suffix):
            raise ValueError("source_ci.run_id does not match source_ci.url")
        return self


class AggregateEvidenceVerificationError(ValueError):
    pass


def load_and_verify_aggregate_reference(
    reference_path: Path,
    *,
    repository_root: Path,
) -> AggregateEvidenceReference:
    root = repository_root.resolve()
    reference = AggregateEvidenceReference.model_validate_json(
        reference_path.read_text(encoding="utf-8")
    )
    artifact_path = (root / Path(*PurePosixPath(reference.artifact_path).parts)).resolve()
    try:
        artifact_path.relative_to(root)
    except ValueError as exc:
        raise AggregateEvidenceVerificationError("artifact path escapes repository root") from exc
    if not artifact_path.is_file():
        raise AggregateEvidenceVerificationError("referenced artifact does not exist")

    actual_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    if actual_sha256 != reference.artifact_sha256:
        raise AggregateEvidenceVerificationError("referenced artifact SHA-256 mismatch")

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AggregateEvidenceVerificationError("referenced artifact must be a JSON object")
    private_paths = _find_private_payload_keys(payload)
    if private_paths:
        joined = ", ".join(private_paths[:5])
        raise AggregateEvidenceVerificationError(
            f"referenced aggregate artifact contains private payload keys: {joined}"
        )
    if payload.get("decision") != reference.decision:
        raise AggregateEvidenceVerificationError("reference decision does not match artifact")
    protocol_digests = {
        value
        for key, value in payload.items()
        if (key == "protocol_sha256" or key.endswith("_protocol_sha256")) and isinstance(value, str)
    }
    protocol = payload.get("protocol")
    if isinstance(protocol, dict) and isinstance(protocol.get("sha256"), str):
        protocol_digests.add(protocol["sha256"])
    if reference.protocol_sha256 not in protocol_digests:
        raise AggregateEvidenceVerificationError(
            "reference protocol SHA-256 does not match artifact"
        )
    claim_boundary = payload.get("claim_boundary")
    if isinstance(claim_boundary, dict):
        artifact_allowed = claim_boundary.get("allowed")
        artifact_forbidden = claim_boundary.get("forbidden")
        if not isinstance(artifact_allowed, list) or not all(
            isinstance(item, str) for item in artifact_allowed
        ):
            raise AggregateEvidenceVerificationError(
                "artifact allowed claim boundary must be a string list"
            )
        if not isinstance(artifact_forbidden, list) or not all(
            isinstance(item, str) for item in artifact_forbidden
        ):
            raise AggregateEvidenceVerificationError(
                "artifact forbidden claim boundary must be a string list"
            )
        if tuple(artifact_allowed) != reference.allowed_claims:
            raise AggregateEvidenceVerificationError(
                "reference allowed claims do not match artifact"
            )
        if tuple(artifact_forbidden) != reference.forbidden_claims:
            raise AggregateEvidenceVerificationError(
                "reference forbidden claims do not match artifact"
            )
    return reference


def _find_private_payload_keys(value: Any, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).casefold() in _PRIVATE_PAYLOAD_KEYS:
                findings.append(child_path)
            findings.extend(_find_private_payload_keys(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_private_payload_keys(child, path=f"{path}[{index}]"))
    return findings
