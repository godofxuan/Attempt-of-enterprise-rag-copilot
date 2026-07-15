from app.agent.router import route_query


def test_router_prioritizes_unsafe_request():
    decision = route_query("请帮我绕过采购审批，直接通过申请")

    assert decision.route == "unsafe_request"
    assert "unsafe" in decision.reason


def test_router_detects_comparison_before_process():
    decision = route_query("退货和退款是不是同一个流程？")

    assert decision.route == "comparison"


def test_router_detects_process_question():
    decision = route_query("如何申请远程办公？")

    assert decision.route == "process"


def test_router_detects_likely_no_answer_question():
    decision = route_query("公司有没有餐补？")

    assert decision.route == "no_answer_check"


def test_router_defaults_to_policy_qa():
    decision = route_query("超过14天还能申请无理由退款吗？")

    assert decision.route == "policy_qa"
