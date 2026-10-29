from __future__ import annotations

import re
from collections.abc import Sequence

from app.domain.evidence import Claim, ClaimCitation, SupportingSpan
from app.domain.evidence_packet import SOURCE_UNIT_END, DeliveredEvidence, source_unit_ranges, _DEPENDENT_CLAUSE
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
_CRITICAL_FACT_PATTERN = re.compile(
    r"\d|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|"
    r"approv\w*|submit\w*|authoriz\w*|permit\w*|allow\w*|forbid\w*|prohibit\w*)\b"
    r"|批准|审批|提交|授权|允许|禁止|不得|不允许|不能|期限|金额|比例",
    re.IGNORECASE,
)
_NUMBER_PATTERN = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?(?![\w.])")
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
    r"|不得|不允许|不能|不可|禁止|严禁|无权|未获准|并非|不是|没有",
    re.IGNORECASE,
)
_POSITIVE_PATTERN = re.compile(
    r"\b(?:allow(?:ed)?|can|may|must|permit(?:ted)?|require(?:d)?)\b"
    r"|允许|可以|可|必须|应当",
    re.IGNORECASE,
)


def verify_claims(
    claims: Sequence[Claim],
    visible_hits: Sequence[AdmittedEvidenceChunk | DeliveredEvidence],
) -> list[ClaimCitation]:
    visible_by_id: dict[str, AdmittedEvidenceChunk | DeliveredEvidence] = {}
    for evidence in visible_hits:
        if not isinstance(evidence, (AdmittedEvidenceChunk, DeliveredEvidence)):
            raise TypeError("visible evidence must contain admitted chunk values")
        citation_id = (
            evidence.citation_id
            if isinstance(evidence, DeliveredEvidence)
            else evidence.hit.chunk_id
        )
        if citation_id in visible_by_id:
            raise ValueError("visible chunk IDs must be unique")
        visible_by_id[citation_id] = evidence

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

        references_visible = all(chunk_id in visible_by_id for chunk_id in cited_ids)
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

        evidence_text = "\n".join(_evidence_text(visible_by_id[chunk_id]) for chunk_id in cited_ids)
        spans = _exact_supporting_spans(claim.text, [(cid,visible_by_id[cid]) for cid in cited_ids])
        # A permitted layout variant may only recover one original complete unit.
        # Check the original quote afterwards; never normalize arbitrary numbers.
        checked_text=spans[0].quote if spans else claim.text
        lexical_support = _lexical_support(checked_text, evidence_text)
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
        shared_tokens = _shared_content_token_count(checked_text, evidence_text)
        if lexical_support < _MIN_LEXICAL_SUPPORT or shared_tokens < _MIN_SHARED_CONTENT_TOKENS:
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
        if _date_mismatch(checked_text, evidence_text):
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
        if _numeric_mismatch(checked_text, evidence_text):
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
        if _negation_mismatch(checked_text, evidence_text):
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
        qualifier_missing=any(
            unit.startswith(claim.text) and _DEPENDENT_CLAUSE.match(unit[len(claim.text):])
            for cid in cited_ids for unit in _complete_quote_texts(visible_by_id[cid])
        )
        conditional_source = bool(re.search(
            r"仅当|仅限|只有[^。！？]*才|only\s+if\b|provided\s+that\b|subject\s+to\b",
            evidence_text, re.I,
        ))
        if (_CRITICAL_FACT_PATTERN.search(claim.text) or qualifier_missing or conditional_source) and not spans:
            results.append(
                _unsupported(
                    claim_id=claim.claim_id,
                    cited_ids=cited_ids,
                    references_visible=True,
                    lexical_support=lexical_support,
                    reason="critical_fact_requires_bound_span",
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
                support_kind="exact_span" if spans else "heuristic",
                supporting_spans=spans,
            )
        )
    return results


