"""Regression for the preserved new-family q5 false-answered observation."""

import pytest

from app.agent.question_parts import part_is_addressed
from tests.agent_v2.test_query_coverage_v1 import runner_fixture
from tests.retrieval import conftest as fixtures
from tests.v2_test_support import user_context

chunk_factory = fixtures.chunk_factory
document_factory = fixtures.document_factory
snapshot_factory = fixtures.snapshot_factory


@pytest.mark.parametrize("scope", ["夜间作业", "跨境运输", "高温施工", "外包协作"])
@pytest.mark.parametrize(
    "wrong", ["申请必须提前 21 天提交。", "常规办理还须提交申请单。", "白天办理还须提交确认单。"]
)
def test_other_submission_does_not_cover_scoped_additional_material(scope, wrong):
    assert not part_is_addressed(scope + "还须提交什么？", [wrong])


@pytest.mark.parametrize("scope", ["夜间作业", "跨境运输", "高温施工", "外包协作"])
def test_scoped_obligation_is_addressed(scope):
    assert part_is_addressed(scope + "还须提交什么？", ["申请涉及" + scope + "时还须提交确认单。"])


def test_scope_and_action_cannot_come_from_different_sentences():
    assert not part_is_addressed(
        "夜间作业还须提交什么？", ["夜间作业必须登记。常规申请须提交确认单。"]
    )


def test_observed_omission_is_partial_without_deleting_supported_facts(
    snapshot_factory, document_factory, chunk_factory
):
    text = (
        "门禁权限续期制度\n门禁权限续期申请须提前 21 个工作日提交。"
        "门禁权限续期需要申请单和用途说明。"
        "门禁权限续期涉及夜间作业时还须提交值班确认单。"
    )
    claim = (
        "门禁权限续期制度\n门禁权限续期申请须提前 21 个工作日提交。"
        "门禁权限续期需要申请单和用途说明。"
    )
    runner, _ = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[text], claim=claim
    )
    response = runner.run("门禁权限续期需要哪些材料，夜间作业还须提交什么？", user_context())
    assert response.mode == response.trace["final_mode"] == "partial"
    assert response.trace["task_coverage"]["answer_missing"] == 1
    assert response.trace["answer_decision"]["final_mode"] == "partial"
    assert "夜间作业还须提交什么" in response.answer
    assert "21 个工作日" in response.answer and "申请单和用途说明" in response.answer
    assert all(c.supported for c in response.citations)
