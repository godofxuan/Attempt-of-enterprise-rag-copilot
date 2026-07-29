from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from types import MappingProxyType
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

from app.external_datasets.finqa import FinQACase


EXTRACTION_VERSION = "finqa_numeric_candidate_v1"
CANDIDATE_MANIFEST_VERSION = "finqa_numeric_candidate_manifest_v1"
MAX_SOURCE_TEXT_CHARS = 16_000
MAX_CANDIDATES_PER_SOURCE = 256
MAX_ABSOLUTE_VALUE = Decimal("1e30")

SourceKind = Literal["text", "table_cell"]
CandidateRole = Literal["operand", "period_label", "ordinal", "page_number"]
FinancialUnit = Literal[
    "usd",
    "eur",
    "gbp",
    "cny",
    "ratio",
    "count",
    "shares",
    "unknown",
]
FinancialScale = Literal[
    "one",
    "thousand",
    "million",
    "billion",
    "trillion",
    "percent",
    "basis_point",
    "unknown",
]
TypedFinancialOperation = Literal[
    "ADD",
    "SUB",
    "MUL",
    "DIV",
    "PERCENT_CHANGE",
    "RATIO",
    "AVERAGE",
]
FailureReason = Literal[
    "missing_candidate",
    "duplicate_candidate",
    "temporal_mismatch",
    "metric_mismatch",
    "unit_mismatch",
    "scale_mismatch",
    "sign_mismatch",
    "direction_mismatch",
    "literal_only_operand",
    "unsupported_operation",
    "invalid_arity",
    "divide_by_zero",
    "missing_provenance",
    "unadmitted_source",
    "invalid_candidate_role",
    "forward_step_reference",
    "duplicate_step_id",
    "missing_output_step",
    "budget_exceeded",
    "ambiguous_intent",
    "invalid_program_schema",
]

DSL_VERSION = "finqa_typed_financial_dsl_v1"
VALIDATOR_VERSION = "finqa_typed_program_validator_v1"
COMPILER_VERSION = "finqa_typed_program_compiler_v1"
MAX_PROGRAM_STEPS = 8
MAX_PROGRAM_ARGUMENTS = 8
MAX_PROGRAM_PAYLOAD_BYTES = 16_384
MAX_PROGRAM_CANDIDATES = 128
MAX_PROGRAM_ABSOLUTE_VALUE = Decimal("1e30")
PROGRAM_DECIMAL_PRECISION = 50
_OPERATIONS = {
    "ADD",
    "SUB",
    "MUL",
    "DIV",
    "PERCENT_CHANGE",
    "RATIO",
    "AVERAGE",
}

