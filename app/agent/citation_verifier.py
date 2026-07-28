from __future__ import annotations

import re
from collections.abc import Sequence

from app.domain.evidence import Claim, ClaimCitation
from app.domain.retrieved_security import AdmittedEvidenceChunk
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
_MIN_LEXICAL_SUPPORT = 0.4
_MIN_SHARED_CONTENT_TOKENS = 2
_NUMBER_PATTERN = re.compile(
    r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?(?![\w.])"
)
_DATE_PATTERN = re.compile(
    r"(?<!\d)(?:"
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"
    r"|\d{4}年\d{1,2}月\d{1,2}日"
    r")(?!\d)"
)
_YEAR_PATTERN = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_ACTIVE_STATUS_PATTERN = re.compile(
    r"\b(?:active|effective|in effect|takes effect)\b|生效|现行|有效|启用",
    re.IGNORECASE,
)
_INACTIVE_STATUS_PATTERN = re.compile(
    r"\b(?:expired|inactive|repealed|retired|superseded)\b"
    r"|废止|失效|过期|作废|被替代",
    re.IGNORECASE,
)
_NEGATIVE_PATTERN = re.compile(
    r"\b(?:cannot|can't|disallow(?:ed)?|forbid(?:den)?|may not|must not|"
    r"never|no|not|prohibit(?:ed)?)\b"
    r"|不得|不允许|不能|不可|禁止|严禁|无权|未获准",
    re.IGNORECASE,
)
_POSITIVE_PATTERN = re.compile(
    r"\b(?:allow(?:ed)?|can|may|must|permit(?:ted)?|require(?:d)?)\b"
    r"|允许|可以|可|必须|应当",
    re.IGNORECASE,
)


def verify_claims(
    claims: Sequence[Claim],
    visible_hits: Sequence[AdmittedEvidenceChunk],
) -> list[ClaimCitation]:
    visible_by_id: dict[str, AdmittedEvidenceChunk] = {}
    for evidence in visible_hits:
        if not isinstance(evidence, AdmittedEvidenceChunk):
            raise TypeError("visible evidence must contain admitted chunk values")
        if evidence.hit.chunk_id in visible_by_id:
            raise ValueError("visible chunk IDs must be unique")
        visible_by_id[evidence.hit.chunk_id] = evidence

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
                    reason="missing_citation",
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
                    reason="invisible_citation",
                )
            )
            continue

        evidence_text = "\n".join(
            (
                visible_by_id[chunk_id].hit.matched_text
                + "\n"
                + visible_by_id[chunk_id].hit.context_text
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
                    reason="no_lexical_support",
                )
            )
            continue
        shared_tokens = _shared_content_token_count(claim.text, evidence_text)
        if (
            lexical_support < _MIN_LEXICAL_SUPPORT
            or shared_tokens < _MIN_SHARED_CONTENT_TOKENS
        ):
            results.append(
                _unsupported(
                    claim_id=claim.claim_id,
                    cited_ids=cited_ids,
                    references_visible=True,
                    lexical_support=lexical_support,
                    reason="insufficient_lexical_support",
                )
            )
            continue
        if _date_mismatch(claim.text, evidence_text):
            results.append(
                _unsupported(
                    claim_id=claim.claim_id,
                    cited_ids=cited_ids,
                    references_visible=True,
                    lexical_support=lexical_support,
                    reason="date_mismatch",
                )
            )
            continue
        if _numeric_mismatch(claim.text, evidence_text):
            results.append(
                _unsupported(
                    claim_id=claim.claim_id,
                    cited_ids=cited_ids,
                    references_visible=True,
                    lexical_support=lexical_support,
                    reason="numeric_mismatch",
                )
            )
            continue
        if _negation_mismatch(claim.text, evidence_text):
            results.append(
                _unsupported(
                    claim_id=claim.claim_id,
                    cited_ids=cited_ids,
                    references_visible=True,
                    lexical_support=lexical_support,
                    reason="negation_mismatch",
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


def _shared_content_token_count(claim_text: str, evidence_text: str) -> int:
    return len(
        _content_tokens(claim_text).intersection(_content_tokens(evidence_text))
    )


def _date_mismatch(claim_text: str, evidence_text: str) -> bool:
    claim_dates = {
        _normalize_date(value) for value in _DATE_PATTERN.findall(claim_text)
    }
    evidence_dates = {
        _normalize_date(value) for value in _DATE_PATTERN.findall(evidence_text)
    }
    if claim_dates and not claim_dates.issubset(evidence_dates):
        return True

    claim_years = set(_YEAR_PATTERN.findall(claim_text))
    evidence_years = set(_YEAR_PATTERN.findall(evidence_text))
    if claim_years and not claim_years.issubset(evidence_years):
        return True

    claim_status = _lifecycle_status(claim_text)
    evidence_status = _lifecycle_status(evidence_text)
    return (
        claim_status is not None
        and evidence_status is not None
        and claim_status != evidence_status
        and bool(claim_dates or claim_years)
    )


def _numeric_mismatch(claim_text: str, evidence_text: str) -> bool:
    claim_numbers = {
        _normalize_number(value) for value in _NUMBER_PATTERN.findall(claim_text)
    }
    if not claim_numbers:
        return False
    evidence_numbers = {
        _normalize_number(value)
        for value in _NUMBER_PATTERN.findall(evidence_text)
    }
    return not claim_numbers.issubset(evidence_numbers)


def _negation_mismatch(claim_text: str, evidence_text: str) -> bool:
    claim_polarity = _statement_polarity(claim_text)
    evidence_polarity = _statement_polarity(evidence_text)
    return (
        claim_polarity != 0
        and evidence_polarity != 0
        and claim_polarity != evidence_polarity
    )


def _lifecycle_status(text: str) -> str | None:
    if _INACTIVE_STATUS_PATTERN.search(text):
        return "inactive"
    if _ACTIVE_STATUS_PATTERN.search(text):
        return "active"
    return None


def _statement_polarity(text: str) -> int:
    if _NEGATIVE_PATTERN.search(text):
        return -1
    if _POSITIVE_PATTERN.search(text):
        return 1
    return 0


def _normalize_date(value: str) -> str:
    return re.sub(r"\D", "-", value).strip("-")


def _normalize_number(value: str) -> str:
    return value.casefold().replace(",", "")


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