def _exact_supporting_spans(claim_text, cited_evidence) -> list[SupportingSpan]:
    """Resolve complete source units, never a substring with a removed qualifier."""
    normalized = " ".join(claim_text.split()).casefold()
    layout=narrow_layout_key(claim_text)
    found=[]
    for citation_id, evidence in cited_evidence:
        if any(unit.startswith(claim_text) and _DEPENDENT_CLAUSE.match(unit[len(claim_text):])
               for unit in _complete_quote_texts(evidence)):
            # A short matched projection cannot overrule the condition in its
            # actually delivered parent. Both belong to the same citation.
            continue
        if isinstance(evidence, DeliveredEvidence):
            hit = evidence.anchor.hit
            fields = [
                ("open_content" if evidence.opened else "matched_text", evidence.matched_text)
            ]
            if evidence.context_text:
                fields.append(("context_text", evidence.context_text))
        else:
            hit = evidence.hit
            fields = [("matched_text", hit.matched_text), ("context_text", hit.context_text)]
        seen_fields=set()
        for field, text in fields:
            if text in seen_fields:
                continue
            seen_fields.add(text)
            ranges = [(0, len(text))]
            start = 0
            # A decimal point is not a sentence boundary; a line wrap is not one either.
            for unit_start,unit_end in source_unit_ranges(text):
                ranges.append((unit_start, unit_end))
                # A prefix ending at a complete unit retains every preceding
                # subject/condition. Never accept arbitrary skipped fragments
                # or a prefix that ends in the middle of a source unit.
                ranges.append((0, unit_end))
                start = unit_end
            # A trailing unfinished clause must not become an independent fact.
            for start, end in sorted(set(ranges)):
                while start < end and text[start].isspace():
                    start += 1
                # Only explicit neutral labels may be omitted; scope-bearing lines
                # and ordinary wrapped sentences remain part of the source unit.
                newline = text.find("\n", start, end)
                if newline >= 0 and text[start:newline].strip() in {
                    "制度要点",
                    "制度要求",
                    "Policy details",
                }:
                    start = newline + 1
                    while start < end and text[start].isspace():
                        start += 1
                while end > start and text[end - 1].isspace():
                    end -= 1
                quote = text[start:end]
                if quote and (" ".join(quote.split()).casefold() == normalized or narrow_layout_key(quote)==layout):
                    found.extend([
                        SupportingSpan(
                            citation_id=citation_id,
                            index_run_id=hit.index_run_id,
                            version_id=hit.version_id,
                            field=field,
                            start=start,
                            end=end,
                            quote=quote,
                        )
                    ])
    unique={}
    for span in found:
        # Matched text repeated at the same offset in its parent projection is
        # one bound occurrence, unlike two positions inside a source field.
        key=(span.citation_id,span.start,span.end,span.quote)
        unique.setdefault(key,span)
    return list(unique.values()) if len(unique)==1 else []


def narrow_layout_key(text: str) -> str:
    """Only CJK-digit ASCII space/tab boundaries; never join digits or words."""
    text=re.sub(r"(?<=[\u3400-\u9fff])[ \t]+(?=[0-9])","",text.strip(" \t"))
    return re.sub(r"(?<=[0-9])[ \t]+(?=[\u3400-\u9fff])","",text)


def _complete_quote_texts(evidence):
    fields=(evidence.matched_text,evidence.context_text) if isinstance(evidence,DeliveredEvidence) else (evidence.hit.matched_text,evidence.hit.context_text)
    return [text[start:end].strip() for text in fields for start,end in source_unit_ranges(text)]


def _evidence_text(evidence: AdmittedEvidenceChunk | DeliveredEvidence) -> str:
    if isinstance(evidence, DeliveredEvidence):
        return evidence.text
    return evidence.hit.matched_text + "\n" + evidence.hit.context_text


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
        support_kind="none",
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
    return len(_content_tokens(claim_text).intersection(_content_tokens(evidence_text)))


def _date_mismatch(claim_text: str, evidence_text: str) -> bool:
    claim_dates = {_normalize_date(value) for value in _DATE_PATTERN.findall(claim_text)}
    evidence_dates = {_normalize_date(value) for value in _DATE_PATTERN.findall(evidence_text)}
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
    claim_numbers = {_normalize_number(value) for value in _NUMBER_PATTERN.findall(claim_text)}
    if not claim_numbers:
        return False
    evidence_numbers = {
        _normalize_number(value) for value in _NUMBER_PATTERN.findall(evidence_text)
    }
    return not claim_numbers.issubset(evidence_numbers)


def _negation_mismatch(claim_text: str, evidence_text: str) -> bool:
    claim_is_negative = _has_explicit_negation(claim_text)
    comparable_sentences = [
        sentence
        for sentence in _sentences(evidence_text)
        if _negation_comparable(claim_text, sentence)
    ]
    if not comparable_sentences:
        return False
    evidence_polarities = {_has_explicit_negation(sentence) for sentence in comparable_sentences}
    return claim_is_negative not in evidence_polarities


def _negation_comparable(claim_text: str, evidence_sentence: str) -> bool:
    if _shared_content_token_count(claim_text, evidence_sentence) < 2:
        return False
    claim_numbers = {_normalize_number(value) for value in _NUMBER_PATTERN.findall(claim_text)}
    evidence_numbers = {
        _normalize_number(value) for value in _NUMBER_PATTERN.findall(evidence_sentence)
    }
    if claim_numbers and not claim_numbers.issubset(evidence_numbers):
        return False
    claim_dates = {_normalize_date(value) for value in _DATE_PATTERN.findall(claim_text)}
    evidence_dates = {_normalize_date(value) for value in _DATE_PATTERN.findall(evidence_sentence)}
    return not claim_dates or claim_dates.issubset(evidence_dates)


def _sentences(text: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?。！？;；\n])\s*", text)
        if sentence.strip()
    ]


def _has_explicit_negation(text: str) -> bool:
    return bool(_NEGATIVE_PATTERN.search(text))


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