_EXTRACTION_CONFIG = {
    "candidate_id_hex_chars": 20,
    "max_absolute_value": "1e30",
    "max_candidates_per_source": MAX_CANDIDATES_PER_SOURCE,
    "max_source_text_chars": MAX_SOURCE_TEXT_CHARS,
    "period_year_max": 2100,
    "period_year_min": 1900,
    "version": EXTRACTION_VERSION,
}
EXTRACTION_CONFIG_SHA256 = hashlib.sha256(
    json.dumps(
        _EXTRACTION_CONFIG,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
).hexdigest()

_CURRENCY_UNIT = {
    "$": "usd",
    "usd": "usd",
    "€": "eur",
    "eur": "eur",
    "£": "gbp",
    "gbp": "gbp",
    "¥": "cny",
    "cny": "cny",
    "rmb": "cny",
}
_SCALE_MULTIPLIER = {
    "one": Decimal("1"),
    "thousand": Decimal("1000"),
    "million": Decimal("1000000"),
    "billion": Decimal("1000000000"),
    "trillion": Decimal("1000000000000"),
}
_SCALE_ALIASES = {
    "k": "thousand",
    "thousand": "thousand",
    "thousands": "thousand",
    "m": "million",
    "mn": "million",
    "million": "million",
    "millions": "million",
    "b": "billion",
    "bn": "billion",
    "billion": "billion",
    "billions": "billion",
    "trillion": "trillion",
    "trillions": "trillion",
}
_CURRENCY_TOKEN = r"(?:USD|EUR|GBP|CNY|RMB|[$€£¥])"
_PREFIX_TOKEN = rf"(?:(?:{_CURRENCY_TOKEN}|[+-])(?:[ \t]*(?:{_CURRENCY_TOKEN}|[+-]))?[ \t]*)?"
_NUMBER_TOKEN = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+"
_SUFFIX_TOKEN = (
    r"(?:basis[ \t]+points?|bps|percent|per[ \t]+cent|%|"
    r"thousands?|millions?|billions?|trillions?|mn|bn|k|m|b)"
)
_NUMERIC_PATTERN = re.compile(
    rf"(?<![\w.,])(?:"
    rf"(?P<parenthesized>\([ \t]*(?P<p_prefix>{_PREFIX_TOKEN})"
    rf"(?P<p_number>{_NUMBER_TOKEN})(?:[ \t]*(?P<p_suffix>{_SUFFIX_TOKEN}))?[ \t]*\))"
    rf"|(?P<plain>(?P<n_prefix>{_PREFIX_TOKEN})(?P<n_number>{_NUMBER_TOKEN})"
    rf"(?:[ \t]*(?P<n_suffix>{_SUFFIX_TOKEN}))?))"
    rf"(?!\w|\.(?=\d)|,(?=\d))",
    re.IGNORECASE,
)
_ORDINAL_PATTERN = re.compile(
    r"(?<![\w.])(?P<number>\d+)(?:st|nd|rd|th)(?!\w)",
    re.IGNORECASE,
)
_YEAR_PATTERN = re.compile(r"(?<!\d)(?P<year>(?:19|20)\d{2})(?!\d)")
_HEADER_SCALE_PATTERN = re.compile(
    r"\b(?:in|amounts?[ \t]+in)?[ \t]*"
    r"(?P<scale>thousands?|millions?|billions?|trillions?)\b",
    re.IGNORECASE,
)
_HEADER_YEAR_PATTERN = re.compile(
    r"(?<!\d)(?:fy|fiscal[ \t]+year[ \t]*)?(?P<year>(?:19|20)\d{2})(?!\d)",
    re.IGNORECASE,
)
_PAGE_CONTEXT_PATTERN = re.compile(r"\b(?:page|pg|p\.)[ \t]*$", re.IGNORECASE)
_ORDINAL_CONTEXT_PATTERN = re.compile(
    r"\b(?:footnote|note|section|appendix|item)[ \t]*$",
    re.IGNORECASE,
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class _FrozenMapping(Mapping[str, Decimal]):
    __slots__ = ("_data",)

    def __init__(self, values: Mapping[str, Decimal]) -> None:
        self._data = MappingProxyType(dict(values))

    def __getitem__(self, key: str) -> Decimal:
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __deepcopy__(self, _memo):
        return self


class ProvenanceSpan(_StrictFrozenModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_range(self) -> ProvenanceSpan:
        if self.end <= self.start:
            raise ValueError("provenance end must be greater than start")
        return self


class NumericCandidate(_StrictFrozenModel):
    candidate_id: str = Field(pattern=r"^num-[0-9a-f]{20}$")
    raw_text: str = Field(min_length=1, max_length=256)
    normalized_value: Decimal
    metric: str | None = None
    entity: str | None = None
    period: str | None = None
    fiscal_year: int | None = Field(default=None, ge=1900, le=2100)
    unit: FinancialUnit
    scale: FinancialScale
    sign: Literal[-1, 0, 1]
    source_id: str = Field(min_length=1, max_length=512)
    evidence_id: str = Field(min_length=1, max_length=512)
    source_kind: SourceKind = "text"
    table_id: str | None = Field(default=None, max_length=512)
    row_header: str | None = Field(default=None, max_length=512)
    column_header: str | None = Field(default=None, max_length=512)
    provenance_span: ProvenanceSpan
    role: CandidateRole
    extraction_version: Literal["finqa_numeric_candidate_v1"] = EXTRACTION_VERSION

    @model_validator(mode="after")
    def validate_candidate(self) -> NumericCandidate:
        expected_sign = (
            -1
            if self.normalized_value < 0
            else (1 if self.normalized_value > 0 else 0)
        )
        if self.sign != expected_sign:
            raise ValueError("candidate sign does not match normalized value")
        if abs(self.normalized_value) > MAX_ABSOLUTE_VALUE:
            raise ValueError("candidate exceeds the numeric magnitude budget")
        if self.provenance_span.end - self.provenance_span.start != len(
            self.raw_text
        ):
            raise ValueError("candidate raw text length does not match provenance")
        expected_hash = hashlib.sha256(self.raw_text.encode("utf-8")).hexdigest()
        if self.provenance_span.text_sha256 != expected_hash:
            raise ValueError("candidate raw text does not match provenance hash")
        if self.source_kind == "table_cell" and self.table_id is None:
            raise ValueError("table-cell candidate requires table_id")
        return self


class NumericCandidateSource(_StrictFrozenModel):
    source_id: str = Field(min_length=1, max_length=512)
    evidence_id: str = Field(min_length=1, max_length=512)
    text: str = Field(min_length=1, max_length=MAX_SOURCE_TEXT_CHARS)
    kind: SourceKind
    table_id: str | None = Field(default=None, max_length=512)
    row_header: str | None = Field(default=None, max_length=512)
    column_header: str | None = Field(default=None, max_length=512)
    unit_hint: FinancialUnit | None = None

    @model_validator(mode="after")
    def validate_table_source(self) -> NumericCandidateSource:
        if self.kind == "table_cell" and self.table_id is None:
            raise ValueError("table-cell source requires table_id")
        return self


class NumericCandidateCorpus(_StrictFrozenModel):
    extraction_version: Literal["finqa_numeric_candidate_v1"] = EXTRACTION_VERSION
    candidates: tuple[NumericCandidate, ...]
    rejected_noise_counts: dict[str, int]


class NumericCandidateManifest(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_numeric_candidate_manifest_v1"
    ] = CANDIDATE_MANIFEST_VERSION
    status: Literal["SYNTHETIC_CONTRACT_ONLY", "PRIVATE_DATASET_RUN"]
    extraction_version: Literal["finqa_numeric_candidate_v1"] = EXTRACTION_VERSION
    extraction_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extractor_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_record_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    candidate_id_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    counts_by_source_kind: dict[str, int]
    counts_by_role: dict[str, int]
    counts_by_unit: dict[str, int]
    counts_by_scale: dict[str, int]
    rejected_noise_counts: dict[str, int]
    missing_metadata_counts: dict[str, int]


class FinancialQuestionIntent(_StrictFrozenModel):
    operation_intent: TypedFinancialOperation
    metric: str | None = Field(default=None, max_length=512)
    entity: str | None = Field(default=None, max_length=512)
    target_period: str | None = Field(default=None, max_length=128)
    start_period: str | None = Field(default=None, max_length=128)
    end_period: str | None = Field(default=None, max_length=128)
    requested_unit: FinancialUnit
    requested_scale: FinancialScale
    direction: Literal[
        "new_over_old",
        "old_over_new",
        "part_over_total",
        "none",
    ]
    intent_version: Literal[
        "finqa_financial_question_intent_v1"
    ] = "finqa_financial_question_intent_v1"

    @model_validator(mode="after")
    def validate_period_contract(self) -> FinancialQuestionIntent:
        if (self.start_period is None) != (self.end_period is None):
            raise ValueError("start_period and end_period must be provided together")
        if self.target_period is not None and self.start_period is not None:
            raise ValueError(
                "target_period cannot be combined with start/end periods"
            )
        return self


class TypedProgramValidationError(ValueError):
    def __init__(self, reason: FailureReason, message: str) -> None:
        self.reason = reason
        super().__init__(message)


class CandidateRef(_StrictFrozenModel):
    candidate_id: str = Field(pattern=r"^num-[0-9a-f]{20}$")


class StepRef(_StrictFrozenModel):
    step_id: str = Field(pattern=r"^step-0[1-8]$")


OperandRef = CandidateRef | StepRef


class TypedProgramStep(_StrictFrozenModel):
    step_id: str = Field(pattern=r"^step-0[1-8]$")
    operation: TypedFinancialOperation
    arguments: tuple[OperandRef, ...] = Field(
        min_length=2,
        max_length=MAX_PROGRAM_ARGUMENTS,
    )


class TypedProgram(_StrictFrozenModel):
    dsl_version: Literal[
        "finqa_typed_financial_dsl_v1"
    ] = DSL_VERSION
    steps: tuple[TypedProgramStep, ...] = Field(
        min_length=1,
        max_length=MAX_PROGRAM_STEPS,
    )
    output_step_id: str = Field(pattern=r"^step-0[1-8]$")


class ValidatedTypedProgram(_StrictFrozenModel):
    program: TypedProgram
    candidate_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    validation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validator_version: Literal[
        "finqa_typed_program_validator_v1"
    ] = VALIDATOR_VERSION


class TypedProgramDiagnostics(_StrictFrozenModel):
    validation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    step_count: int = Field(ge=1, le=MAX_PROGRAM_STEPS)
    candidate_count: int = Field(ge=1, le=MAX_PROGRAM_CANDIDATES)
    evidence_count: int = Field(ge=1, le=MAX_PROGRAM_CANDIDATES)
    decimal_precision: Literal[50] = PROGRAM_DECIMAL_PRECISION
    warnings: tuple[str, ...] = ()


class TypedProgramResult(_StrictFrozenModel):
    value: Decimal
    unit: FinancialUnit
    output_step_id: str = Field(pattern=r"^step-0[1-8]$")
    step_values: Mapping[str, Decimal]
    candidate_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    program_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    diagnostics: TypedProgramDiagnostics
    validator_version: Literal[
        "finqa_typed_program_validator_v1"
    ] = VALIDATOR_VERSION
    compiler_version: Literal[
        "finqa_typed_program_compiler_v1"
    ] = COMPILER_VERSION

    @field_validator("step_values")
    @classmethod
    def validate_step_values(
        cls,
        value: Mapping[str, Decimal],
    ) -> Mapping[str, Decimal]:
        if not value or any(
            not re.fullmatch(r"step-0[1-8]", step_id)
            for step_id in value
        ):
            raise ValueError("step values contain an invalid step ID")
        return _FrozenMapping(value)

    @field_serializer("step_values")
    def serialize_step_values(
        self,
        value: Mapping[str, Decimal],
    ) -> dict[str, Decimal]:
        return dict(value)


def _canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _normalized_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _validate_identifier(value: str, label: str) -> str:
    normalized = _normalized_optional_text(value)
    if normalized is None:
        raise ValueError(f"{label} must not be blank")
    if len(normalized) > 512:
        raise ValueError(f"{label} exceeds 512 characters")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{label} contains control characters")
    return normalized


def _extract_currency(prefix: str) -> FinancialUnit | None:
    matches = [
        _CURRENCY_UNIT[token.casefold()]
        for token in re.findall(_CURRENCY_TOKEN, prefix, flags=re.IGNORECASE)
    ]
    if len(matches) > 1:
        raise ValueError("numeric token contains multiple currency markers")
    return matches[0] if matches else None


def _extract_sign(prefix: str, *, parenthesized: bool) -> int:
    signs = re.findall(r"[+-]", prefix)
    if len(signs) > 1:
        raise ValueError("numeric token contains multiple signs")
    if parenthesized or signs == ["-"]:
        return -1
    return 1


def _scale_from_header(*headers: str | None) -> FinancialScale | None:
    scales: set[FinancialScale] = set()
    for header in headers:
        if header is None:
            continue
        match = _HEADER_SCALE_PATTERN.search(header)
        if match:
            scales.add(_SCALE_ALIASES[match.group("scale").casefold()])
    if len(scales) > 1:
        raise ValueError("table headers contain contradictory scale hints")
    return next(iter(scales), None)


def _classify_suffix(
    suffix: str | None,
    *,
    header_scale: FinancialScale | None,
) -> tuple[FinancialScale, Decimal, FinancialUnit | None]:
    if suffix is None:
        scale = header_scale or "one"
        return scale, _SCALE_MULTIPLIER[scale], None
    normalized = " ".join(suffix.casefold().split())
    if normalized in {"%", "percent", "per cent"}:
        if header_scale not in {None, "percent"}:
            raise ValueError("numeric suffix contradicts table scale")
        return "percent", Decimal("0.01"), "ratio"
    if normalized in {"bps", "basis point", "basis points"}:
        if header_scale not in {None, "basis_point"}:
            raise ValueError("numeric suffix contradicts table scale")
        return "basis_point", Decimal("0.0001"), "ratio"
    scale = _SCALE_ALIASES[normalized]
    if header_scale is not None and header_scale != scale:
        raise ValueError("numeric suffix contradicts table scale")
    return scale, _SCALE_MULTIPLIER[scale], None


def _period_from_header(column_header: str | None) -> tuple[str | None, int | None]:
    if column_header is None:
        return None, None
    match = _HEADER_YEAR_PATTERN.search(column_header)
    if match is None:
        return None, None
    year = int(match.group("year"))
    return str(year), year


def _clause_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    left = max(text.rfind(separator, 0, start) for separator in (";", "\n", "."))
    right_candidates = [
        position
        for separator in (";", "\n", ".")
        if (position := text.find(separator, end)) >= 0
    ]
    return left + 1, min(right_candidates, default=len(text))


def _period_from_text(
    text: str,
    *,
    start: int,
    end: int,
) -> tuple[str | None, int | None]:
    clause_start, clause_end = _clause_bounds(text, start, end)
    years = {
        int(match.group("year"))
        for match in _YEAR_PATTERN.finditer(text, clause_start, clause_end)
    }
    if len(years) != 1:
        return None, None
    year = next(iter(years))
    return str(year), year


def _context_role(
    text: str,
    *,
    start: int,
    end: int,
    normalized_value: Decimal,
    has_financial_marker: bool,
) -> CandidateRole:
    if not has_financial_marker and normalized_value == normalized_value.to_integral():
        integer = int(normalized_value)
        if 1900 <= integer <= 2100:
            return "period_label"
    prefix = text[max(0, start - 32) : start]
    if _PAGE_CONTEXT_PATTERN.search(prefix):
        return "page_number"
    if _ORDINAL_CONTEXT_PATTERN.search(prefix):
        return "ordinal"
    line_prefix = text[text.rfind("\n", 0, start) + 1 : start]
    suffix = text[end : min(len(text), end + 1)]
    if not line_prefix.strip() and suffix in {".", ")"}:
        return "ordinal"
    if start > 0 and end < len(text) and text[start - 1] == "[" and text[end] == "]":
        return "ordinal"
    return "operand"


def _candidate_identity(
    *,
    source_id: str,
    evidence_id: str,
    source_kind: SourceKind,
    table_id: str | None,
    row_header: str | None,
    column_header: str | None,
    provenance_span: ProvenanceSpan,
    normalized_value: Decimal,
    unit: FinancialUnit,
    scale: FinancialScale,
    sign: int,
    role: CandidateRole,
) -> str:
    payload = {
        "column_header": column_header,
        "evidence_id": evidence_id,
        "extraction_version": EXTRACTION_VERSION,
        "normalized_value": _canonical_decimal(normalized_value),
        "provenance": provenance_span.model_dump(mode="json"),
        "role": role,
        "row_header": row_header,
        "scale": scale,
        "sign": sign,
        "source_id": source_id,
        "source_kind": source_kind,
        "table_id": table_id,
        "unit": unit,
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return f"num-{digest[:20]}"


def _build_candidate(
    *,
    source_id: str,
    evidence_id: str,
    text: str,
    kind: SourceKind,
    start: int,
    end: int,
    number_text: str,
    prefix: str,
    suffix: str | None,
    parenthesized: bool,
    table_id: str | None,
    row_header: str | None,
    column_header: str | None,
    unit_hint: FinancialUnit | None,
    forced_role: CandidateRole | None = None,
) -> NumericCandidate:
    raw_text = text[start:end]
    try:
        unsigned_value = Decimal(number_text.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError("numeric token is not a valid Decimal") from exc
    sign_multiplier = _extract_sign(prefix, parenthesized=parenthesized)
    explicit_unit = _extract_currency(prefix)
    header_scale = _scale_from_header(row_header, column_header)
    scale, multiplier, suffix_unit = _classify_suffix(
        suffix,
        header_scale=header_scale,
    )
    inferred_unit = suffix_unit or explicit_unit
    if unit_hint is not None and inferred_unit is not None and unit_hint != inferred_unit:
        raise ValueError("numeric token contradicts the provided unit hint")
    unit: FinancialUnit = inferred_unit or unit_hint or "unknown"
    normalized_value = unsigned_value * multiplier * sign_multiplier
    if normalized_value == 0:
        normalized_value = Decimal("0")
    has_financial_marker = bool(prefix.strip() or suffix or unit_hint)
    role = forced_role or _context_role(
        text,
        start=start,
        end=end,
        normalized_value=normalized_value,
        has_financial_marker=has_financial_marker,
    )
    period, fiscal_year = _period_from_header(column_header)
    if role == "period_label":
        fiscal_year = int(unsigned_value)
        period = str(fiscal_year)
    elif period is None:
        period, fiscal_year = _period_from_text(text, start=start, end=end)
    provenance_span = ProvenanceSpan(
        start=start,
        end=end,
        text_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )
    metric = _normalized_optional_text(row_header)
    normalized_table_id = _normalized_optional_text(table_id)
    normalized_column_header = _normalized_optional_text(column_header)
    candidate_id = _candidate_identity(
        source_id=source_id,
        evidence_id=evidence_id,
        source_kind=kind,
        table_id=normalized_table_id,
        row_header=metric,
        column_header=normalized_column_header,
        provenance_span=provenance_span,
        normalized_value=normalized_value,
        unit=unit,
        scale=scale,
        sign=(
            -1
            if normalized_value < 0
            else (1 if normalized_value > 0 else 0)
        ),
        role=role,
    )
    return NumericCandidate(
        candidate_id=candidate_id,
        raw_text=raw_text,
        normalized_value=normalized_value,
        metric=metric,
        entity=None,
        period=period,
        fiscal_year=fiscal_year,
        unit=unit,
        scale=scale,
        sign=-1 if normalized_value < 0 else (1 if normalized_value > 0 else 0),
        source_id=source_id,
        evidence_id=evidence_id,
        source_kind=kind,
        table_id=normalized_table_id,
        row_header=metric,
        column_header=normalized_column_header,
        provenance_span=provenance_span,
        role=role,
    )


def extract_numeric_candidate_corpus(
    sources: tuple[NumericCandidateSource, ...] | list[NumericCandidateSource],
) -> NumericCandidateCorpus:
    candidates: list[NumericCandidate] = []
    rejected = Counter[str]()
    for source in sources:
        batch = _extract_numeric_candidate_batch(**source.model_dump())
        candidates.extend(batch.candidates)
        rejected.update(batch.rejected_noise_counts)
    candidate_ids = [candidate.candidate_id for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("numeric candidate IDs must be unique within a corpus")
    return NumericCandidateCorpus(
        candidates=tuple(candidates),
        rejected_noise_counts=dict(sorted(rejected.items())),
    )


def build_finqa_numeric_sources(
    case: FinQACase,
    *,
    admitted_evidence_ids: set[str] | None = None,
) -> tuple[NumericCandidateSource, ...]:
    text_rows = [
        (f"text_{index}", text)
        for index, text in enumerate([*case.pre_text, *case.post_text])
        if text.strip()
    ]
    table_row_ids = {
        f"table_{row_index}" for row_index in range(len(case.table))
    }
    known_evidence_ids = {
        evidence_id for evidence_id, _ in text_rows
    } | table_row_ids
    admitted = (
        known_evidence_ids
        if admitted_evidence_ids is None
        else set(admitted_evidence_ids)
    )
    unknown = admitted - known_evidence_ids
    if unknown:
        raise ValueError(
            "admitted FinQA evidence IDs are not present in the case: "
            + ", ".join(sorted(unknown))
        )

    sources = [
        NumericCandidateSource(
            source_id=case.filename,
            evidence_id=evidence_id,
            text=text,
            kind="text",
        )
        for evidence_id, text in text_rows
        if evidence_id in admitted
    ]
    header = case.table[0]
    for row_index, row in enumerate(case.table[1:], start=1):
        evidence_id = f"table_{row_index}"
        if evidence_id not in admitted:
            continue
        row_header = row[0]
        for column_index, cell in enumerate(row[1:], start=1):
            if not cell.strip():
                continue
            sources.append(
                NumericCandidateSource(
                    source_id=case.filename,
                    evidence_id=evidence_id,
                    text=cell,
                    kind="table_cell",
                    table_id="table-main",
                    row_header=row_header,
                    column_header=header[column_index],
                )
            )
    return tuple(sources)


def extract_finqa_numeric_candidates(
    case: FinQACase,
    *,
    admitted_evidence_ids: set[str] | None = None,
) -> NumericCandidateCorpus:
    return extract_numeric_candidate_corpus(
        build_finqa_numeric_sources(
            case,
            admitted_evidence_ids=admitted_evidence_ids,
        )
    )


def _extract_numeric_candidate_batch(
    *,
    source_id: str,
    evidence_id: str,
    text: str,
    kind: SourceKind,
    table_id: str | None = None,
    row_header: str | None = None,
    column_header: str | None = None,
    unit_hint: FinancialUnit | None = None,
) -> NumericCandidateCorpus:
    source_id = _validate_identifier(source_id, "source_id")
    evidence_id = _validate_identifier(evidence_id, "evidence_id")
    if not text or len(text) > MAX_SOURCE_TEXT_CHARS:
        raise ValueError(
            f"text must contain 1-{MAX_SOURCE_TEXT_CHARS} characters"
        )
    if kind == "table_cell" and _normalized_optional_text(table_id) is None:
        raise ValueError("table-cell extraction requires table_id")

    candidates: list[NumericCandidate] = []
    occupied_spans: set[tuple[int, int]] = set()
    for match in _NUMERIC_PATTERN.finditer(text):
        parenthesized = match.group("parenthesized") is not None
        prefix = match.group("p_prefix" if parenthesized else "n_prefix") or ""
        number_text = match.group("p_number" if parenthesized else "n_number")
        suffix = match.group("p_suffix" if parenthesized else "n_suffix")
        candidate = _build_candidate(
            source_id=source_id,
            evidence_id=evidence_id,
            text=text,
            kind=kind,
            start=match.start(),
            end=match.end(),
            number_text=number_text,
            prefix=prefix,
            suffix=suffix,
            parenthesized=parenthesized,
            table_id=table_id,
            row_header=row_header,
            column_header=column_header,
            unit_hint=unit_hint,
        )
        candidates.append(candidate)
        occupied_spans.add((match.start(), match.end()))

    for match in _ORDINAL_PATTERN.finditer(text):
        span = (match.start(), match.end())
        if span in occupied_spans:
            continue
        candidates.append(
            _build_candidate(
                source_id=source_id,
                evidence_id=evidence_id,
                text=text,
                kind=kind,
                start=match.start(),
                end=match.end(),
                number_text=match.group("number"),
                prefix="",
                suffix=None,
                parenthesized=False,
                table_id=table_id,
                row_header=row_header,
                column_header=column_header,
                unit_hint=None,
                forced_role="ordinal",
            )
        )
        occupied_spans.add(span)

    for match in _YEAR_PATTERN.finditer(text):
        span = (match.start(), match.end())
        if span in occupied_spans:
            continue
        candidates.append(
            _build_candidate(
                source_id=source_id,
                evidence_id=evidence_id,
                text=text,
                kind=kind,
                start=match.start(),
                end=match.end(),
                number_text=match.group("year"),
                prefix="",
                suffix=None,
                parenthesized=False,
                table_id=table_id,
                row_header=row_header,
                column_header=column_header,
                unit_hint=None,
                forced_role="period_label",
            )
        )
        occupied_spans.add(span)

    candidates.sort(
        key=lambda candidate: (
            candidate.provenance_span.start,
            candidate.provenance_span.end,
            candidate.candidate_id,
        )
    )
    if len(candidates) > MAX_CANDIDATES_PER_SOURCE:
        raise ValueError("numeric candidate count exceeds the source budget")
    rejected = Counter(
        f"non_operand_{candidate.role}"
        for candidate in candidates
        if candidate.role in {"ordinal", "page_number"}
    )
    return NumericCandidateCorpus(
        candidates=tuple(candidates),
        rejected_noise_counts=dict(sorted(rejected.items())),
    )


def extract_numeric_candidates(
    source_id: str,
    evidence_id: str,
    text: str,
    kind: SourceKind,
    table_id: str | None = None,
    row_header: str | None = None,
    column_header: str | None = None,
    unit_hint: FinancialUnit | None = None,
) -> tuple[NumericCandidate, ...]:
    return _extract_numeric_candidate_batch(
        source_id=source_id,
        evidence_id=evidence_id,
        text=text,
        kind=kind,
        table_id=table_id,
        row_header=row_header,
        column_header=column_header,
        unit_hint=unit_hint,
    ).candidates


def build_numeric_candidate_manifest(
    *,
    corpus: NumericCandidateCorpus,
    source_artifact_sha256: str,
    extractor_source_sha256: str,
    source_record_count: int,
    status: Literal[
        "SYNTHETIC_CONTRACT_ONLY",
        "PRIVATE_DATASET_RUN",
    ] = "SYNTHETIC_CONTRACT_ONLY",
) -> NumericCandidateManifest:
    if not re.fullmatch(r"[0-9a-f]{64}", source_artifact_sha256):
        raise ValueError("source artifact SHA-256 must be lowercase hexadecimal")
    if not re.fullmatch(r"[0-9a-f]{64}", extractor_source_sha256):
        raise ValueError("extractor source SHA-256 must be lowercase hexadecimal")
    if source_record_count < 0:
        raise ValueError("source record count must be non-negative")
    candidates = corpus.candidates
    candidate_ids = sorted(candidate.candidate_id for candidate in candidates)
    candidate_id_set_sha256 = hashlib.sha256(
        "\n".join(candidate_ids).encode("ascii")
    ).hexdigest()

    def counts(attribute: str) -> dict[str, int]:
        return dict(
            sorted(
                Counter(
                    str(getattr(candidate, attribute)) for candidate in candidates
                ).items()
            )
        )

    missing_metadata = {
        "column_header": sum(
            candidate.column_header is None for candidate in candidates
        ),
        "entity": sum(candidate.entity is None for candidate in candidates),
        "fiscal_year": sum(
            candidate.fiscal_year is None for candidate in candidates
        ),
        "metric": sum(candidate.metric is None for candidate in candidates),
        "period": sum(candidate.period is None for candidate in candidates),
        "row_header": sum(candidate.row_header is None for candidate in candidates),
        "scale_unknown": sum(
            candidate.scale == "unknown" for candidate in candidates
        ),
        "table_id": sum(candidate.table_id is None for candidate in candidates),
        "unit_unknown": sum(
            candidate.unit == "unknown" for candidate in candidates
        ),
    }
    return NumericCandidateManifest(
        status=status,
        extraction_config_sha256=EXTRACTION_CONFIG_SHA256,
        extractor_source_sha256=extractor_source_sha256,
        source_artifact_sha256=source_artifact_sha256,
        source_record_count=source_record_count,
        candidate_count=len(candidates),
        candidate_id_set_sha256=candidate_id_set_sha256,
        counts_by_source_kind=counts("source_kind"),
        counts_by_role=counts("role"),
        counts_by_unit=counts("unit"),
        counts_by_scale=counts("scale"),
        rejected_noise_counts=dict(sorted(corpus.rejected_noise_counts.items())),
        missing_metadata_counts=missing_metadata,
    )


@dataclass(frozen=True)
class _ValueState:
    value: Decimal
    unit: FinancialUnit
    metric: str | None
    entity: str | None
    periods: frozenset[str]
    candidate_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class _ValidatedExecution:
    validated: ValidatedTypedProgram
    step_states: dict[str, _ValueState]


def _raise_validation(
    reason: FailureReason,
    message: str,
) -> None:
    raise TypedProgramValidationError(reason, message)


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _ordered_unique(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _argument_contains_literal(argument: object) -> bool:
    if isinstance(argument, (bool, int, float, Decimal)):
        return True
    if isinstance(argument, str):
        return bool(re.fullmatch(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)", argument))
    if not isinstance(argument, dict):
        return False
    if set(argument).intersection({"literal", "value", "expression", "number"}):
        return True
    return any(
        isinstance(value, (bool, int, float, Decimal))
        for value in argument.values()
    )


def _parse_typed_program(planner_payload: object) -> TypedProgram:
    if isinstance(planner_payload, TypedProgram):
        return planner_payload
    try:
        payload_bytes = _canonical_json_bytes(planner_payload)
    except (TypeError, ValueError) as exc:
        _raise_validation(
            "invalid_program_schema",
            "planner payload is not canonical JSON",
        )
        raise AssertionError from exc
    if len(payload_bytes) > MAX_PROGRAM_PAYLOAD_BYTES:
        _raise_validation(
            "budget_exceeded",
            "planner payload exceeds the byte budget",
        )
    if not isinstance(planner_payload, dict):
        _raise_validation(
            "invalid_program_schema",
            "planner payload must be an object",
        )
    steps = planner_payload.get("steps")
    if not isinstance(steps, (list, tuple)):
        _raise_validation(
            "invalid_program_schema",
            "planner payload must contain a step list",
        )
    if len(steps) > MAX_PROGRAM_STEPS:
        _raise_validation("budget_exceeded", "program has too many steps")
    if not steps:
        _raise_validation("invalid_program_schema", "program has no steps")
    for step in steps:
        if not isinstance(step, dict):
            _raise_validation(
                "invalid_program_schema",
                "each program step must be an object",
            )
        operation = step.get("operation")
        if operation not in _OPERATIONS:
            _raise_validation(
                "unsupported_operation",
                "program contains an unsupported operation",
            )
        arguments = step.get("arguments")
        if not isinstance(arguments, (list, tuple)):
            _raise_validation(
                "invalid_arity",
                "program step arguments must be a list",
            )
        if len(arguments) > MAX_PROGRAM_ARGUMENTS:
            _raise_validation(
                "budget_exceeded",
                "program step has too many arguments",
            )
        if not 2 <= len(arguments) <= MAX_PROGRAM_ARGUMENTS:
            _raise_validation(
                "invalid_arity",
                "program operation has invalid arity",
            )
        if any(_argument_contains_literal(argument) for argument in arguments):
            _raise_validation(
                "literal_only_operand",
                "program arguments must reference candidates or previous steps",
            )
    try:
        return TypedProgram.model_validate(planner_payload)
    except ValidationError as exc:
        if "output_step_id" not in planner_payload:
            _raise_validation(
                "missing_output_step",
                "program does not declare an output step",
            )
        _raise_validation(
            "invalid_program_schema",
            "program does not match the typed DSL schema",
        )
        raise AssertionError from exc


def _validated_candidates(
    candidates: list[NumericCandidate] | tuple[NumericCandidate, ...],
) -> dict[str, NumericCandidate]:
    if len(candidates) > MAX_PROGRAM_CANDIDATES:
        _raise_validation(
            "budget_exceeded",
            "candidate set exceeds the validator budget",
        )
    by_id: dict[str, NumericCandidate] = {}
    identity_fingerprints: set[bytes] = set()
    for candidate in candidates:
        try:
            expected_sign = (
                -1
                if candidate.normalized_value < 0
                else (1 if candidate.normalized_value > 0 else 0)
            )
            if candidate.sign != expected_sign:
                _raise_validation(
                    "sign_mismatch",
                    "candidate sign is inconsistent with its value",
                )
            raw_text = candidate.raw_text
            provenance = candidate.provenance_span
            if (
                provenance.end - provenance.start != len(raw_text)
                or provenance.text_sha256
                != hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
            ):
                _raise_validation(
                    "missing_provenance",
                    "candidate provenance is invalid",
                )
        except AttributeError as exc:
            _raise_validation(
                "missing_provenance",
                "candidate provenance is missing",
            )
            raise AssertionError from exc
        try:
            checked = NumericCandidate.model_validate(
                candidate.model_dump(mode="python")
            )
        except (AttributeError, ValidationError, ValueError) as exc:
            _raise_validation(
                "missing_provenance",
                "candidate provenance is invalid",
            )
            raise AssertionError from exc
        try:
            reconstructed = extract_numeric_candidates(
                source_id=checked.source_id,
                evidence_id=checked.evidence_id,
                text=checked.raw_text,
                kind=checked.source_kind,
                table_id=checked.table_id,
                row_header=checked.row_header,
                column_header=checked.column_header,
                unit_hint=(
                    None if checked.unit == "unknown" else checked.unit
                ),
            )
        except ValueError as exc:
            _raise_validation(
                "missing_provenance",
                "candidate value cannot be reconstructed from source text",
            )
            raise AssertionError from exc
        reconstructed_exact = next(
            (
                item
                for item in reconstructed
                if item.provenance_span.start == 0
                and item.provenance_span.end == len(checked.raw_text)
            ),
            None,
        )
        if reconstructed_exact is None:
            _raise_validation(
                "missing_provenance",
                "candidate value is not bound to the complete source span",
            )
        if reconstructed_exact.normalized_value != checked.normalized_value:
            _raise_validation(
                "missing_provenance",
                "candidate normalized value does not match source text",
            )
        if reconstructed_exact.unit != checked.unit:
            _raise_validation(
                "unit_mismatch",
                "candidate unit does not match source text",
            )
        if reconstructed_exact.scale != checked.scale:
            _raise_validation(
                "scale_mismatch",
                "candidate scale does not match source text",
            )
        if reconstructed_exact.sign != checked.sign:
            _raise_validation(
                "sign_mismatch",
                "candidate sign does not match source text",
            )
        identity_fingerprint = _canonical_json_bytes(
            {
                "column_header": checked.column_header,
                "evidence_id": checked.evidence_id,
                "normalized_value": _canonical_decimal(
                    checked.normalized_value
                ),
                "provenance_span": checked.provenance_span.model_dump(
                    mode="json"
                ),
                "role": checked.role,
                "row_header": checked.row_header,
                "scale": checked.scale,
                "sign": checked.sign,
                "source_id": checked.source_id,
                "source_kind": checked.source_kind,
                "table_id": checked.table_id,
                "unit": checked.unit,
            }
        )
        if identity_fingerprint in identity_fingerprints:
            _raise_validation(
                "duplicate_candidate",
                "candidate set contains duplicate source identities",
            )
        identity_fingerprints.add(identity_fingerprint)
        expected_candidate_id = _candidate_identity(
            source_id=checked.source_id,
            evidence_id=checked.evidence_id,
            source_kind=checked.source_kind,
            table_id=checked.table_id,
            row_header=checked.row_header,
            column_header=checked.column_header,
            provenance_span=checked.provenance_span,
            normalized_value=checked.normalized_value,
            unit=checked.unit,
            scale=checked.scale,
            sign=checked.sign,
            role=checked.role,
        )
        if checked.candidate_id != expected_candidate_id:
            _raise_validation(
                "missing_provenance",
                "candidate ID is not bound to its canonical source identity",
            )
        if checked.candidate_id in by_id:
            _raise_validation(
                "duplicate_candidate",
                "candidate set contains duplicate IDs",
            )
        by_id[checked.candidate_id] = checked
    return by_id


def _static_program_closure(
    program: TypedProgram,
    candidate_by_id: dict[str, NumericCandidate],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    seen_steps: set[str] = set()
    candidate_ids: list[str] = []
    evidence_ids: list[str] = []
    for ordinal, step in enumerate(program.steps, start=1):
        if step.step_id in seen_steps:
            _raise_validation(
                "duplicate_step_id",
                "program contains a duplicate step ID",
            )
        if step.step_id != f"step-{ordinal:02d}":
            _raise_validation(
                "invalid_program_schema",
                "step IDs must be contiguous and ordered",
            )
        for argument in step.arguments:
            if isinstance(argument, StepRef):
                if argument.step_id not in seen_steps:
                    _raise_validation(
                        "forward_step_reference",
                        "step reference must point to an earlier step",
                    )
                continue
            candidate = candidate_by_id.get(argument.candidate_id)
            if candidate is None:
                _raise_validation(
                    "missing_candidate",
                    "program references an unknown candidate",
                )
            candidate_ids.append(candidate.candidate_id)
            evidence_ids.append(candidate.evidence_id)
        seen_steps.add(step.step_id)
    if (
        program.output_step_id not in seen_steps
        or program.output_step_id != program.steps[-1].step_id
    ):
        _raise_validation(
            "missing_output_step",
            "output must reference the final completed step",
        )
    return _ordered_unique(candidate_ids), _ordered_unique(evidence_ids)


def _metadata_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(
        "".join(
            character if character.isalnum() else " "
            for character in value.casefold()
        ).split()
    )
    return normalized or None


def _candidate_period(candidate: NumericCandidate) -> str | None:
    if candidate.period is not None:
        return candidate.period.casefold().strip()
    if candidate.fiscal_year is not None:
        return str(candidate.fiscal_year)
    return None


def _validate_candidate_contracts(
    *,
    candidate_ids: tuple[str, ...],
    candidate_by_id: dict[str, NumericCandidate],
    admitted_evidence_ids: set[str],
    intent: FinancialQuestionIntent,
) -> None:
    if len(admitted_evidence_ids) > MAX_PROGRAM_CANDIDATES:
        _raise_validation(
            "budget_exceeded",
            "admitted evidence set exceeds the validator budget",
        )
    if any(
        not isinstance(evidence_id, str)
        or not evidence_id
        or len(evidence_id) > 512
        or any(ord(character) < 32 for character in evidence_id)
        for evidence_id in admitted_evidence_ids
    ):
        _raise_validation(
            "budget_exceeded",
            "admitted evidence identity violates the validator budget",
        )
    used = [candidate_by_id[candidate_id] for candidate_id in candidate_ids]
    for candidate in used:
        if candidate.evidence_id not in admitted_evidence_ids:
            _raise_validation(
                "unadmitted_source",
                "candidate is not from admitted evidence",
            )
        if candidate.role != "operand":
            _raise_validation(
                "invalid_candidate_role",
                "non-operand candidate cannot enter a program",
            )

    allowed_periods: set[str] | None = None
    if intent.target_period is not None:
        allowed_periods = {intent.target_period.casefold().strip()}
    elif intent.start_period is not None and intent.end_period is not None:
        allowed_periods = {
            intent.start_period.casefold().strip(),
            intent.end_period.casefold().strip(),
        }
    if allowed_periods is not None:
        for candidate in used:
            period = _candidate_period(candidate)
            if period is None:
                _raise_validation(
                    "ambiguous_intent",
                    "candidate period is unknown for a period-bound question",
                )
            if period not in allowed_periods:
                _raise_validation(
                    "temporal_mismatch",
                    "candidate period is incompatible with the question",
                )

    requested_metric = _metadata_key(intent.metric)
    if requested_metric is not None:
        for candidate in used:
            candidate_metric = _metadata_key(candidate.metric)
            if candidate_metric is None:
                _raise_validation(
                    "ambiguous_intent",
                    "candidate metric is unknown for a metric-bound question",
                )
            if candidate_metric != requested_metric:
                _raise_validation(
                    "metric_mismatch",
                    "candidate metric is incompatible with the question",
                )
    requested_entity = _metadata_key(intent.entity)
    if requested_entity is not None:
        for candidate in used:
            candidate_entity = _metadata_key(candidate.entity)
            if (
                candidate_entity is not None
                and candidate_entity != requested_entity
            ):
                _raise_validation(
                    "metric_mismatch",
                    "candidate entity is incompatible with the question",
                )
    for candidate in used:
        if candidate.scale == "unknown":
            _raise_validation(
                "scale_mismatch",
                "candidate scale is unknown",
            )
        expected_sign = (
            -1
            if candidate.normalized_value < 0
            else (1 if candidate.normalized_value > 0 else 0)
        )
        if candidate.sign != expected_sign:
            _raise_validation(
                "sign_mismatch",
                "candidate sign is inconsistent with its value",
            )


def _candidate_state(candidate: NumericCandidate) -> _ValueState:
    period = _candidate_period(candidate)
    return _ValueState(
        value=candidate.normalized_value,
        unit=candidate.unit,
        metric=candidate.metric,
        entity=candidate.entity,
        periods=frozenset(() if period is None else (period,)),
        candidate_ids=(candidate.candidate_id,),
        evidence_ids=(candidate.evidence_id,),
    )


def _same_metadata(
    states: tuple[_ValueState, ...],
    attribute: Literal["metric", "entity"],
) -> str | None:
    values = [getattr(state, attribute) for state in states]
    known = {
        key
        for value in values
        if (key := _metadata_key(value)) is not None
    }
    if len(known) > 1:
        _raise_validation(
            "metric_mismatch",
            f"operation arguments have incompatible {attribute}",
        )
    if known and any(value is None for value in values):
        _raise_validation(
            "ambiguous_intent",
            f"operation arguments have incomplete {attribute} metadata",
        )
    return next((value for value in values if value is not None), None)


def _shared_metadata(
    states: tuple[_ValueState, ...],
    attribute: Literal["metric", "entity"],
) -> str | None:
    known = [
        (value, _metadata_key(value))
        for state in states
        if (value := getattr(state, attribute)) is not None
    ]
    if len(known) != len(states):
        return None
    keys = {key for _, key in known if key is not None}
    if len(keys) != 1:
        return None
    return known[0][0]


def _same_unit(states: tuple[_ValueState, ...]) -> FinancialUnit:
    units = {state.unit for state in states}
    if len(units) != 1:
        _raise_validation(
            "unit_mismatch",
            "operation arguments have incompatible units",
        )
    return states[0].unit


def _validate_arity(
    operation: TypedFinancialOperation,
    argument_count: int,
) -> None:
    if operation == "AVERAGE":
        valid = 2 <= argument_count <= MAX_PROGRAM_ARGUMENTS
    else:
        valid = argument_count == 2
    if not valid:
        _raise_validation(
            "invalid_arity",
            "operation has an invalid argument count",
        )


def _validate_direction(
    *,
    operation: TypedFinancialOperation,
    states: tuple[_ValueState, ...],
    intent: FinancialQuestionIntent,
) -> None:
    if operation == "PERCENT_CHANGE" and intent.direction == "none":
        _raise_validation(
            "ambiguous_intent",
            "percent change requires an explicit direction",
        )
    if (
        intent.start_period is None
        or intent.end_period is None
        or intent.direction not in {"new_over_old", "old_over_new"}
        or operation not in {"SUB", "DIV", "PERCENT_CHANGE", "RATIO"}
    ):
        return
    start = intent.start_period.casefold().strip()
    end = intent.end_period.casefold().strip()
    expected = (
        (end, start)
        if intent.direction == "new_over_old"
        else (start, end)
    )
    actual: list[str] = []
    for state in states[:2]:
        if len(state.periods) != 1:
            _raise_validation(
                "ambiguous_intent",
                "directional operand has ambiguous period metadata",
            )
        actual.append(next(iter(state.periods)))
    if tuple(actual) != expected:
        _raise_validation(
            "direction_mismatch",
            "operand order is incompatible with the requested direction",
        )


def _merge_state(
    *,
    value: Decimal,
    unit: FinancialUnit,
    states: tuple[_ValueState, ...],
    metric: str | None,
    entity: str | None,
) -> _ValueState:
    if not value.is_finite() or abs(value) > MAX_PROGRAM_ABSOLUTE_VALUE:
        _raise_validation(
            "budget_exceeded",
            "program result exceeds the Decimal magnitude budget",
        )
    return _ValueState(
        value=value,
        unit=unit,
        metric=metric,
        entity=entity,
        periods=frozenset().union(*(state.periods for state in states)),
        candidate_ids=_ordered_unique(
            [
                candidate_id
                for state in states
                for candidate_id in state.candidate_ids
            ]
        ),
        evidence_ids=_ordered_unique(
            [
                evidence_id
                for state in states
                for evidence_id in state.evidence_ids
            ]
        ),
    )


def _execute_step(
    *,
    operation: TypedFinancialOperation,
    states: tuple[_ValueState, ...],
    intent: FinancialQuestionIntent,
) -> _ValueState:
    _validate_arity(operation, len(states))
    _validate_direction(operation=operation, states=states, intent=intent)
    metric: str | None = None
    entity: str | None = None
    if operation in {"ADD", "SUB", "PERCENT_CHANGE", "AVERAGE"}:
        metric = _same_metadata(states, "metric")
        entity = _same_metadata(states, "entity")
    values = tuple(state.value for state in states)
    if operation == "ADD":
        unit = _same_unit(states)
        value = values[0] + values[1]
    elif operation == "SUB":
        unit = _same_unit(states)
        value = values[0] - values[1]
    elif operation == "AVERAGE":
        unit = _same_unit(states)
        value = sum(values, start=Decimal("0")) / Decimal(len(values))
    elif operation == "PERCENT_CHANGE":
        _same_unit(states)
        if values[1] == 0:
            _raise_validation("divide_by_zero", "old value must not be zero")
        unit = "ratio"
        value = (values[0] - values[1]) / values[1]
    elif operation in {"DIV", "RATIO"}:
        if values[1] == 0:
            _raise_validation("divide_by_zero", "denominator must not be zero")
        if states[0].unit == states[1].unit:
            unit = "ratio"
            metric = _shared_metadata(states, "metric")
            entity = _shared_metadata(states, "entity")
        elif states[1].unit == "ratio":
            unit = states[0].unit
            metric = states[0].metric
            entity = states[0].entity
        else:
            _raise_validation(
                "unit_mismatch",
                "division arguments do not form an admitted unit ratio",
            )
        value = values[0] / values[1]
    else:
        left, right = states
        if left.unit == "ratio" and right.unit == "ratio":
            unit = "ratio"
        elif left.unit == "ratio":
            unit = right.unit
        elif right.unit == "ratio":
            unit = left.unit
        else:
            _raise_validation(
                "unit_mismatch",
                "multiplication requires at least one dimensionless argument",
            )
        value_states = tuple(
            state for state in states if state.unit != "ratio"
        )
        if len(value_states) == 1:
            metric = value_states[0].metric
            entity = value_states[0].entity
        else:
            metric = _shared_metadata(states, "metric")
            entity = _shared_metadata(states, "entity")
        value = values[0] * values[1]
    return _merge_state(
        value=value,
        unit=unit,
        states=states,
        metric=metric,
        entity=entity,
    )


def _validate_and_execute(
    *,
    planner_payload: object,
    candidates: list[NumericCandidate] | tuple[NumericCandidate, ...],
    admitted_evidence_ids: set[str],
    intent: FinancialQuestionIntent,
) -> _ValidatedExecution:
    try:
        intent = FinancialQuestionIntent.model_validate(
            intent.model_dump(mode="python")
        )
    except (AttributeError, ValidationError, ValueError) as exc:
        _raise_validation(
            "ambiguous_intent",
            "question intent does not satisfy its runtime contract",
        )
        raise AssertionError from exc
    program = _parse_typed_program(planner_payload)
    candidate_by_id = _validated_candidates(candidates)
    candidate_ids, evidence_ids = _static_program_closure(
        program,
        candidate_by_id,
    )
    _validate_candidate_contracts(
        candidate_ids=candidate_ids,
        candidate_by_id=candidate_by_id,
        admitted_evidence_ids=set(admitted_evidence_ids),
        intent=intent,
    )
    output_step = program.steps[-1]
    if output_step.operation != intent.operation_intent:
        _raise_validation(
            "unsupported_operation",
            "output operation does not match the question intent",
        )

    step_states: dict[str, _ValueState] = {}
    with localcontext() as decimal_context:
        decimal_context.prec = PROGRAM_DECIMAL_PRECISION
        for step in program.steps:
            argument_states = tuple(
                (
                    step_states[argument.step_id]
                    if isinstance(argument, StepRef)
                    else _candidate_state(
                        candidate_by_id[argument.candidate_id]
                    )
                )
                for argument in step.arguments
            )
            step_states[step.step_id] = _execute_step(
                operation=step.operation,
                states=argument_states,
                intent=intent,
            )
    output_state = step_states[program.output_step_id]
    if (
        intent.requested_unit != "unknown"
        and output_state.unit != intent.requested_unit
    ):
        _raise_validation(
            "unit_mismatch",
            "program output unit does not match the question intent",
        )
    if intent.requested_scale not in {"one", "unknown"}:
        _raise_validation(
            "scale_mismatch",
            "V1 compiler emits canonical base-unit results only",
        )
    validation_payload = {
        "admitted_evidence_ids": sorted(admitted_evidence_ids),
        "candidates": [
            candidate_by_id[candidate_id].model_dump(mode="json")
            for candidate_id in candidate_ids
        ],
        "intent": intent.model_dump(mode="json"),
        "program": program.model_dump(mode="json"),
        "validator_version": VALIDATOR_VERSION,
    }
    validated = ValidatedTypedProgram(
        program=program,
        candidate_ids=candidate_ids,
        evidence_ids=evidence_ids,
        validation_sha256=hashlib.sha256(
            _canonical_json_bytes(validation_payload)
        ).hexdigest(),
    )
    return _ValidatedExecution(validated=validated, step_states=step_states)


def validate_typed_program(
    *,
    planner_payload: object,
    candidates: list[NumericCandidate] | tuple[NumericCandidate, ...],
    admitted_evidence_ids: set[str],
    intent: FinancialQuestionIntent,
) -> ValidatedTypedProgram:
    return _validate_and_execute(
        planner_payload=planner_payload,
        candidates=candidates,
        admitted_evidence_ids=admitted_evidence_ids,
        intent=intent,
    ).validated


def compile_and_execute_typed_program(
    *,
    planner_payload: object,
    candidates: list[NumericCandidate] | tuple[NumericCandidate, ...],
    admitted_evidence_ids: set[str],
    intent: FinancialQuestionIntent,
) -> TypedProgramResult:
    execution = _validate_and_execute(
        planner_payload=planner_payload,
        candidates=candidates,
        admitted_evidence_ids=admitted_evidence_ids,
        intent=intent,
    )
    program = execution.validated.program
    output = execution.step_states[program.output_step_id]
    program_sha256 = hashlib.sha256(
        _canonical_json_bytes(program.model_dump(mode="json"))
    ).hexdigest()
    return TypedProgramResult(
        value=output.value,
        unit=output.unit,
        output_step_id=program.output_step_id,
        step_values={
            step.step_id: execution.step_states[step.step_id].value
            for step in program.steps
        },
        candidate_ids=output.candidate_ids,
        evidence_ids=output.evidence_ids,
        program_sha256=program_sha256,
        diagnostics=TypedProgramDiagnostics(
            validation_sha256=execution.validated.validation_sha256,
            step_count=len(program.steps),
            candidate_count=len(output.candidate_ids),
            evidence_count=len(output.evidence_ids),
        ),
    )


__all__ = [
    "CANDIDATE_MANIFEST_VERSION",
    "COMPILER_VERSION",
    "CandidateRef",
    "DSL_VERSION",
    "EXTRACTION_CONFIG_SHA256",
    "EXTRACTION_VERSION",
    "FinancialQuestionIntent",
    "NumericCandidate",
    "NumericCandidateCorpus",
    "NumericCandidateManifest",
    "NumericCandidateSource",
    "ProvenanceSpan",
    "StepRef",
    "TypedProgram",
    "TypedProgramDiagnostics",
    "TypedProgramResult",
    "TypedProgramStep",
    "TypedProgramValidationError",
    "VALIDATOR_VERSION",
    "ValidatedTypedProgram",
    "build_numeric_candidate_manifest",
    "build_finqa_numeric_sources",
    "compile_and_execute_typed_program",
    "extract_finqa_numeric_candidates",
    "extract_numeric_candidate_corpus",
    "extract_numeric_candidates",
    "validate_typed_program",
]
