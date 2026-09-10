"""Bounded reimbursement needs, not a general semantic completeness judge."""
from dataclasses import dataclass
import re

from app.agent.answer_contract import bounded_answer_slots
from app.retrieval.query_normalization import retrieval_query

_DOMAIN = re.compile(r"报[销消]")
_MATERIAL_QUERY = re.compile(r"材料|票据|凭证|带啥|带什么|准备什么")
_APPROVAL_QUERY = re.compile(r"审批|批准|签.{0,3}字")
_LIMIT_QUERY = re.compile(r"额度|上限|限额|最多.{0,8}元")
_PERSONAL = re.compile(r"我|这次|这笔")
_ELIGIBILITY = re.compile(r"能不能|能否|可不可以|可以.{0,5}报销吗|能报销吗")
_MATERIALS = re.compile(r"发票|行程单|出差申请单|审批单|付款凭证|支付凭证|报销单|合同|收据|明细清单")
_MATERIAL_RELATION = re.compile(r"需要|需提供|须提供|应提供|提交|携带|材料.{0,4}(?:包括|包含|为)|凭证")
_LIMIT_VALUE = re.compile(r"(?:额度|上限|限额|最多).{0,16}\d+(?:\.\d+)?\s*(?:元|美元)")

NEED_LABELS = {"materials": "材料", "approval": "审批", "limit": "额度", "eligibility": "个人适用条件"}


def requested_needs(question: str) -> tuple[str, ...]:
    question = retrieval_query(question)
    if not _DOMAIN.search(question):
        return ()
    return tuple(key for key, needed in (
        ("materials", bool(_MATERIAL_QUERY.search(question))),
        ("approval", bool(_APPROVAL_QUERY.search(question))),
        ("limit", bool(_LIMIT_QUERY.search(question))),
        ("eligibility", bool(_PERSONAL.search(question) and _ELIGIBILITY.search(question))),
    ) if needed)


def material_terms(text: str) -> set[str]:
    return {term for clause in re.split(r"[。！？；\n]", text)
            if _MATERIAL_RELATION.search(clause) for term in _MATERIALS.findall(clause)}


def relevant_need_count(text: str, needs: tuple[str, ...]) -> int:
    signals = {"materials": bool(need_statements(text, 'materials')), "approval": bool(_APPROVAL_QUERY.search(text)),
               "limit": bool(_LIMIT_VALUE.search(text)), "eligibility": False}
    return sum(signals[need] for need in needs)


_OTHER_SUBJECT = re.compile(r'^(?:该|本|其他|另一)?(?:合同|采购|退款|休假|年假|入职|离职).{0,8}(?:需要|额度|材料|不需要)')
_MATERIAL_OBJECT = re.compile(r'材料|发票|行程单|申请单|审批单|凭证|报销单|合同|收据|清单|证明|原件|复印件')
_MATERIAL_PREDICATE = re.compile(r'需要|无需|不需要|须|提供|提交|携带|包括|包含')


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r'[。！？；;\n]', text) if s.strip()]


def need_statements(text: str, need: str) -> set[str]:
    """Keep complete clauses, including object, condition and negative obligation.

    A finite packet-relative check, not a semantic entailment model. No name-only
    union: 'invoice' cannot cover 'invoice original if over 500'.
    """
    result = set()
    for sentence in _sentences(text):
        if _OTHER_SUBJECT.search(sentence):
            continue
        if need == 'materials':
            matches = _MATERIAL_PREDICATE.search(sentence) and _MATERIAL_OBJECT.search(sentence)
        elif need == 'limit':
            matches = _LIMIT_VALUE.search(sentence)
        else:
            matches = False
        if matches:
            result.add(''.join(sentence.split()))
    return result


def complementary_claim(question: str, text: str) -> bool:
    """Only wholly relevant, non-approval claims may extend approval retention."""
    needs = set(requested_needs(question)) & {'materials', 'limit'}
    sentences = _sentences(text)
    if not needs or not sentences or _APPROVAL_QUERY.search(text):
        return False
    return all(any(need_statements(s, need) for need in needs) for s in sentences)


@dataclass(frozen=True)
class NeedCoverage:
    requested: tuple[str, ...]
    missing: tuple[str, ...]
    incomplete_read: bool


def assess_need_coverage(question: str, claims: list[str], evidence: list[str], *,
                         incomplete_read: bool = False) -> NeedCoverage:
    needs = requested_needs(question)
    def complete(need: str) -> bool:
        available = set().union(*(need_statements(text, need) for text in evidence))
        answered = set().union(*(need_statements(text, need) for text in claims))
        return bool(available) and available.issubset(answered)
    # Only finite, explicit relations are marked covered. Unknown stays unknown.
    approval_question = question if re.search(r"谁|哪个部门|哪位", question) else '报销由谁审批？'
    approval = bounded_answer_slots(approval_question, claims)
    satisfied = {
        "materials": complete('materials'),
        "approval": "approver" in approval.satisfied,
        "limit": complete('limit'),
        # A policy excerpt alone cannot establish the employee's actual circumstances.
        "eligibility": False,
    }
    return NeedCoverage(needs, tuple(need for need in needs if not satisfied[need]), incomplete_read)
