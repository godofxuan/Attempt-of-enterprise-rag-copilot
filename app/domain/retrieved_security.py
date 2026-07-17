from __future__ import annotations

from types import MappingProxyType
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DETECTOR_VERSION = "rcg-v1.0.0"
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
    detector_version: Literal["rcg-v1.0.0"]
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


__all__ = [
    "DETECTOR_VERSION",
    "MAX_DECODED_VIEWS",
    "MAX_NORMALIZED_CHARS",
    "MAX_SCAN_CHARS",
    "RULE_SPECS",
    "GuardDecision",
    "GuardDisposition",
    "GuardSeverity",
    "RiskCategory",
]
