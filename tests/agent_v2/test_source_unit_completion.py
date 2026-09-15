"""Host may quote more source context, never validate a weakened substring."""

import pytest

from tests.agent_v2.test_query_coverage_v1 import runner_fixture
from tests.retrieval import conftest as fixtures
from tests.v2_test_support import user_context

chunk_factory = fixtures.chunk_factory
document_factory = fixtures.document_factory
snapshot_factory = fixtures.snapshot_factory


@pytest.mark.parametrize(
    "text,claim,question,required",
    [
        (
            "设备借用制度\n设备借用申请须提前 3 个工作日提交。设备借用由服务主管审批。",
            "设备借用申请须提前 3 个工作日提交。",
            "设备借用申请提前多久？",
            "设备借用制度",
        ),
        (
            "仅限上海办公室\n出差申请必须提前 7 天提交。",
            "出差申请必须提前 7 天提交。",
            "上海办公室出差申请提前几天？",
            "仅限上海办公室",
        ),
        (
            "附表\n| 适用情况 | 要求 |\n| 夜间作业 | 值班确认单 |\n"
            "设备借用涉及夜间作业时还须提交值班确认单。",
            "设备借用涉及夜间作业时还须提交值班确认单。",
            "设备借用夜间作业需要什么？",
            "| 夜间作业 | 值班确认单 |",
        ),
    ],
)
def test_complete_source_unit_restored_not_stripped(
    text, claim, question, required, snapshot_factory, document_factory, chunk_factory
):
    runner, _ = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[text], claim=claim
    )
    response = runner.run(question, user_context())
    assert response.mode == "answered"
    assert required in response.answer and claim in response.answer
    assert response.trace["source_unit_completion"]["expanded"] == 1
    assert all(c.support_kind == "exact_span" for c in response.citations)


@pytest.mark.parametrize(
    "text,claim",
    [
        ("仅限上海办公室\n出差申请必须提前 7 天提交。", "出差申请必须提前 30 天提交。"),
        ("出差申请不得由员工自行审批。", "出差申请可以由员工自行审批。"),
        ("出差申请必须提前 7 天提交。", "采购申请必须提前 7 天提交。"),
        (
            "上海办公室\n出差申请必须提前 7 天提交。北京办公室\n出差申请必须提前 7 天提交。",
            "出差申请必须提前 7 天提交。",
        ),
    ],
)
def test_no_completion_of_contradiction_wrong_object_or_ambiguous_scope(
    text, claim, snapshot_factory, document_factory, chunk_factory
):
    runner, _ = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[text], claim=claim
    )
    response = runner.run("出差申请有什么要求？", user_context())
    assert response.mode != "answered"
    assert response.trace.get("source_unit_completion", {}).get("expanded", 0) == 0


def test_restored_unit_does_not_discard_trailing_condition(
    snapshot_factory, document_factory, chunk_factory
):
    text = "出差申请须提前 7 天提交，仅限已经完成培训的员工。"
    claim = "出差申请须提前 7 天提交"
    runner, _ = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[text], claim=claim
    )
    response = runner.run("出差申请有什么要求？", user_context())
    assert response.mode == "answered"
    assert "仅限已经完成培训的员工" in response.answer
    assert response.trace["source_unit_completion"]["expanded"] == 1
