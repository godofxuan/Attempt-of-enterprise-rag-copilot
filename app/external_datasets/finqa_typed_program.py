from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    operation_intent: str = Field(min_length=1, max_length=64)
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


class TypedProgramValidationError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


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


def compile_and_execute_typed_program(
    *args: object,
    **kwargs: object,
) -> None:
    raise NotImplementedError(
        "Gate C is not implemented: typed planner validation and execution "
        "remain outside the approved Gate B candidate-extraction scope"
    )


__all__ = [
    "CANDIDATE_MANIFEST_VERSION",
    "EXTRACTION_CONFIG_SHA256",
    "EXTRACTION_VERSION",
    "FinancialQuestionIntent",
    "NumericCandidate",
    "NumericCandidateCorpus",
    "NumericCandidateManifest",
    "NumericCandidateSource",
    "ProvenanceSpan",
    "TypedProgramValidationError",
    "build_numeric_candidate_manifest",
    "build_finqa_numeric_sources",
    "compile_and_execute_typed_program",
    "extract_finqa_numeric_candidates",
    "extract_numeric_candidate_corpus",
    "extract_numeric_candidates",
]
