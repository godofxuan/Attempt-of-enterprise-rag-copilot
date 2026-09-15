"""Necessary omission checks for explicit question clauses, not semantic entailment.

The original question and search queries are never changed. Unrecognized or
implicit requests remain outside this finite contract.
"""

import re
from dataclasses import dataclass

from app.utils import tokenize_for_bm25

_ASK = re.compile(r"哪些|什么|多久|多少|谁|怎么|如何|是否|能否|能不能|可不可以")
_FILLER = re.compile(r"需要|请问|请|到底|这个|那个|可以|要|的|了|呢|吗")
_DURATION_QUERY = re.compile(r"多久|多少(?:天|日|小时|周|个月|年)")
_DURATION = (
    r"(?:为|是|为期|最长|最短|不超过|至少|最多)?\s*"
    r"[0-9一二三四五六七八九十百两]+(?:\.\d+)?\s*(?:个?月|小时|天|日|周|年)"
)
_MATERIAL_QUERY = re.compile(r"材料|票据|凭证")
_OBLIGATION = re.compile(r"需要|须提供|需提供|应提供|提交|携带|包括|包含")
_APPLICATION_LEAD_TIME = re.compile(r"(.{2,60}?)申请(?:又)?提前多久")
_ADVANCE_DURATION = re.compile(
    r"提前\s*[0-9一二三四五六七八九十百两]+(?:\.\d+)?\s*"
    r"(?:个?\s*(?:工作日|自然日)|个?月|小时|天|日|周|年)"
)
_UNESTABLISHED_ADVANCE = re.compile(r"无需|无须|不用|不需|不要求|不得|不能|未规定|未说明")
_ADDITIONAL_MATERIAL_QUERY = re.compile(
    r"(.{2,100}?)(?:还|另外|额外)(?:需要|须|需|应|要)?"
    r"(?:提交|提供|携带)(?:什么|哪些)(?:材料|资料|文件|凭证)?[？?]?"
)


@dataclass(frozen=True)
class QuestionPartCoverage:
    requested: tuple[str, ...]
    missing: tuple[str, ...]
    overflow: bool = False


def explicit_question_parts(question: str) -> tuple[str, ...]:
    fragments = re.split(r"[，,；;。？?\n]|(?:并且|以及|同时)", question)
    return tuple(dict.fromkeys(s.strip() for s in fragments if _ASK.search(s)))


def has_explicit_part_anchor(question: str, evidence: str) -> bool:
    """Literal subject + action in one unit may support ONE explicit process part.

    Called only after whole-question scope/year checks. No new search is issued.
    This never establishes that the other parts have evidence or were answered.
    """
    parts = explicit_question_parts(question)
    if not parts:
        return False
    for part in parts[:8]:
        match = re.fullmatch(r"([\u4e00-\u9fff]{2,40})(?:怎么|如何)([\u4e00-\u9fff]{2,40})", part)
        if match is None:
            continue
        for unit in re.split(r"[。！？；;\n]", evidence):
            if re.search(re.escape(match[1]) + r".{0,80}" + re.escape(match[2]), unit):
                return True
    return False


def assess_question_parts(question: str, claims: list[str]) -> QuestionPartCoverage:
    parts = explicit_question_parts(question)
    if len(parts) < 2:
        return QuestionPartCoverage((), ())
    return QuestionPartCoverage(
        parts[:8],
        tuple(part for part in parts[:8] if not part_is_addressed(part, claims)),
        len(parts) > 8,
    )


def part_is_addressed(part: str, texts: list[str]) -> bool:
    """Reuse the same finite necessary checks at retrieval and answer stages."""
    additional = _ADDITIONAL_MATERIAL_QUERY.fullmatch(part.strip())
    if additional:
        # Generic submission elsewhere must not satisfy this scoped obligation.
        scope = additional[1].strip()
        return any(
            scope in clause and re.search(r"(?:提交|提供|携带).+", clause)
            for text in texts
            for clause in re.split(r"[。！？；;\n]", text)
        )
    application = _APPLICATION_LEAD_TIME.fullmatch(part)
    if application:
        # Bind lead time to this literal application subject in one clause;
        # another policy's duration must not satisfy the requested obligation.
        subject = application[1]
        return any(
            subject in clause
            and "申请" in clause
            and _ADVANCE_DURATION.search(clause)
            and not _UNESTABLISHED_ADVANCE.search(clause)
            for text in texts
            for clause in re.split(r"[，,。！？；;\n]", text)
        )
    sentences = [s.strip() for text in texts for s in re.split(r"[。！？；;\n]", text) if s.strip()]
    content = _FILLER.sub("", _ASK.sub("", part))
    anchors = {
        word
        for word in tokenize_for_bm25(content)
        if len(word) >= 2 and re.search(r"[\w\u4e00-\u9fff]", word)
    }
    if not anchors:
        return False
    for sentence in sentences:
        if not any(anchor in sentence for anchor in anchors):
            continue
        if _DURATION_QUERY.search(part):
            if any(
                re.search(re.escape(anchor) + r"\s*" + _DURATION, sentence) for anchor in anchors
            ):
                return True
            continue
        if _MATERIAL_QUERY.search(part) and not _OBLIGATION.search(sentence):
            continue
        return True
    return False
