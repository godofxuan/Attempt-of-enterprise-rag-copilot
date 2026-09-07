"""Bounded answer-shape checks; never a general semantic correctness judge."""

import re
from dataclasses import dataclass

_VALUE = (
    r"(?:\d+(?:\.\d+)?|[一二三四五六七八九十百]+|one|two|three|four|five|six|seven|eight|nine|ten)"
)
_DURATION_QUESTION = re.compile(r"how many days|几天|多少天", re.I)
_DURATION_VALUE = re.compile(_VALUE + r"\s*(?:days?\b|天|日)", re.I)
_APPROVER_QUESTION = re.compile(
    r"(?:谁|哪个部门|哪位).{0,8}(?:审批|批准)|审批人是谁|审批由谁负责|who.{0,20}approv",
    re.I,
)
_APPROVAL_RELATION = re.compile(r"审批|批准|\bapprov\w*\b", re.I)
_UNKNOWN = re.compile(r"未说明|未确定|不详|未知|没有说明|not specified|unknown", re.I)
_EXEMPT = re.compile(r"(?:无需|不需要|免于)\s*(?:审批|批准)|no approval (?:is )?required", re.I)
_CONDITION = re.compile(r"(不超过|超过|不少于|少于)\s*(\d+(?:\.\d+)?)\s*(元|美元)")
_OTHER_OBJECT = re.compile(r"另一|其他|其它|another|other\b", re.I)
_ACTOR = (
    re.compile(r"(?:审批|批准)(?:人)?(?:为|是|由)([^，。；,;.!?]{1,24}?)(?:完成|负责|$)"),
    re.compile(r"(?:由|仍需|需要|须|需(?!要))([^，。；,;.!?]{1,24}?)(?:审批|批准)"),
    re.compile(r"^([^，。；,;.!?]{1,24}?)(?:审批|批准)$"),
    re.compile(r"^(?:the\s+)?([a-z][a-z ]{0,35}?)\s+approves?\b", re.I),
    re.compile(r"\bapproved by ([a-z][a-z ]{0,35})", re.I),
)
_NON_ACTOR = re.compile(r"流程|需要|提交|核验|是否|无需|未|审批|报销|申请|规定|required", re.I)


@dataclass(frozen=True)
class AnswerSlots:
    requested: tuple[str, ...]
    satisfied: tuple[str, ...]
    retained: tuple[int, ...]
    conditional: bool = False

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(slot for slot in self.requested if slot not in self.satisfied)


def bounded_answer_slots(question: str, claim_texts: list[str]) -> AnswerSlots:
    """Inspect verified final claims, not retrieval aspects or unseen source text.

    This grammar covers explicit approval roles, exemptions and same-threshold
    branches only. Whole claims retain their original conditions and citations.
    """
    approval = bool(_APPROVER_QUESTION.search(question))
    duration = bool(_DURATION_QUESTION.search(question))
    requested = tuple(s for s, needed in (("duration", duration), ("approver", approval)) if needed)
    if not requested:
        return AnswerSlots((), (), tuple(range(len(claim_texts))))
    requested_condition = _CONDITION.search(question)
    satisfied: set[str] = set()
    retained = []
    conditional = False
    for index, text in enumerate(claim_texts):
        relevant = False
        for clause in re.split(r"[，。；,;.!?\n]+", text):
            clause = clause.strip()
            if not clause or _OTHER_OBJECT.search(clause):
                continue
            condition = _CONDITION.search(clause)
            unresolved_condition = False
            if condition:
                if requested_condition:
                    if condition.groups() != requested_condition.groups():
                        continue
                else:
                    unresolved_condition = True
            if duration and _DURATION_VALUE.search(clause):
                relevant = True
                if not unresolved_condition:
                    satisfied.add("duration")
            if approval and _APPROVAL_RELATION.search(clause):
                relevant = True
                conditional |= unresolved_condition
                if unresolved_condition or _UNKNOWN.search(clause):
                    continue
                if _EXEMPT.search(clause):
                    satisfied.add("approver")
                    continue
                if "无需" in clause or "不需要" in clause:
                    continue
                for pattern in _ACTOR:
                    match = pattern.search(clause)
                    if match and not _NON_ACTOR.search(match.group(1)):
                        satisfied.add("approver")
                        break
        # Preserve the old duration-only extractive partial contract. Approval
        # questions, however, must not retain wholly unrelated duration facts.
        if relevant or not approval:
            retained.append(index)
    if conditional:
        satisfied.discard("approver")
    return AnswerSlots(
        requested, tuple(s for s in requested if s in satisfied), tuple(retained), conditional
    )


def answer_sufficiency(question: str, claim_texts: list[str]) -> str:
    if _APPROVER_QUESTION.search(question) and not any(
        _APPROVAL_RELATION.search(text) for text in claim_texts
    ):
        return "missing_requested_relation"
    slots = bounded_answer_slots(question, claim_texts)
    if "approver" in slots.missing:
        return "missing_requested_actor"
    if _DURATION_QUESTION.search(question):
        if not any(_DURATION_VALUE.search(text) for text in claim_texts):
            return "missing_requested_value"
        return "bounded_value_present"
    return "semantic_completeness_unverified"
