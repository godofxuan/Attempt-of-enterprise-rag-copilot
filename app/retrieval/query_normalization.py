"""Finite search-time aliases; never rewrite the stored question or its filters."""
import re

_PROTECTED = re.compile(r'《[^》]*》|“[^”]*”|"[^"\n]*"|\b[A-Za-z][A-Za-z0-9_.-]*\b')
_DOMAIN = re.compile(r'报[销消肖](?!科技|公司|品牌)')
_ALIASES = (('报消', '报销'), ('报肖', '报销'), ('审皮', '审批'),
            ('发漂', '发票'), ('要带啥', '需要哪些材料'), ('要带什么', '需要哪些材料'))


def retrieval_query(question: str) -> str:
    """Only normalize unquoted reimbursement prose. All other bytes survive.

    This is not general spell correction. Negations, thresholds, dates and IDs
    are not edited. Quoted names remain exact even if they resemble a typo.
    """
    spans = list(_PROTECTED.finditer(question))
    plain = _PROTECTED.sub('', question)
    if not _DOMAIN.search(plain):
        return question
    parts, start = [], 0
    for match in [*spans, None]:
        end = match.start() if match is not None else len(question)
        fragment = question[start:end]
        for old, new in _ALIASES:
            fragment = fragment.replace(old, new)
        parts.append(fragment)
        if match is not None:
            parts.append(match.group())
            start = match.end()
    return ''.join(parts)
