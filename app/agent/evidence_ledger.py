from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from app.domain.evidence import EvidenceItem, EvidenceLedger
from app.domain.queries import QueryAnalysis
from app.domain.retrieved_security import AdmittedEvidenceChunk


EvidenceByAspect = Mapping[str, Sequence[AdmittedEvidenceChunk]]
NavigationAction = Literal["search", "find", "open"]


def build_ledger(
    analysis: QueryAnalysis,
    evidence_by_aspect: EvidenceByAspect,
    conflicts: EvidenceByAspect | None = None,
    *,
    denied_only: bool = False,
    budget_exhausted: bool = False,
    next_action: NavigationAction = "search",
) -> EvidenceLedger:
    if analysis.intent == "unsafe":
        raise ValueError("unsafe analysis cannot build an evidence ledger")
    if not analysis.required_aspects:
        raise ValueError("analysis requires at least one required aspect")
    conflicts = conflicts or {}
    required = analysis.required_aspects
    required_set = set(required)
    supplied_aspects = set(evidence_by_aspect) | set(conflicts)
    if not supplied_aspects.issubset(required_set):
        raise ValueError("evidence aspect must be a required aspect")
    if next_action not in {"search", "find", "open"}:
        raise ValueError("next_action must be search, find, or open")

    items: list[EvidenceItem] = []
    supported_aspects: list[str] = []
    conflicting_aspects: list[str] = []
    visible_count = 0

    for aspect in required:
        supporting_hits = _unique_hits(evidence_by_aspect.get(aspect, ()))
        conflicting_hits = _unique_hits(conflicts.get(aspect, ()))
        visible_count += len(supporting_hits) + len(conflicting_hits)
        items.extend(
            _to_item(aspect, hit, relation="supports")
            for hit in supporting_hits
        )
        items.extend(
            _to_item(aspect, hit, relation="conflicts")
            for hit in conflicting_hits
        )

        if not supporting_hits:
            if conflicting_hits:
                conflicting_aspects.append(aspect)
            continue
        if conflicting_hits and not _priority_resolves(
            supporting_hits,
            conflicting_hits,
        ):
            conflicting_aspects.append(aspect)
            continue
        supported_aspects.append(aspect)

    if denied_only and visible_count:
        raise ValueError("denied_only cannot include visible evidence")

    missing_aspects = [
        aspect for aspect in required if aspect not in supported_aspects
    ]
    coverage = len(supported_aspects) / len(required)
    if coverage == 1.0 and not conflicting_aspects:
        recommended_action = "answer"
    elif denied_only and visible_count == 0:
        recommended_action = "permission"
    elif budget_exhausted:
        recommended_action = "partial" if supported_aspects else "budget"
    elif supported_aspects or conflicting_aspects:
        recommended_action = next_action
    else:
        recommended_action = "not_found"

    return EvidenceLedger(
        required_aspects=required,
        items=items,
        supported_aspects=supported_aspects,
        conflicting_aspects=conflicting_aspects,
        missing_aspects=missing_aspects,
        coverage=coverage,
        recommended_action=recommended_action,
    )


def _unique_hits(
    hits: Sequence[AdmittedEvidenceChunk],
) -> list[AdmittedEvidenceChunk]:
    result: list[AdmittedEvidenceChunk] = []
    seen: set[str] = set()
    for evidence in hits:
        if not isinstance(evidence, AdmittedEvidenceChunk):
            raise TypeError("evidence must contain admitted chunk values")
        if evidence.hit.chunk_id in seen:
            continue
        seen.add(evidence.hit.chunk_id)
        result.append(evidence)
    return result


def _to_item(
    aspect: str,
    evidence: AdmittedEvidenceChunk,
    *,
    relation: Literal["supports", "conflicts"],
) -> EvidenceItem:
    hit = evidence.hit
    return EvidenceItem(
        aspect=aspect,
        chunk_id=hit.chunk_id,
        doc_id=hit.doc_id,
        relation=relation,
        authority_level=hit.authority_level,
        version_id=hit.version_id,
        status=hit.status,
    )


def _priority_resolves(
    supporting_hits: list[AdmittedEvidenceChunk],
    conflicting_hits: list[AdmittedEvidenceChunk],
) -> bool:
    support_priority = max(_priority(hit) for hit in supporting_hits)
    conflict_priority = max(_priority(hit) for hit in conflicting_hits)
    return support_priority > conflict_priority


def _priority(evidence: AdmittedEvidenceChunk) -> tuple[int, int]:
    hit = evidence.hit
    return hit.authority_level, 1 if hit.status == "active" else 0


__all__ = ["EvidenceByAspect", "NavigationAction", "build_ledger"]
