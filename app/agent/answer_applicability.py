"""Literal business-scope checks, separate from citation/semantic correctness."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.evidence import AnswerResponse


_LOCATION = re.compile(
    r"(?<![\w'-])(?P<name>[A-Za-z][A-Za-z'-]*"
    r"(?:[ \t]+[A-Za-z][A-Za-z'-]*){0,3})[ \t]+(?P<kind>office|branch)\b",
    re.I,
)
_GRADE = re.compile(r"\b(?:staff\s+)?grade\s+([A-Za-z]*\d+[A-Za-z0-9-]*)\b", re.I)
_PREFIX = {
    "for", "in", "at", "the", "of", "is", "does", "what", "which", "compare",
    "between", "and", "versus", "vs", "from", "about", "under", "to",
}
_GENERIC = {"my", "your", "our", "their", "this", "that", "any", "each", "every"}


def _locations(text: str) -> frozenset[tuple[str, str]]:
    values = set()
    for match in _LOCATION.finditer(text):
        words = match["name"].casefold().split()
        # Structural delimiters, not a dictionary of supported office names.
        delimiters = [i for i, word in enumerate(words) if word in _PREFIX]
        if delimiters:
            words = words[delimiters[-1] + 1:]
        if words and not set(words).intersection(_GENERIC):
            values.add((match["kind"].casefold(), " ".join(words)))
    return frozenset(values)


def _literal_present(value: str, text: str) -> bool:
    return re.search(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])", text, re.I) is not None


@dataclass(frozen=True)
class LiteralQueryScope:
    locations: frozenset[tuple[str, str]]
    grades: frozenset[str]
    ambiguous: bool = False

    @property
    def active(self) -> bool:
        return bool(self.locations or self.grades)


def literal_query_scope(question: str) -> LiteralQueryScope:
    locations = _locations(question)
    grades = frozenset(value.casefold() for value in _GRADE.findall(question))
    # Literal matching cannot establish negated/conditional applicability.
    # Preserve the original question; never silently remove its negation.
    ambiguous = bool(
        (locations or grades)
        and re.search(r"\b(?:not|except|unless|excluding|if)\b|不是|除外|除非", question, re.I)
    )
    return LiteralQueryScope(locations, grades, ambiguous)


def scope_evidence_support(question: str, text: str, *, section_path: tuple[str, ...] = ()) -> bool:
    scope = literal_query_scope(question)
    if not scope.active:
        return True
    if scope.ambiguous:
        return False
    locations = _locations(text) | _locations("\n".join(section_path))
    if scope.locations and (not locations or not locations.issubset(scope.locations)):
        return False
    if scope.grades and not any(_literal_present(grade, text) for grade in scope.grades):
        return False
    return True


def enforce_answer_applicability(question: str, response: AnswerResponse) -> AnswerResponse:
    """Cannot promote, add a source, alter authority or waive citation checks."""
    scope = literal_query_scope(question)
    if not scope.active or response.mode not in {"answered", "partial"}:
        return response
    source_by_id = {source.chunk_id: source for source in response.sources}
    citation_by_id = {citation.claim_id: citation for citation in response.citations}
    kept = []
    covered_locations = set()
    covered_grades = set()
    for claim in response.claims:
        citation = citation_by_id.get(claim.claim_id)
        previews = []
        for cid in claim.cited_chunk_ids:
            source = source_by_id.get(cid)
            if source is None:
                continue
            # UI previews are capped at 1000 characters. A verified span from
            # this exact source/version may legitimately lie beyond that cap.
            spans = [span.quote for span in citation.supporting_spans
                     if citation.support_kind == "exact_span" and span.citation_id == cid
                     and span.index_run_id == source.index_run_id
                     and span.version_id == source.version_id] if citation else []
            previews.append(("\n".join([source.preview, *spans]), tuple(source.section_path)))
        # Check each cited source independently: a correct header in source A
        # must not make an unrelated source B applicable by text concatenation.
        if (not citation or not citation.supported or not previews
                or len(previews) != len(claim.cited_chunk_ids)
                or any(not scope_evidence_support(question, text, section_path=section)
                       for text, section in previews)):
            continue
        claim_locations = _locations(claim.text)
        if scope.locations and claim_locations and not claim_locations.issubset(scope.locations):
            continue
        kept.append(claim)
        for text, section in previews:
            locations = _locations(text) | _locations("\n".join(section))
            covered_locations.update(locations.intersection(scope.locations))
            covered_grades.update(grade for grade in scope.grades if _literal_present(grade, text))
    missing = len(scope.locations - covered_locations) + len(scope.grades - covered_grades)
    dropped = len(response.claims) - len(kept)
    audit = {
        "basis": "literal_office_branch_grade_not_semantic_proof_v1",
        "requested_constraints": len(scope.locations) + len(scope.grades),
        "missing_constraints": missing,
        "ambiguous_query": scope.ambiguous,
        "dropped_claims": dropped,
    }
    trace = {**response.trace, "query_applicability": audit}
    if not missing and not dropped:
        return response.model_copy(update={"trace": trace})
    note = (
        "The visible evidence does not establish all requested office/branch and grade "
        "constraints. Unverified statements were withheld."
    )
    mode, reason = ("partial", "partial_evidence") if kept else ("not_found", "not_found")
    claim_ids = {claim.claim_id for claim in kept}
    source_ids = {cid for claim in kept for cid in claim.cited_chunk_ids}
    return AnswerResponse(
        mode=mode,
        stop_reason=reason,
        answer="\n".join([*(claim.text for claim in kept), note]),
        claims=kept,
        citations=[c for c in response.citations if c.claim_id in claim_ids],
        sources=[s for s in response.sources if s.chunk_id in source_ids],
        warnings=[*response.warnings, note],
        trace={**trace, "final_mode": mode, "stop_reason": reason},
    )
