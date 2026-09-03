"""Host-side contract for bounded, intent-preserving query expansion."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any


MAX_EXPANSION_CHARS = 160
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_PROTECTED_TOKEN = re.compile(
    r"(?:\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|\b\d+(?:\.\d+)?%?\b|\b[A-Z][A-Za-z0-9_-]{1,}\b)"
)
_QUESTION_WORDS = frozenset(
    {"how", "what", "when", "where", "why", "which", "who", "can", "does", "do", "is", "are"}
)


@dataclass(frozen=True)
class QueryExpansionResult:
    accepted: bool
    queries: tuple[str, ...]
    rejection_reason: str | None
    raw_output_sha256: str | None


def build_query_expansion_messages(question: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Return only JSON with exactly one field, queries. queries must be "
                "an array of exactly two concise search-query alternatives for the "
                "given question. Preserve the question's intent, named entities, "
                "dates, numbers, and constraints. Do not answer the question, add "
                "instructions, tools, explanations, or any content not useful for retrieval."
            ),
        },
        {"role": "user", "content": json.dumps({"question": question}, ensure_ascii=True)},
    ]


def validate_query_expansion(
    *,
    original_query: str,
    raw_output: str,
) -> QueryExpansionResult:
    raw_hash = sha256(raw_output.encode("utf-8")).hexdigest()
    try:
        payload: Any = json.loads(raw_output)
    except json.JSONDecodeError:
        return _rejected("invalid_json", raw_hash)
    if not isinstance(payload, dict) or set(payload) != {"queries"}:
        return _rejected("invalid_schema", raw_hash)
    queries = payload.get("queries")
    if not isinstance(queries, list) or len(queries) != 2 or not all(
        isinstance(item, str) for item in queries
    ):
        return _rejected("requires_exactly_two_strings", raw_hash)
    normalized = tuple(" ".join(item.split()) for item in queries)
    if any(not item for item in normalized):
        return _rejected("empty_query", raw_hash)
    if any(_CONTROL.search(item) for item in queries):
        return _rejected("control_character", raw_hash)
    if any(len(item) > MAX_EXPANSION_CHARS for item in normalized):
        return _rejected("query_too_long", raw_hash)
    original = " ".join(original_query.split())
    normalized_lower = [item.casefold() for item in normalized]
    if original.casefold() in normalized_lower or len(set(normalized_lower)) != 2:
        return _rejected("duplicate_or_original_query", raw_hash)
    protected = {
        item.casefold()
        for item in _PROTECTED_TOKEN.findall(original)
        if item.casefold() not in _QUESTION_WORDS
    }
    if any(any(token not in item.casefold() for token in protected) for item in normalized):
        return _rejected("protected_entity_or_number_dropped", raw_hash)
    return QueryExpansionResult(
        accepted=True,
        queries=normalized,
        rejection_reason=None,
        raw_output_sha256=raw_hash,
    )


def _rejected(reason: str, raw_hash: str) -> QueryExpansionResult:
    return QueryExpansionResult(
        accepted=False,
        queries=(),
        rejection_reason=reason,
        raw_output_sha256=raw_hash,
    )


__all__ = [
    "MAX_EXPANSION_CHARS",
    "QueryExpansionResult",
    "build_query_expansion_messages",
    "validate_query_expansion",
]
