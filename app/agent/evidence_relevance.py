from __future__ import annotations

import re

from app.domain.retrieved_security import AdmittedEvidenceChunk
from app.utils import tokenize_for_bm25

_GENERIC_QUERY_TOKENS = {
    "a",
    "all",
    "an",
    "any",
    "are",
    "current",
    "does",
    "is",
    "policy",
    "rules",
    "the",
    "what",
    "which",
    "公司",
    "全部",
    "制度",
    "告诉",
    "哪些",
    "多少",
    "当前",
    "所有",
    "是否",
    "版本",
    "的",
    "规定",
    "请",
    "额度",
    "年",
}
_QUOTED_ENTITY_PATTERNS = (
    re.compile(r"《([^》]+)》"),
    re.compile(r"[“\"]([^”\"]+)[”\"]"),
)
_YEAR_PATTERN = re.compile(r"(?<!\d)\d{4}(?!\d)")
_LIST_REQUEST = re.compile(r"列出|列举|哪些|complete list|all required", re.I)


def has_query_anchor_support(query: str, evidence: AdmittedEvidenceChunk) -> bool:
    if not isinstance(evidence, AdmittedEvidenceChunk):
        raise TypeError("query-anchor evidence must be an admitted chunk")
    hit = evidence.hit
    query_tokens = _content_tokens(query)
    evidence_text = f"{hit.matched_text}\n{hit.context_text}"
    evidence_tokens = _content_tokens(evidence_text)

    explicit_years = set(_YEAR_PATTERN.findall(query))
    evidence_years = set(_YEAR_PATTERN.findall(evidence_text))
    if explicit_years and not explicit_years.issubset(evidence_years):
        return False

    entity_tokens: set[str] = set()
    entities: list[str] = []
    for pattern in _QUOTED_ENTITY_PATTERNS:
        for entity in pattern.findall(query):
            entities.append(entity)
            entity_tokens.update(_content_tokens(entity))
    if entities:
        normalized_evidence = "".join(evidence_text.casefold().split())
        if not any(
            "".join(entity.casefold().split()) in normalized_evidence for entity in entities
        ):
            return False
        # A named-document list request can retrieve the document without the
        # prose repeating generic words such as "list" or "which materials".
        # This is relevance only; publication still requires grounded claims.
        if _LIST_REQUEST.search(query):
            return True
    anchors = query_tokens - entity_tokens - _GENERIC_QUERY_TOKENS
    if anchors:
        return bool(anchors.intersection(evidence_tokens))

    entity_or_query = (entity_tokens or query_tokens) - _GENERIC_QUERY_TOKENS
    return not entity_or_query or bool(entity_or_query.intersection(evidence_tokens))


def _content_tokens(text: str) -> set[str]:
    result: set[str] = set()
    for raw_token in tokenize_for_bm25(text):
        token = raw_token.casefold().strip()
        token = re.sub(r"^\W+|\W+$", "", token)
        if token:
            result.add(token)
    return result


__all__ = ["has_query_anchor_support"]
