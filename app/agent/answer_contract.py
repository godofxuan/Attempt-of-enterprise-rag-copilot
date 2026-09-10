"""Bounded answer-shape checks; never a general semantic correctness judge."""

import re
from dataclasses import dataclass
from app.domain.evidence_packet import SOURCE_UNIT_END
from app.retrieval.query_normalization import retrieval_query

_VALUE = (
    r"(?:\d+(?:\.\d+)?|[一二三四五六七八九十百]+|one|two|three|four|five|six|seven|eight|nine|ten)"
)
_DURATION_QUESTION = re.compile(r"how many days|几天|多少天", re.I)
_DURATION_VALUE = re.compile(
    _VALUE + r"\s*(?:(?:business\s+|calendar\s+)?days?\b|(?:个\s*)?(?:自然日|工作日|天|日))",
    re.I,
)
_APPROVER_QUESTION = re.compile(
    r"(?:谁|哪个部门|哪位).{0,8}(?:审批|批准)|审批人是谁|审批由谁负责|who.{0,20}approv",
    re.I,
)
_APPROVAL_RELATION = re.compile(r"审批|批准|\bapprov\w*\b", re.I)
_UNKNOWN = re.compile(r"未说明|未确定|不详|未知|没有说明|not specified|unknown", re.I)
_EXEMPT = re.compile(r"(?:无需|不需要|免于)\s*(?:审批|批准)|no approval (?:is )?required", re.I)
_CONDITION = re.compile(r"(不超过|超过|不少于|少于)\s*(\d+(?:\.\d+)?)\s*(元|美元)")
_OTHER_OBJECT = re.compile(r"另一|其他|其它|another|other\b", re.I)
_NON_ACTOR = re.compile(r"流程|需要|提交|核验|是否|不是|并非|不得|不能|无需|未|审批|报销|申请|规定|required", re.I)

# Explicit object heads and complete positive predicates, not substring proofs.
_OBJECT = re.compile(r"报销|申请|合同|退款|expenses?\b|travel requests?\b", re.I)
_SUBJECT = re.compile(
    r"^(?:(?:这笔|该|本|这项)?(?:出差报销|报销|出差申请|申请|退款)|(?:this|the) expense)\s*", re.I
)
_POSITIVE = re.compile(
    r"(?:由|仍需|需要|须|需(?!要))([\u4e00-\u9fff]{1,24})(?:审批|批准)"
    r"|(?:审批|批准)(?:人)?(?:为|是|由)([\u4e00-\u9fff]{1,24}?)(?:完成|负责)?"
    r"|([\u4e00-\u9fff]{1,20}(?:负责人|经理|主管|部门))(?:审批|批准)"
    r"|(?:the )?([a-z][a-z ]{0,35}?) approves? (?:this expense|travel requests?)"
    r"|is approved by ([a-z][a-z ]{0,35})",
    re.I,
)


def _positive_approval(clause: str) -> bool:
    predicate = _SUBJECT.sub("", clause).strip()
    if _EXEMPT.fullmatch(predicate):
        return True
    match = _POSITIVE.fullmatch(predicate)
    return bool(match and all(not _NON_ACTOR.search(v) for v in match.groups() if v))


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
    question = retrieval_query(question)
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
        active_condition = None
        active_object = None
        for clause in re.split(r"([。；;!?\n]+|\.(?!\d))|[，,]", text):
            if clause is None:
                continue
            if re.fullmatch(r"[。；;!?\n.]+", clause):
                active_condition = None
                active_object = None
                continue
            clause = clause.strip()
            if not clause or _OTHER_OBJECT.search(clause):
                continue
            condition = _CONDITION.search(clause)
            if condition:
                active_condition = condition
            explicit_object = _OBJECT.search(clause)
            if explicit_object:
                active_object = explicit_object.group().casefold()
            wanted_object = _OBJECT.search(question)
            if (
                wanted_object
                and active_object
                and active_object != wanted_object.group().casefold()
            ):
                continue
            unresolved_condition = False
            if active_condition:
                if requested_condition:
                    if active_condition.groups() != requested_condition.groups():
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
                predicate = clause
                if condition:
                    predicate = predicate[condition.end() :].lstrip("的 ")
                if _positive_approval(predicate):
                    satisfied.add("approver")
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
    question = retrieval_query(question)
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


_REQUIREMENT_COUNT = re.compile(
    r"(?<![0-9一二两三四五六七八九十百])([1-9]\d?|[一二两三四五六七八九十])"
    r"\s*(?:项|条)(?:关键|主要|具体)?要求"
)
# Policy lists include permissions and schedules, not just obligations.
_REQUIREMENT_PREDICATE = re.compile(r"要求|规定|必须|需要|应当|应在|须|不得|禁止|允许|安排")


def requested_requirement_count(question: str) -> int | None:
    match = _REQUIREMENT_COUNT.search(question)
    if not match:
        return None
    number = match.group(1)
    if number.isdigit():
        return int(number)
    return {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}[number]


def requirement_units(texts: list[str]) -> set[str]:
    """Complete delivered obligation units, not qrels or chunk fact labels.

    Only the same neutral headings already allowed by citation binding can be
    removed. Conditions, subjects, negation and wrapped lines stay in the unit.
    """
    units = set()
    for text in texts:
        start = 0
        ends = [match.end() for match in SOURCE_UNIT_END.finditer(text)]
        if not ends or ends[-1] < len(text):
            ends.append(len(text))
        for end in ends:
            unit = text[start:end].strip()
            start = end
            first, separator, rest = unit.partition("\n")
            if separator and first.strip() in {"制度要点", "制度要求", "Policy details"}:
                unit = rest.strip()
            if _REQUIREMENT_PREDICATE.search(unit):
                units.add("".join(unit.split()))
    return units
