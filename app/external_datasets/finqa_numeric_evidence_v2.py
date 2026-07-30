from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.retrieved_security import GuardDecision
from app.external_datasets.finqa import FinQACase, build_finqa_evidence_units
from app.external_datasets.finqa_typed_program import (
    FinancialUnit,
    NumericCandidate,
    NumericCandidateSource,
    extract_numeric_candidates,
)
from app.security.retrieved_content import RetrievedContentGuard


CLOSURE_VERSION = "finqa_numeric_evidence_closure_v2"
EXTRACTION_VERSION_V2 = "finqa_numeric_candidate_v2"
ClosureReason = Literal["table_parent", "text_neighbor"]
_SCALE_MULTIPLIER = {
    "one": Decimal("1"),
    "thousand": Decimal("1000"),
    "million": Decimal("1000000"),
    "billion": Decimal("1000000000"),
    "trillion": Decimal("1000000000000"),
    "percent": Decimal("0.01"),
    "basis_point": Decimal("0.0001"),
    "unknown": Decimal("1"),
}
_VALUE_BEARING_COLUMN_HEADER = re.compile(
    r"""
    ^\s*
    \(?\s*
    (?:[$€£¥]|USD|EUR|GBP)?\s*
    [-+]?\d[\d,]*(?:\.\d+)?
    \s*(?:%|bps?|thousands?|millions?|billions?|trillions?)?
    \s*\)?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class NumericEvidenceClosurePolicyV2(_StrictFrozenModel):
    max_added_evidence_units: int = Field(default=24, ge=0, le=64)
    max_total_evidence_units: int = Field(default=32, ge=1, le=64)
    max_total_evidence_chars: int = Field(default=8000, ge=1, le=64_000)
    text_neighbor_radius: int = Field(default=1, ge=0, le=5)
    expand_bounded_table_parent: bool = True

    @model_validator(mode="after")
    def validate_unit_budgets(self) -> NumericEvidenceClosurePolicyV2:
        if self.max_added_evidence_units > self.max_total_evidence_units:
            raise ValueError("added evidence budget exceeds total evidence budget")
        return self

    @property
    def policy_sha256(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        return hashlib.sha256(payload).hexdigest()


class NumericCandidateV2(NumericCandidate):
    extraction_version: Literal[
        "finqa_numeric_candidate_v2"
    ] = EXTRACTION_VERSION_V2


class NumericCandidateCorpusV2(_StrictFrozenModel):
    extraction_version: Literal[
        "finqa_numeric_candidate_v2"
    ] = EXTRACTION_VERSION_V2
    candidates: tuple[NumericCandidateV2, ...]
    rejected_noise_counts: dict[str, int]


class FinQANumericEvidenceClosureV2(_StrictFrozenModel):
    closure_version: Literal[
        "finqa_numeric_evidence_closure_v2"
    ] = CLOSURE_VERSION
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_unit_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    proposed_unit_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    added_unit_ids: tuple[str, ...] = Field(max_length=64)
    skipped_unit_ids: tuple[str, ...] = Field(max_length=64)
    added_reason_by_unit_id: dict[str, ClosureReason]
    total_unit_count: int = Field(ge=1, le=64)
    total_chars: int = Field(ge=1, le=64_000)
    requires_guard_scan: Literal[True] = True

    @model_validator(mode="after")
    def validate_closure_accounting(self) -> FinQANumericEvidenceClosureV2:
        if len(self.proposed_unit_ids) != len(set(self.proposed_unit_ids)):
            raise ValueError("numeric evidence closure contains duplicate units")
        if self.proposed_unit_ids[: len(self.selected_unit_ids)] != (
            self.selected_unit_ids
        ):
            raise ValueError("numeric evidence closure reordered selected units")
        if set(self.added_unit_ids) != (
            set(self.proposed_unit_ids) - set(self.selected_unit_ids)
        ):
            raise ValueError("numeric evidence closure additions do not reconcile")
        if set(self.added_reason_by_unit_id) != set(self.added_unit_ids):
            raise ValueError("numeric evidence closure reasons do not reconcile")
        if self.total_unit_count != len(self.proposed_unit_ids):
            raise ValueError("numeric evidence closure count does not reconcile")
        return self


class FinQANumericEvidenceAdmissionV2(_StrictFrozenModel):
    closure_version: Literal[
        "finqa_numeric_evidence_closure_v2"
    ] = CLOSURE_VERSION
    proposed_unit_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    admitted_unit_ids: tuple[str, ...] = Field(max_length=64)
    quarantined_unit_ids: tuple[str, ...] = Field(max_length=64)
    decision_by_unit_id: dict[str, GuardDecision]
    scan_count: int = Field(ge=1, le=64)

    @model_validator(mode="after")
    def validate_admission_accounting(
        self,
    ) -> FinQANumericEvidenceAdmissionV2:
        proposed = set(self.proposed_unit_ids)
        admitted = set(self.admitted_unit_ids)
        quarantined = set(self.quarantined_unit_ids)
        if admitted & quarantined or admitted | quarantined != proposed:
            raise ValueError("numeric evidence admission decisions do not reconcile")
        if set(self.decision_by_unit_id) != proposed:
            raise ValueError("numeric evidence admission scans do not reconcile")
        if self.scan_count != len(self.proposed_unit_ids):
            raise ValueError("numeric evidence admission scan count is invalid")
        return self


def _unit_number(unit_id: str) -> int:
    return int(unit_id.split("_", maxsplit=1)[1])


def _canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _candidate_id_v2(
    candidate: NumericCandidate,
    *,
    normalized_value: Decimal,
    sign: int,
) -> str:
    payload = {
        "column_header": candidate.column_header,
        "evidence_id": candidate.evidence_id,
        "extraction_version": EXTRACTION_VERSION_V2,
        "normalized_value": _canonical_decimal(normalized_value),
        "provenance": candidate.provenance_span.model_dump(mode="json"),
        "role": candidate.role,
        "row_header": candidate.row_header,
        "scale": candidate.scale,
        "sign": sign,
        "source_id": candidate.source_id,
        "source_kind": candidate.source_kind,
        "table_id": candidate.table_id,
        "unit": candidate.unit,
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return f"num-{digest[:20]}"


def _promote_candidate_v2(candidate: NumericCandidate) -> NumericCandidateV2:
    narrative_parenthetical = (
        candidate.source_kind == "text"
        and candidate.raw_text.lstrip().startswith("(")
        and candidate.raw_text.rstrip().endswith(")")
        and re.search(r"[+-]", candidate.raw_text) is None
    )
    normalized_value = (
        candidate.normalized_value.copy_abs()
        if narrative_parenthetical
        else candidate.normalized_value
    )
    sign = (
        -1
        if normalized_value < 0
        else (1 if normalized_value > 0 else 0)
    )
    payload = candidate.model_dump()
    payload.update(
        {
            "candidate_id": _candidate_id_v2(
                candidate,
                normalized_value=normalized_value,
                sign=sign,
            ),
            "normalized_value": normalized_value,
            "sign": sign,
            "extraction_version": EXTRACTION_VERSION_V2,
        }
    )
    return NumericCandidateV2.model_validate(payload)


def extract_numeric_candidates_v2(
    source_id: str,
    evidence_id: str,
    text: str,
    kind: Literal["text", "table_cell"],
    table_id: str | None = None,
    row_header: str | None = None,
    column_header: str | None = None,
    unit_hint: FinancialUnit | None = None,
) -> tuple[NumericCandidateV2, ...]:
    v1_candidates = extract_numeric_candidates(
        source_id=source_id,
        evidence_id=evidence_id,
        text=text,
        kind=kind,
        table_id=table_id,
        row_header=row_header,
        column_header=column_header,
        unit_hint=unit_hint,
    )
    return tuple(_promote_candidate_v2(item) for item in v1_candidates)


def build_finqa_numeric_sources_v2(
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
        sources.append(
            NumericCandidateSource(
                source_id=case.filename,
                evidence_id=evidence_id,
                text=row_header,
                kind="table_cell",
                table_id="table-main",
                row_header=row_header,
            )
        )
        for column_index, cell in enumerate(row[1:], start=1):
            if not cell.strip():
                continue
            column_header = header[column_index]
            header_source = NumericCandidateSource(
                source_id=case.filename,
                evidence_id=evidence_id,
                text=column_header,
                kind="table_cell",
                table_id="table-main",
                row_header=row_header,
                column_header=column_header,
            )
            if _VALUE_BEARING_COLUMN_HEADER.fullmatch(column_header) and any(
                candidate.role == "operand"
                for candidate in extract_numeric_candidates_v2(
                    **header_source.model_dump()
                )
            ):
                sources.append(header_source)
            sources.append(
                NumericCandidateSource(
                    source_id=case.filename,
                    evidence_id=evidence_id,
                    text=cell,
                    kind="table_cell",
                    table_id="table-main",
                    row_header=row_header,
                    column_header=column_header,
                )
            )
    return tuple(sources)


def extract_finqa_numeric_candidates_v2(
    case: FinQACase,
    *,
    admitted_evidence_ids: set[str] | None = None,
) -> NumericCandidateCorpusV2:
    candidates: list[NumericCandidateV2] = []
    rejected = Counter[str]()
    for source in build_finqa_numeric_sources_v2(
        case,
        admitted_evidence_ids=admitted_evidence_ids,
    ):
        batch = extract_numeric_candidates_v2(**source.model_dump())
        candidates.extend(batch)
        rejected.update(
            f"non_operand_{candidate.role}"
            for candidate in batch
            if candidate.role in {"ordinal", "page_number"}
        )
    candidate_ids = [candidate.candidate_id for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("v2 numeric candidate IDs must be unique within a corpus")
    return NumericCandidateCorpusV2(
        candidates=tuple(candidates),
        rejected_noise_counts=dict(sorted(rejected.items())),
    )


def numeric_candidate_surface_value_v2(
    candidate: NumericCandidateV2,
) -> Decimal:
    multiplier = _SCALE_MULTIPLIER[candidate.scale]
    return candidate.normalized_value / multiplier


def expand_finqa_numeric_evidence_v2(
    case: FinQACase,
    *,
    selected_unit_ids: Sequence[str],
    policy: NumericEvidenceClosurePolicyV2 | None = None,
) -> FinQANumericEvidenceClosureV2:
    resolved_policy = policy or NumericEvidenceClosurePolicyV2()
    selected = tuple(selected_unit_ids)
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("selected evidence IDs must be non-empty and unique")
    units = {unit.unit_id: unit for unit in build_finqa_evidence_units(case)}
    unknown = set(selected) - set(units)
    if unknown:
        raise ValueError(
            "selected evidence IDs are not present in the FinQA case: "
            + ", ".join(sorted(unknown))
        )
    selected_chars = sum(len(units[unit_id].text) for unit_id in selected)
    if (
        len(selected) > resolved_policy.max_total_evidence_units
        or selected_chars > resolved_policy.max_total_evidence_chars
    ):
        raise ValueError("selected evidence exceeds numeric closure budget")

    proposals: list[tuple[str, ClosureReason]] = []
    if resolved_policy.expand_bounded_table_parent:
        proposals.extend(
            (unit_id, "table_parent")
            for unit_id in sorted(
                (
                    unit_id
                    for unit_id in units
                    if unit_id.startswith("table_")
                ),
                key=_unit_number,
            )
            if unit_id not in selected
        )
    if resolved_policy.text_neighbor_radius:
        for selected_id in selected:
            if not selected_id.startswith("text_"):
                continue
            ordinal = _unit_number(selected_id)
            offsets = [
                *range(
                    -resolved_policy.text_neighbor_radius,
                    0,
                ),
                *range(
                    1,
                    resolved_policy.text_neighbor_radius + 1,
                ),
            ]
            for offset in offsets:
                candidate_id = f"text_{ordinal + offset}"
                if candidate_id in units and candidate_id not in selected:
                    proposals.append((candidate_id, "text_neighbor"))

    proposed = list(selected)
    added: list[str] = []
    skipped: list[str] = []
    reasons: dict[str, ClosureReason] = {}
    total_chars = selected_chars
    seen = set(selected)
    for unit_id, reason in proposals:
        if unit_id in seen:
            continue
        seen.add(unit_id)
        unit_chars = len(units[unit_id].text)
        fits = (
            len(added) < resolved_policy.max_added_evidence_units
            and len(proposed) < resolved_policy.max_total_evidence_units
            and total_chars + unit_chars
            <= resolved_policy.max_total_evidence_chars
        )
        if not fits:
            skipped.append(unit_id)
            continue
        proposed.append(unit_id)
        added.append(unit_id)
        reasons[unit_id] = reason
        total_chars += unit_chars

    return FinQANumericEvidenceClosureV2(
        policy_sha256=resolved_policy.policy_sha256,
        selected_unit_ids=selected,
        proposed_unit_ids=tuple(proposed),
        added_unit_ids=tuple(added),
        skipped_unit_ids=tuple(skipped),
        added_reason_by_unit_id=reasons,
        total_unit_count=len(proposed),
        total_chars=total_chars,
    )


def admit_finqa_numeric_evidence_closure_v2(
    case: FinQACase,
    *,
    closure: FinQANumericEvidenceClosureV2,
    guard: RetrievedContentGuard,
) -> FinQANumericEvidenceAdmissionV2:
    units = {unit.unit_id: unit for unit in build_finqa_evidence_units(case)}
    unknown = set(closure.proposed_unit_ids) - set(units)
    if unknown:
        raise ValueError("numeric evidence closure references an unknown unit")
    decisions = {
        unit_id: guard.scan(units[unit_id].text)
        for unit_id in closure.proposed_unit_ids
    }
    admitted = tuple(
        unit_id
        for unit_id in closure.proposed_unit_ids
        if decisions[unit_id].disposition == "ADMIT"
    )
    quarantined = tuple(
        unit_id
        for unit_id in closure.proposed_unit_ids
        if decisions[unit_id].disposition == "QUARANTINE"
    )
    return FinQANumericEvidenceAdmissionV2(
        proposed_unit_ids=closure.proposed_unit_ids,
        admitted_unit_ids=admitted,
        quarantined_unit_ids=quarantined,
        decision_by_unit_id=decisions,
        scan_count=len(decisions),
    )


__all__ = [
    "CLOSURE_VERSION",
    "EXTRACTION_VERSION_V2",
    "FinQANumericEvidenceAdmissionV2",
    "FinQANumericEvidenceClosureV2",
    "NumericCandidateCorpusV2",
    "NumericCandidateV2",
    "NumericEvidenceClosurePolicyV2",
    "admit_finqa_numeric_evidence_closure_v2",
    "build_finqa_numeric_sources_v2",
    "expand_finqa_numeric_evidence_v2",
    "extract_finqa_numeric_candidates_v2",
    "extract_numeric_candidates_v2",
    "numeric_candidate_surface_value_v2",
]
