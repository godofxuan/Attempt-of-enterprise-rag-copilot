from __future__ import annotations

from types import MappingProxyType
from typing import Annotated, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.agent import AgentAction, BudgetState, ToolError
from app.domain.documents import DocumentStatus, LocatorKind, SourceLocator
from app.domain.queries import (
    FindMatch,
    OpenResult,
    RetrievalMode,
    SearchHit,
    SearchStopReason,
)


DETECTOR_VERSION = "rcg-v1.2.0"
MAX_SCAN_CHARS = 20_000
MAX_NORMALIZED_CHARS = 20_000
MAX_DECODED_VIEWS = 8

GuardDisposition = Literal["ADMIT", "QUARANTINE"]
GuardSeverity = Literal["none", "observe", "quarantine", "error"]
RiskCategory = Literal[
    "instruction_override",
    "role_impersonation",
    "secret_extraction",
    "tool_egress",
    "invisible_unicode",
    "encoded_payload",
    "markup_wrapper",
    "split_payload",
    "guard_error",
]

RULE_SPECS: Mapping[str, tuple[RiskCategory, GuardSeverity]] = MappingProxyType(
    {
        "RCG-BASE64-DECODED-001": ("encoded_payload", "quarantine"),
        "RCG-EGRESS-SENSITIVE-DATA-001": ("tool_egress", "quarantine"),
        "RCG-GUARD-ERROR": ("guard_error", "error"),
        "RCG-INSTRUCTION-OVERRIDE-001": (
            "instruction_override",
            "quarantine",
        ),
        "RCG-INVISIBLE-BIDI-001": ("invisible_unicode", "quarantine"),
        "RCG-INVISIBLE-CONTROL-OBSERVE-001": (
            "invisible_unicode",
            "observe",
        ),
        "RCG-INVISIBLE-NFKC-001": ("invisible_unicode", "quarantine"),
        "RCG-INVISIBLE-OBFUSCATION-001": (
            "invisible_unicode",
            "quarantine",
        ),
        "RCG-MARKUP-WRAPPED-DIRECTIVE-001": (
            "markup_wrapper",
            "quarantine",
        ),
        "RCG-ROLE-BOUNDARY-001": ("role_impersonation", "quarantine"),
        "RCG-SECRET-EXTRACTION-001": (
            "secret_extraction",
            "quarantine",
        ),
        "RCG-SPLIT-ADJACENT-001": ("split_payload", "quarantine"),
    }
)

_SEVERITY_ORDER = {"none": 0, "observe": 1, "quarantine": 2, "error": 3}


