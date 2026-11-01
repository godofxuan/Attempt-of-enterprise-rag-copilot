"""Complete a quotation, not the support of the model's shorter assertion."""

from dataclasses import dataclass

from app.agent.citation_verifier import verify_claims, narrow_layout_key
from app.domain.evidence import Claim, ClaimCitation
from app.domain.evidence_packet import SOURCE_UNIT_END, DeliveredEvidence, source_unit_ranges


@dataclass(frozen=True)
class SourceUnit:
    citation_id: str
    field: str
    start: int
    end: int
    quote: str


def complete_units(evidence: DeliveredEvidence):
    seen=set()
    for field, text in (
        ("open_content" if evidence.opened else "matched_text", evidence.matched_text),
        ("context_text", evidence.context_text),
    ):
        if text in seen:
            continue
        seen.add(text)
        for start,end in source_unit_ranges(text):
            left = start
            while left < end and text[left].isspace():
                left += 1
            if left < end:
                yield SourceUnit(evidence.citation_id, field, left, end, text[left:end])
            start = end
        # Do not turn a budget-truncated trailing unit into an independent fact.


def complete_claim_quotes(
    claims: list[Claim], citations: list[ClaimCitation], delivered: list[DeliveredEvidence]
):
    by_id = {e.citation_id: e for e in delivered}
    updated, verified = [], []
    counts = {"expanded": 0, "ambiguous": 0, "unmatched": 0}
    for claim, citation in zip(claims, citations, strict=True):
        replacement = None
        if citation.supported and len(citation.supporting_spans)==1:
            original=citation.supporting_spans[0].quote
            if original!=claim.text and narrow_layout_key(original)==narrow_layout_key(claim.text):
                claim=claim.model_copy(update={"text":original})
        if (
            citation.unsupported_reason == "critical_fact_requires_bound_span"
            and len(claim.cited_chunk_ids) == 1
        ):
            evidence = by_id.get(claim.cited_chunk_ids[0])
            if evidence is not None:
                # Exact bytes and one complete unit only. Never remove a title,
                # condition, table header, negation or a trailing qualifier.
                units = {
                    (u.field,u.start,u.end): u
                    for u in complete_units(evidence)
                    if claim.text in u.quote and len(claim.text) < len(u.quote) <= 2000
                }
                if len(units) == 1:
                    unit = next(iter(units.values()))
                    proposed = claim.model_copy(update={"text": unit.quote, "critical": True})
                    checked = verify_claims([proposed], [evidence])[0]
                    if checked.supported and checked.support_kind == "exact_span":
                        replacement = proposed, checked
                elif len(units) > 1:
                    counts["ambiguous"] += 1
                else:
                    counts["unmatched"] += 1
        if replacement is not None:
            claim, citation = replacement
            counts["expanded"] += 1
        updated.append(claim)
        verified.append(citation)
    return (
        updated,
        verified,
        {
            "version": "complete-source-quote-v1",
            **counts,
            "basis": "host_full_quote_reverified_not_original_claim_entailment",
        },
    )
