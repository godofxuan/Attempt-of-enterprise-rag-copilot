"""Complete a quotation, not the support of the model's shorter assertion."""

from dataclasses import dataclass

from app.agent.citation_verifier import verify_claims
from app.domain.evidence import Claim, ClaimCitation
from app.domain.evidence_packet import SOURCE_UNIT_END, DeliveredEvidence


@dataclass(frozen=True)
class SourceUnit:
    citation_id: str
    field: str
    start: int
    end: int
    quote: str


def complete_units(evidence: DeliveredEvidence):
    for field, text in (
        ("matched_text", evidence.matched_text),
        ("context_text", evidence.context_text),
    ):
        start = 0
        for match in SOURCE_UNIT_END.finditer(text):
            end = match.end()
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
        if (
            citation.unsupported_reason == "critical_fact_requires_bound_span"
            and len(claim.cited_chunk_ids) == 1
        ):
            evidence = by_id.get(claim.cited_chunk_ids[0])
            if evidence is not None:
                # Exact bytes and one complete unit only. Never remove a title,
                # condition, table header, negation or a trailing qualifier.
                units = {
                    u.quote: u
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
