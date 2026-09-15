import json

import pytest

from app.agent.answer_contract import bounded_answer_slots
from tests.agent_v2.test_query_coverage_v1 import runner_fixture
from tests.retrieval import conftest as fixtures
from tests.v2_test_support import user_context

chunk_factory = fixtures.chunk_factory
document_factory = fixtures.document_factory
snapshot_factory = fixtures.snapshot_factory


@pytest.mark.parametrize("subject", ["数据脱敏申请", "设备借用", "样品送检", "账号续期"])
def test_explicit_subject_approval_is_not_a_fixed_business_wordlist(subject):
    slots = bounded_answer_slots(subject + "由谁审批？", [subject + "由服务主管审批。"])
    assert slots.satisfied == ("approver",)


@pytest.mark.parametrize(
    "claim",
    [
        "其他申请由服务主管审批。",
        "设备借用不是由服务主管审批。",
        "设备借用需要审批。",
        "设备借用不得由服务主管审批。",
        "设备借用材料由服务主管审批。",
    ],
)
def test_explicit_subject_does_not_relax_object_negation_or_obligation(claim):
    assert "approver" not in bounded_answer_slots("设备借用由谁审批？", [claim]).satisfied


@pytest.mark.parametrize(
    "question,claims",
    [
        (
            "设备借用申请提前多久，由谁审批？",
            ["设备借用申请须提前 3 个工作日提交。", "设备借用由服务主管审批。"],
        ),
        (
            "设备借用由谁审批，单次额度上限是多少？",
            ["设备借用由服务主管审批。", "设备借用单次额度上限为 300 元。"],
        ),
    ],
)
def test_other_verified_requested_facts_survive_approval_policy(
    question, claims, snapshot_factory, document_factory, chunk_factory
):
    runner, _ = runner_fixture(
        snapshot_factory,
        document_factory,
        chunk_factory,
        texts=["\n".join(claims)],
        claim=claims[0],
    )

    def chat(model, messages, **kwargs):
        return json.dumps(
            {
                "answer": "\n".join(claims),
                "claims": [
                    {
                        "claim_id": f"C{i}",
                        "text": text,
                        "critical": True,
                        "cited_source_ids": ["S1"],
                    }
                    for i, text in enumerate(claims, 1)
                ],
            }
        )

    runner.response_builder.chat_fn = chat
    response = runner.run(question, user_context())
    assert response.mode == response.trace["final_mode"] == "answered"
    assert [c.text for c in response.claims] == claims
    assert all(c.supported for c in response.citations)
    assert response.trace["task_coverage"]["answer_missing"] == 0


def test_other_policy_limit_does_not_extend_retention(
    snapshot_factory, document_factory, chunk_factory
):
    claims = ["设备借用由服务主管审批。", "采购申请单次额度上限为 300 元。"]
    runner, _ = runner_fixture(
        snapshot_factory,
        document_factory,
        chunk_factory,
        texts=["\n".join(claims)],
        claim=claims[0],
    )

    def chat(model, messages, **kwargs):
        return json.dumps(
            {
                "answer": "\n".join(claims),
                "claims": [
                    {
                        "claim_id": f"C{i}",
                        "text": text,
                        "critical": True,
                        "cited_source_ids": ["S1"],
                    }
                    for i, text in enumerate(claims, 1)
                ],
            }
        )

    runner.response_builder.chat_fn = chat
    response = runner.run("设备借用由谁审批，单次额度上限是多少？", user_context())
    assert response.mode != "answered"
    assert all("300" not in c.text for c in response.claims)
