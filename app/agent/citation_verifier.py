from __future__ import annotations

import re
from collections.abc import Sequence

from app.domain.evidence import Claim, ClaimCitation
from app.domain.queries import SearchHit
from app.utils import tokenize_for_bm25


_STOP_TOKENS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "is",
    "of",
    "the",
    "to",
    "was",
    "were",
    "的",
    "了",
    "和",
    "是",
}


def verify_claims(
    claims: Sequence[Claim],
    visible_hits: Sequence[SearchHit],
) -> list[ClaimCitation]:
    visible_by_id: dict[str, SearchHit] = {}
    for hit in visible_hits:
        if not isinstance(hit, SearchHit):
            raise TypeError("visible evidence must contain SearchHit values")
        if hit.chunk_id in visible_by_id:
            raise ValueError("visible chunk IDs must be unique")
        visible_by_id[hit.chunk_id] = hit

    results: list[ClaimCitation] = []
    for claim in claims:
        if not isinstance(claim, Claim):
            raise TypeError("claims must contain Claim values")
        cited_ids = _deduplicate(claim.cited_chunk_ids)
        if not cited_ids:
            results.append(
                _unsupported(
                    claim_id=claim.claim_id,
                    cited_ids=[],
                    references_visible=False,
                    lexical_support=0.0,
                    reason="missing citation",
                )
            )
            continue

        references_visible = all(
            chunk_id in visible_by_id for chunk_id in cited_ids
        )
        if not references_visible:
            results.append(
                _unsupported(
                    claim_id=claim.claim_id,
                    cited_ids=cited_ids,
                    references_visible=False,
                    lexical_support=0.0,
                    reason="citation does not reference visible evidence",
                )
            )
            continue

        evidence_text = "\n".join(
            (
                visible_by_id[chunk_id].matched_text
                + "\n"
                + visible_by_id[chunk_id].context_text
            )
            for chunk_id in cited_ids
        )
        lexical_support = _lexical_support(claim.text, evidence_text)
        if lexical_support == 0.0:
            results.append(
                _unsupported(
                    claim_id=claim.claim_id,
                    cited_ids=cited_ids,
                    references_visible=True,
                    lexical_support=0.0,
                    reason="citation has no lexical support",
                )
            )
            continue
        results.append(
            ClaimCitation(
                claim_id=claim.claim_id,
                cited_chunk_ids=cited_ids,
                citation_present=True,
                references_visible_evidence=True,
                lexical_support=lexical_support,
                supported=True,
            )
        )
    return results


def _unsupported(
    *,
    claim_id: str,
    cited_ids: list[str],
    references_visible: bool,
    lexical_support: float,
    reason: str,
) -> ClaimCitation:
    return ClaimCitation(
        claim_id=claim_id,
        cited_chunk_ids=cited_ids,
        citation_present=bool(cited_ids),
        references_visible_evidence=references_visible,
        lexical_support=lexical_support,
        supported=False,
        unsupported_reason=reason,
    )


def _lexical_support(claim_text: str, evidence_text: str) -> float:
    claim_tokens = _content_tokens(claim_text)
    if not claim_tokens:
        return 0.0
    evidence_tokens = _content_tokens(evidence_text)
    overlap = claim_tokens.intersection(evidence_tokens)
    return round(len(overlap) / len(claim_tokens), 6)


def _content_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw_token in tokenize_for_bm25(text):
        token = raw_token.casefold().strip()
        token = re.sub(r"^\W+|\W+$", "", token)
        if not token or token in _STOP_TOKENS:
            continue
        tokens.add(token)
    return tokens


def _deduplicate(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


__all__ = ["verify_claims"]
