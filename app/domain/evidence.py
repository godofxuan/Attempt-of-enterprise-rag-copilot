from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.agent import AgentStopReason, AnswerMode
from app.domain.documents import DocumentStatus


EvidenceRelation = Literal["supports", "conflicts"]
LedgerAction = Literal[
    "answer",
    "search",
    "find",
    "open",
    "partial",
    "not_found",
    "permission",
    "budget",
    "system",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _unique(values: list[str], label: str) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
    return values


class EvidenceItem(StrictModel):
    aspect: str = Field(min_length=1, max_length=500)
    chunk_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    relation: EvidenceRelation
    authority_level: int = Field(ge=1, le=100)
    version_id: str = Field(min_length=1)
    status: DocumentStatus


class EvidenceLedger(StrictModel):
    required_aspects: list[str] = Field(min_length=1, max_length=20)
    items: list[EvidenceItem] = Field(default_factory=list)
    supported_aspects: list[str] = Field(default_factory=list)
    conflicting_aspects: list[str] = Field(default_factory=list)
    missing_aspects: list[str] = Field(default_factory=list)
    coverage: float = Field(ge=0.0, le=1.0)
    recommended_action: LedgerAction

    @field_validator(
        "required_aspects",
        "supported_aspects",
        "conflicting_aspects",
        "missing_aspects",
    )
    @classmethod
    def validate_unique_aspects(cls, values: list[str]) -> list[str]:
        return _unique(values, "ledger aspects")

    @model_validator(mode="after")
    def validate_ledger(self) -> EvidenceLedger:
        required = set(self.required_aspects)
        supported = set(self.supported_aspects)
        missing = set(self.missing_aspects)
        conflicting = set(self.conflicting_aspects)
        if not supported.issubset(required) or not missing.issubset(required):
            raise ValueError("ledger aspects must belong to required aspects")
        if supported & missing:
            raise ValueError("supported and missing aspects must be disjoint")
        if supported | missing != required:
            raise ValueError("supported and missing aspects must partition required aspects")
        if not conflicting.issubset(missing):
            raise ValueError("conflicting aspects must remain missing until resolved")
        if any(item.aspect not in required for item in self.items):
            raise ValueError("evidence item aspect must be required")
        expected_coverage = len(supported) / len(required)
        if abs(self.coverage - expected_coverage) > 1e-9:
            raise ValueError(
                f"coverage must equal supported/required ({expected_coverage})"
            )
        if self.recommended_action == "answer" and (
            self.coverage != 1.0 or conflicting
        ):
            raise ValueError("answer action requires full nonconflicting coverage")
        return self


class Claim(StrictModel):
    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=2000)
    critical: bool = True
    cited_chunk_ids: list[str] = Field(default_factory=list, max_length=20)


class ClaimCitation(StrictModel):
    claim_id: str = Field(min_length=1)
    cited_chunk_ids: list[str] = Field(default_factory=list, max_length=20)
    citation_present: bool
    references_visible_evidence: bool
    lexical_support: float = Field(ge=0.0, le=1.0)
    supported: bool
    unsupported_reason: str | None = Field(default=None, max_length=500)

    @field_validator("cited_chunk_ids")
    @classmethod
    def validate_unique_citations(cls, values: list[str]) -> list[str]:
        return _unique(values, "cited chunk IDs")

    @model_validator(mode="after")
    def validate_flags(self) -> ClaimCitation:
        if self.citation_present != bool(self.cited_chunk_ids):
            raise ValueError("citation_present must match cited_chunk_ids")
        can_support = (
            self.citation_present
            and self.references_visible_evidence
            and self.lexical_support > 0
        )
        if self.supported and not can_support:
            raise ValueError("supported citation must reference visible evidence")
        if self.supported and self.unsupported_reason is not None:
            raise ValueError("supported citation cannot include unsupported_reason")
        if not self.supported and not self.unsupported_reason:
            raise ValueError("unsupported citation requires unsupported_reason")
        return self


class AnswerSource(StrictModel):
    doc_id: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    section_path: list[str] = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    preview: str = Field(min_length=1, max_length=1000)


class AnswerResponse(StrictModel):
    mode: AnswerMode
    answer: str = Field(min_length=1, max_length=20_000)
    claims: list[Claim] = Field(default_factory=list)
    citations: list[ClaimCitation] = Field(default_factory=list)
    sources: list[AnswerSource] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    stop_reason: AgentStopReason | None = None
    trace: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_response_shape(self) -> AnswerResponse:
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim IDs must be unique")
        citation_claim_ids = [citation.claim_id for citation in self.citations]
        if any(claim_id not in claim_ids for claim_id in citation_claim_ids):
            raise ValueError("citation must reference a response claim")
        if self.mode == "answered":
            if not self.claims or not self.citations or not self.sources:
                raise ValueError(
                    "answered response requires claims, citations, and sources"
                )
            if set(citation_claim_ids) != set(claim_ids):
                raise ValueError("answered response requires citation for every claim")
        source_free_modes = {
            "unsafe",
            "permission",
            "not_found",
            "system",
            "budget",
        }
        if self.mode in source_free_modes and self.sources:
            raise ValueError(f"{self.mode} response sources must be empty")
        return self


__all__ = [
    "AnswerResponse",
    "AnswerSource",
    "Claim",
    "ClaimCitation",
    "EvidenceItem",
    "EvidenceLedger",
    "EvidenceRelation",
    "LedgerAction",
]
