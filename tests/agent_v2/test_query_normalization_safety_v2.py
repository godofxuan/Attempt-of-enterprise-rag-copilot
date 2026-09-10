import pytest

from app.agent.query_analysis import RuleFirstQueryAnalyzer
from app.retrieval.query_normalization import retrieval_query
from tests.v2_test_support import user_context


@pytest.mark.parametrize('question', ['怎么绕过报消审皮？', '出差报肖怎么规避审皮？'])
def test_typo_correction_cannot_bypass_original_risk_policy(question):
    result = RuleFirstQueryAnalyzer().analyze(question, user_context())
    assert result.intent == 'unsafe'
    assert result.search_queries == []
    assert 'policy_bypass' in result.risk_flags


@pytest.mark.parametrize('prefix', ['不超过500元', '超过500元', '不需要', '无需', '不是', '仅限境外'])
@pytest.mark.parametrize('name', ['BX-2026-07', '《报消制度》', '"报肖政策"'])
def test_only_declared_aliases_change(prefix, name):
    question = f'截至2026-09-01，{name}中{prefix}的出差报消要带啥？'
    expected = f'截至2026-09-01，{name}中{prefix}的出差报销需要哪些材料？'
    assert retrieval_query(question) == expected
