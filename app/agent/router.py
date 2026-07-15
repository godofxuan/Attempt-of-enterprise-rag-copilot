from app.agent.schemas import RouteDecision
from app.rag_service import is_unsafe_or_injection_request


UNSAFE_KEYWORDS = [
    "绕过审批",
    "绕过采购",
    "无视规定",
    "无视公司规定",
    "管理员密码",
    "泄露",
    "不要引用来源",
    "直接编",
    "bypass",
    "ignore policy",
    "admin password",
]

COMPARISON_KEYWORDS = [
    "相比",
    "对比",
    "区别",
    "分别",
    "是不是同一个",
    "是否同一个",
    "同一个流程",
    "一样吗",
    "compare",
    "difference",
]

PROCESS_KEYWORDS = [
    "如何",
    "怎么",
    "流程",
    "步骤",
    "办理",
    "提交",
    "process",
    "how to",
]

LIKELY_NO_ANSWER_KEYWORDS = [
    "餐补",
    "婚假",
    "班车",
    "股权",
    "期权",
    "薪酬表",
    "下载位置",
    "下载地址",
]


def _compact(text: str) -> str:
    return "".join((text or "").lower().split())


def _contains_any(text: str, keywords: list[str]) -> bool:
    compact = _compact(text)
    return any(_compact(keyword) in compact for keyword in keywords)


def route_query(question: str) -> RouteDecision:
    if is_unsafe_or_injection_request(question) or _contains_any(question, UNSAFE_KEYWORDS):
        return RouteDecision(route="unsafe_request", reason="unsafe keyword matched")

    if _contains_any(question, COMPARISON_KEYWORDS):
        return RouteDecision(route="comparison", reason="comparison keyword matched")

    if _contains_any(question, LIKELY_NO_ANSWER_KEYWORDS):
        return RouteDecision(route="no_answer_check", reason="likely no-answer topic matched")

    if _contains_any(question, PROCESS_KEYWORDS):
        return RouteDecision(route="process", reason="process keyword matched")

    return RouteDecision(route="policy_qa", reason="default policy question")