class GuardDecision(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

    disposition: GuardDisposition
    max_severity: GuardSeverity
    risk_categories: tuple[RiskCategory, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    rule_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    detector_version: Literal["rcg-v1.2.0"]
    original_length: int = Field(ge=0)
    normalized_length: int = Field(ge=0, le=MAX_NORMALIZED_CHARS)
    scanned_length: int = Field(ge=0, le=MAX_SCAN_CHARS)
    decoded_view_count: int = Field(ge=0, le=MAX_DECODED_VIEWS)
    guard_error: bool = False

    @field_validator("risk_categories")
    @classmethod
    def validate_categories(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("risk categories must be unique and sorted")
        return values

    @field_validator("rule_ids")
    @classmethod
    def validate_rule_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("rule IDs must be unique and sorted")
        if any(value not in RULE_SPECS for value in values):
            raise ValueError("rule IDs must come from the detector allowlist")
        return values

    @model_validator(mode="after")
    def validate_decision_state(self) -> GuardDecision:
        if self.scanned_length > self.original_length:
            raise ValueError("scanned length cannot exceed original length")

        expected_categories = tuple(
            sorted({RULE_SPECS[rule_id][0] for rule_id in self.rule_ids})
        )
        if self.risk_categories != expected_categories:
            raise ValueError("risk categories must exactly match the rule allowlist")

        expected_severity: GuardSeverity = "none"
        for rule_id in self.rule_ids:
            rule_severity = RULE_SPECS[rule_id][1]
            if _SEVERITY_ORDER[rule_severity] > _SEVERITY_ORDER[expected_severity]:
                expected_severity = rule_severity
        if self.max_severity != expected_severity:
            raise ValueError("max severity must exactly match the strongest rule")

        guard_error_rules = ("RCG-GUARD-ERROR",)
        if "RCG-GUARD-ERROR" in self.rule_ids and self.rule_ids != guard_error_rules:
            raise ValueError("guard error cannot be combined with detector rules")
        if self.guard_error != (self.rule_ids == guard_error_rules):
            raise ValueError("guard_error must exactly match the guard-error rule")

        expected_disposition = (
            "QUARANTINE"
            if expected_severity in {"quarantine", "error"}
            else "ADMIT"
        )
        if self.disposition != expected_disposition:
            raise ValueError("disposition must exactly match rule severity")
        return self


GuardFieldKind = Literal[
    "matched",
    "parent",
    "find_preview",
    "open",
    "metadata",
    "aggregate",
]
GuardOperation = Literal["search", "find", "open"]


class _GuardedModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class AdmittedSourceLocatorSnapshot(_GuardedModel):
    kind: LocatorKind
    start: int = Field(ge=1)
    end: int | None = Field(default=None, ge=1)
    label: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> AdmittedSourceLocatorSnapshot:
        if self.end is not None and self.end < self.start:
            raise ValueError("locator end must not be earlier than start")
        return self

    @classmethod
    def from_raw(cls, locator: SourceLocator) -> AdmittedSourceLocatorSnapshot:
        return cls(
            kind=locator.kind,
            start=locator.start,
            end=locator.end,
            label=locator.label,
        )


class AdmittedSearchHitSnapshot(_GuardedModel):
    index_run_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    parent_chunk_id: str | None = None
    policy_id: str | None = None
    source_path: str = Field(min_length=1)
    section_path: tuple[str, ...] = Field(min_length=1)
    locator: AdmittedSourceLocatorSnapshot | None = None
    matched_text: str = Field(min_length=1)
    context_text: str = Field(min_length=1)
    context_from_parent: bool = False
    tenant_id: str = Field(min_length=1)
    region: str = Field(min_length=1)
    acl_groups: tuple[str, ...] = Field(min_length=1)
    version_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: DocumentStatus
    authority_level: int = Field(ge=1, le=100)
    variant: str = Field(min_length=1)
    fact_ids: tuple[str, ...] = Field(default_factory=tuple)
    fused_score: float
    dense_score: float | None = None
    bm25_score: float | None = None
    dense_rank: int | None = Field(default=None, ge=1)
    bm25_rank: int | None = Field(default=None, ge=1)

    @field_validator("acl_groups", "fact_ids")
    @classmethod
    def validate_unique_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("admitted hit values must be unique")
        return values

    @classmethod
    def from_raw(cls, hit: SearchHit) -> AdmittedSearchHitSnapshot:
        values = hit.model_dump()
        values["section_path"] = tuple(hit.section_path)
        values["acl_groups"] = tuple(hit.acl_groups)
        values["fact_ids"] = tuple(hit.fact_ids)
        values["locator"] = (
            AdmittedSourceLocatorSnapshot.from_raw(hit.locator)
            if hit.locator is not None
            else None
        )
        return cls(**values)


class AdmittedFindMatchSnapshot(_GuardedModel):
    doc_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    section_path: tuple[str, ...] = Field(min_length=1)
    preview: str = Field(min_length=1, max_length=1000)

    @classmethod
    def from_raw(cls, match: FindMatch) -> AdmittedFindMatchSnapshot:
        return cls(
            doc_id=match.doc_id,
            chunk_id=match.chunk_id,
            section_path=tuple(match.section_path),
            preview=match.preview,
        )


class AdmittedOpenResultSnapshot(_GuardedModel):
    request_id: str = Field(min_length=1)
    target_type: Literal["chunk", "parent", "document"]
    target_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    truncated: bool
    source_path: str = Field(min_length=1)
    section_path: tuple[str, ...] = Field(default_factory=tuple)

    @classmethod
    def from_raw(cls, result: OpenResult) -> AdmittedOpenResultSnapshot:
        return cls(
            request_id=result.request_id,
            target_type=result.target_type,
            target_id=result.target_id,
            doc_id=result.doc_id,
            content=result.content,
            truncated=result.truncated,
            source_path=result.source_path,
            section_path=tuple(result.section_path),
        )


def _require_admit(decision: GuardDecision, field_name: str) -> None:
    if decision.disposition != "ADMIT":
        raise ValueError(f"{field_name} must carry an ADMIT decision")


class AdmittedEvidenceChunk(_GuardedModel):
    hit: AdmittedSearchHitSnapshot
    matched_decision: GuardDecision
    context_decision: GuardDecision | None = None
    metadata_decision: GuardDecision

    @field_validator("hit", mode="before")
    @classmethod
    def snapshot_hit(
        cls,
        value: SearchHit | AdmittedSearchHitSnapshot,
    ) -> AdmittedSearchHitSnapshot:
        if isinstance(value, AdmittedSearchHitSnapshot):
            return value
        if isinstance(value, SearchHit):
            return AdmittedSearchHitSnapshot.from_raw(value)
        raise TypeError("admitted evidence requires a typed SearchHit")

    @model_validator(mode="after")
    def validate_admitted_fields(self) -> AdmittedEvidenceChunk:
        _require_admit(self.matched_decision, "matched content")
        _require_admit(self.metadata_decision, "metadata")
        if self.hit.context_from_parent:
            if self.context_decision is None:
                raise ValueError("parent context requires context_decision")
            _require_admit(self.context_decision, "parent context")
        else:
            if self.context_decision is not None:
                raise ValueError(
                    "context_decision is only valid for distinct parent context"
                )
            if self.hit.context_text != self.hit.matched_text:
                raise ValueError(
                    "child-only context must equal matched content"
                )
        return self


class AdmittedFindMatch(_GuardedModel):
    match: AdmittedFindMatchSnapshot
    preview_decision: GuardDecision
    metadata_decision: GuardDecision

    @field_validator("match", mode="before")
    @classmethod
    def snapshot_match(
        cls,
        value: FindMatch | AdmittedFindMatchSnapshot,
    ) -> AdmittedFindMatchSnapshot:
        if isinstance(value, AdmittedFindMatchSnapshot):
            return value
        if isinstance(value, FindMatch):
            return AdmittedFindMatchSnapshot.from_raw(value)
        raise TypeError("admitted find evidence requires a typed FindMatch")

    @model_validator(mode="after")
    def validate_admitted_fields(self) -> AdmittedFindMatch:
        _require_admit(self.preview_decision, "find preview")
        _require_admit(self.metadata_decision, "find metadata")
        return self


class AdmittedOpenResult(_GuardedModel):
    result: AdmittedOpenResultSnapshot
    content_decision: GuardDecision
    metadata_decision: GuardDecision

    @field_validator("result", mode="before")
    @classmethod
    def snapshot_result(
        cls,
        value: OpenResult | AdmittedOpenResultSnapshot,
    ) -> AdmittedOpenResultSnapshot:
        if isinstance(value, AdmittedOpenResultSnapshot):
            return value
        if isinstance(value, OpenResult):
            return AdmittedOpenResultSnapshot.from_raw(value)
        raise TypeError("admitted open evidence requires a typed OpenResult")

    @model_validator(mode="after")
    def validate_admitted_fields(self) -> AdmittedOpenResult:
        _require_admit(self.content_decision, "open content")
        _require_admit(self.metadata_decision, "open metadata")
        return self


class QuarantineSummary(_GuardedModel):
    internal_item_key: str = Field(min_length=1, exclude=True, repr=False)
    field_kind: GuardFieldKind
    decision: GuardDecision

    @model_validator(mode="after")
    def validate_quarantine(self) -> QuarantineSummary:
        if self.decision.disposition != "QUARANTINE":
            raise ValueError("quarantine summary requires a QUARANTINE decision")
        return self


class ScannedContentUnit(_GuardedModel):
    operation: GuardOperation
    surface: GuardFieldKind
    internal_item_key: str = Field(
        min_length=1,
        exclude=True,
        repr=False,
    )
    member_internal_ids: tuple[str, ...] = Field(
        min_length=1,
        max_length=16,
        exclude=True,
        repr=False,
    )
    aggregate: bool
    disposition: GuardDisposition
    rule_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=32)

    @field_validator("member_internal_ids")
    @classmethod
    def validate_member_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value for value in values):
            raise ValueError("scan member IDs must be non-empty identifiers")
        if len(values) != len(set(values)):
            raise ValueError("scan member IDs must be unique")
        return values

    @field_validator("rule_ids")
    @classmethod
    def validate_scan_rule_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("scan rule IDs must be unique and sorted")
        if any(value not in RULE_SPECS for value in values):
            raise ValueError("scan rule IDs must come from the detector allowlist")
        return values

    @model_validator(mode="after")
    def validate_scan_provenance(self) -> ScannedContentUnit:
        allowed_surfaces = {
            "search": {"matched", "parent", "metadata", "aggregate"},
            "find": {"find_preview", "metadata"},
            "open": {"open", "metadata"},
        }
        if self.surface not in allowed_surfaces[self.operation]:
            raise ValueError("scan surface is not valid for the operation")
        if self.aggregate != (self.surface == "aggregate"):
            raise ValueError("aggregate flag must exactly match aggregate surface")
        if self.aggregate:
            if len(self.member_internal_ids) < 2:
                raise ValueError("aggregate scan requires at least two members")
            if self.internal_item_key != ":".join(self.member_internal_ids):
                raise ValueError("aggregate scan key must exactly match its members")
        elif (
            len(self.member_internal_ids) != 1
            or self.member_internal_ids[0] != self.internal_item_key
        ):
            raise ValueError("non-aggregate scan requires its exact item as one member")

        quarantined = any(
            RULE_SPECS[rule_id][1] in {"quarantine", "error"}
            for rule_id in self.rule_ids
        )
        expected_disposition = "QUARANTINE" if quarantined else "ADMIT"
        if self.disposition != expected_disposition:
            raise ValueError("scan disposition must exactly match its rule severity")
        return self


class SecurityCounters(_GuardedModel):
    candidate_count: int = Field(ge=0)
    scanned_count: int = Field(ge=0)
    admitted_count: int = Field(ge=0)
    quarantined_count: int = Field(ge=0)
    scanned_chars: int = Field(ge=0)
    decoded_candidate_count: int = Field(ge=0)
    top_up_attempts: Literal[0, 1]
    post_guard_evidence_count: int = Field(ge=0)
    guard_error_count: int = Field(ge=0)
    risk_categories: tuple[RiskCategory, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    rule_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    detector_version: Literal["rcg-v1.2.0"]

    @field_validator("risk_categories")
    @classmethod
    def validate_categories(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("risk categories must be unique and sorted")
        return values

    @field_validator("rule_ids")
    @classmethod
    def validate_rule_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("rule IDs must be unique and sorted")
        if any(value not in RULE_SPECS for value in values):
            raise ValueError("rule IDs must come from the detector allowlist")
        return values

    @model_validator(mode="after")
    def validate_counter_state(self) -> SecurityCounters:
        if self.scanned_count != self.admitted_count + self.quarantined_count:
            raise ValueError(
                "scanned_count must equal admitted_count plus quarantined_count"
            )
        if self.post_guard_evidence_count > self.admitted_count:
            raise ValueError(
                "post_guard_evidence_count cannot exceed admitted_count"
            )
        if self.guard_error_count > self.quarantined_count:
            raise ValueError("guard_error_count cannot exceed quarantined_count")
        expected_categories = tuple(
            sorted({RULE_SPECS[rule_id][0] for rule_id in self.rule_ids})
        )
        if self.risk_categories != expected_categories:
            raise ValueError("risk categories must exactly match rule IDs")
        return self


class RetrievedContentSecurityTrace(SecurityCounters):
    stop_reason: Literal["evidence_filtered"] | None = None

    @model_validator(mode="after")
    def validate_public_stop_reason(self) -> RetrievedContentSecurityTrace:
        filtered = (
            self.candidate_count > 0
            and self.post_guard_evidence_count == 0
            and self.quarantined_count > 0
        )
        if filtered != (self.stop_reason == "evidence_filtered"):
            raise ValueError(
                "public stop reason must exactly identify all-filtered evidence"
            )
        return self

    @classmethod
    def from_counters(
        cls,
        counters: SecurityCounters,
        *,
        stop_reason: Literal["evidence_filtered"] | None,
    ) -> RetrievedContentSecurityTrace:
        return cls(
            **counters.model_dump(mode="python"),
            stop_reason=stop_reason,
        )


class GuardedSearchResult(_GuardedModel):
    request_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    mode: RetrievalMode
    index_run_id: str = Field(min_length=1)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hits: tuple[AdmittedEvidenceChunk, ...] = Field(default_factory=tuple)
    visible_candidate_count: int = Field(ge=0)
    internal_denied_count: int = Field(ge=0, exclude=True)
    stage_counts: dict[str, int] = Field(default_factory=dict)
    stop_reason: SearchStopReason

    @model_validator(mode="after")
    def validate_result(self) -> GuardedSearchResult:
        chunk_ids = [item.hit.chunk_id for item in self.hits]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("guarded search chunk IDs must be unique")
        if any(item.hit.index_run_id != self.index_run_id for item in self.hits):
            raise ValueError("guarded hit index run must match result index run")
        if any(value < 0 for value in self.stage_counts.values()):
            raise ValueError("stage counts must be non-negative")
        return self


class GuardedFindResult(_GuardedModel):
    request_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    matches: tuple[AdmittedFindMatch, ...] = Field(default_factory=tuple)
    stop_reason: Literal["ok", "not_found", "timeout"]


class GuardedOpenAdmittedResult(_GuardedModel):
    outcome: Literal["admitted"] = "admitted"
    item: AdmittedOpenResult


class GuardedOpenQuarantinedResult(_GuardedModel):
    outcome: Literal["quarantined"] = "quarantined"
    request_id: str = Field(min_length=1)


GuardedOpenResult = Annotated[
    GuardedOpenAdmittedResult | GuardedOpenQuarantinedResult,
    Field(discriminator="outcome"),
]
GuardedToolPayload = (
    GuardedSearchResult
    | GuardedFindResult
    | GuardedOpenAdmittedResult
    | GuardedOpenQuarantinedResult
    | ToolError
)


class GuardedV2ToolExecution(_GuardedModel):
    action: AgentAction
    result: GuardedToolPayload
    budget_state: BudgetState
    status: Literal["ok", "error"]
    visible_count: int = Field(ge=0)
    context_chars_added: int = Field(ge=0)
    quarantine_summaries: tuple[QuarantineSummary, ...] = Field(
        default_factory=tuple
    )
    security_counters: SecurityCounters
    security_stop_reason: Literal["evidence_filtered"] | None = None

    @model_validator(mode="after")
    def validate_execution(self) -> GuardedV2ToolExecution:
        if isinstance(self.result, ToolError):
            if self.status != "error":
                raise ValueError("ToolError requires error status")
            expected_visible = 0
        else:
            if self.status != "ok":
                raise ValueError("guarded payload requires ok status")
            expected_types = {
                "search": GuardedSearchResult,
                "find": GuardedFindResult,
                "open": (
                    GuardedOpenAdmittedResult,
                    GuardedOpenQuarantinedResult,
                ),
            }
            expected_type = expected_types.get(self.action.tool)
            if expected_type is None or not isinstance(self.result, expected_type):
                raise ValueError("action tool and guarded payload type must match")
            if isinstance(self.result, GuardedSearchResult):
                expected_visible = len(self.result.hits)
            elif isinstance(self.result, GuardedFindResult):
                expected_visible = len(self.result.matches)
            elif isinstance(self.result, GuardedOpenAdmittedResult):
                expected_visible = 1
            else:
                expected_visible = 0

        if self.visible_count != expected_visible:
            raise ValueError("visible_count must match admitted result objects")
        if self.security_counters.post_guard_evidence_count != expected_visible:
            raise ValueError(
                "post_guard_evidence_count must match admitted result objects"
            )
        if (
            len(self.quarantine_summaries)
            != self.security_counters.quarantined_count
        ):
            raise ValueError(
                "quarantine summaries must match quarantined content count"
            )
        filtered = (
            self.status == "ok"
            and self.security_counters.candidate_count > 0
            and self.visible_count == 0
            and self.security_counters.quarantined_count > 0
        )
        if filtered != (self.security_stop_reason == "evidence_filtered"):
            raise ValueError(
                "evidence_filtered must exactly identify an all-quarantined result"
            )
        return self


__all__ = [
    "DETECTOR_VERSION",
    "MAX_DECODED_VIEWS",
    "MAX_NORMALIZED_CHARS",
    "MAX_SCAN_CHARS",
    "RULE_SPECS",
    "AdmittedEvidenceChunk",
    "AdmittedFindMatch",
    "AdmittedFindMatchSnapshot",
    "AdmittedOpenResult",
    "AdmittedOpenResultSnapshot",
    "AdmittedSearchHitSnapshot",
    "AdmittedSourceLocatorSnapshot",
    "GuardDecision",
    "GuardDisposition",
    "GuardFieldKind",
    "GuardOperation",
    "GuardedFindResult",
    "GuardedOpenAdmittedResult",
    "GuardedOpenQuarantinedResult",
    "GuardedOpenResult",
    "GuardedSearchResult",
    "GuardedToolPayload",
    "GuardedV2ToolExecution",
    "GuardSeverity",
    "QuarantineSummary",
    "RiskCategory",
    "ScannedContentUnit",
    "RetrievedContentSecurityTrace",
    "SecurityCounters",
]
