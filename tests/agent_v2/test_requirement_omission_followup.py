"""A cited full-fact chunk is not proof that its answer includes every fact."""

import pytest

from app.agent.answer_contract import requested_requirement_count, requirement_units
from tests.agent_v2.test_query_coverage_v1 import runner_fixture
from tests.v2_test_support import user_context

PREFIX = "工程值班制度\n当前制度要求P1告警在5分钟内确认。"
FULL = PREFIX + "当前制度规定交接时间为17:00。当前制度要求事件在3个工作日内复盘。"


@pytest.mark.parametrize("claim,expected_mode", [(PREFIX, "partial"), (FULL, "answered")])
def test_full_requirement_question_checks_final_text_not_chunk_labels(
    claim, expected_mode, snapshot_factory, document_factory, chunk_factory
):
    runner, _ = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[FULL], claim=claim
    )
    response = runner.run("请完整列出《工程值班制度》的三项关键要求。", user_context())
    assert response.mode == expected_mode
    assert response.citations and all(c.supported for c in response.citations)
    if expected_mode == "partial":
        assert response.warnings
        assert "未完整" in response.answer or "缺" in response.answer
        assert response.stop_reason == response.trace["stop_reason"] == "partial_evidence"
        assert response.trace["final_mode"] == "partial"
        assert response.trace["requirement_list_coverage"]["verified_units"] == 1


@pytest.mark.parametrize(
    "question,expected",
    [
        ("完整列出三项关键要求", 3),
        ("两条要求", 2),
        ("12项具体要求", 12),
        ("全部要求", None),
        ("提交期限是多少", None),
        ("一百三项要求", None),
    ],
)
def test_explicit_count_is_bounded(question, expected):
    assert requested_requirement_count(question) == expected


def test_duplicate_units_do_not_inflate_coverage():
    assert requirement_units([FULL, FULL, PREFIX]) == requirement_units([FULL])
    assert len(requirement_units([FULL])) == 3


def test_conditions_negation_and_scope_are_part_of_requirement_identity():
    source = "实习员工必须在7天内提交，未经批准不得报销。"
    assert not requirement_units([source]) & requirement_units(["员工必须在7天内提交。"])
    assert not requirement_units([source]) & requirement_units(
        ["实习员工必须在7天内提交，未经批准可以报销。"]
    )


@pytest.mark.parametrize(
    "second",
    [
        "制度允许未使用的假期结转。",
        "制度将常规付款安排在每周一。",
    ],
)
def test_permission_and_schedule_are_not_dropped(second):
    first = "制度要求提前五天提交申请。"
    assert len(requirement_units([first + second])) == 2
    assert len(requirement_units([first])) == 1
    assert requirement_units([first]) < requirement_units([first + second])


@pytest.mark.parametrize(
    "second",
    [
        "制度允许未使用的假期结转。",
        "制度将常规付款安排在每周一。",
    ],
)
@pytest.mark.parametrize("complete", [True, False])
def test_permission_or_schedule_must_be_in_final_claim(
    second,
    complete,
    snapshot_factory,
    document_factory,
    chunk_factory,
):
    first = "工程值班制度\n制度要求提前五天提交申请。"
    full = first + second
    runner, _ = runner_fixture(
        snapshot_factory,
        document_factory,
        chunk_factory,
        texts=[full],
        claim=full if complete else first,
    )
    response = runner.run("请完整列出《工程值班制度》的两项要求。", user_context())
    assert response.mode == ("answered" if complete else "partial")
    assert response.citations and all(c.supported for c in response.citations)
    if not complete:
        assert "未完整" in response.answer
