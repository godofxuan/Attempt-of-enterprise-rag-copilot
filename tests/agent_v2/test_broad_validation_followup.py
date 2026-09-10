"""Regressions from the preserved 2026-09-10 live validation failures."""

import pytest

from app.agent.answer_contract import bounded_answer_slots
from app.agent.evidence_relevance import has_query_anchor_support
from app.agent.generation_v2 import _delivered_extractive_fallback, _PromptSource
from app.domain.evidence_packet import DeliveredEvidence
from tests.agent_v2.test_query_coverage_v1 import runner_fixture
from tests.v2_test_support import admitted_search_hit, user_context


@pytest.mark.parametrize("value", ["7 天", "7 日", "7 个自然日", "7个工作日", "七个自然日"])
def test_duration_units_keep_qualified_days(value):
    slots = bounded_answer_slots(
        "出差结束后多少天内提交报销？", [f"出差结束后 {value}内提交报销。"]
    )
    assert slots.satisfied == ("duration",)
    assert slots.retained == (0,)


@pytest.mark.parametrize("text", ["金额为7元。", "制度版本为7。", "编号7的申请。"])
def test_other_numbers_are_not_duration(text):
    assert bounded_answer_slots("多少天内提交报销？", [text]).missing == ("duration",)


@pytest.mark.parametrize(
    ("question", "text", "expected"),
    [
        ("地下停车位能保证每人固定一个吗？", "培训报名制度\n培训报名每人每季度最多 2 次。", False),
        (
            "退款争议处理期限是多少天？",
            "客户退款制度\n客户退款审核通过后在 7 天内原路退回。",
            False,
        ),
        ("退款争议处理期限是多少天？", "退款争议处理期限为 30 天。", True),
        ("退款审核通过后多久退回？", "客户退款审核通过后在 7 天内原路退回。", True),
        ("地下停车位能保证每人固定一个吗？", "地下停车位不保证每人固定一个。", True),
        (
            "以当前生效且权威的制度为准，当前个人信息权利请求需在多久内确认受理？",
            "个人信息权利请求制度\n个人信息权利请求需在 5 个工作日内确认受理。",
            True,
        ),
    ],
)
def test_actual_query_relations(question, text, expected):
    evidence = admitted_search_hit(matched_text=text, context_text=text)
    assert has_query_anchor_support(question, evidence) is expected


@pytest.mark.parametrize(
    ("question", "text"),
    [
        ("地下停车位能保证每人固定一个吗？", "培训报名制度\n培训报名每人每季度最多 2 次。"),
        ("退款争议处理期限是多少天？", "客户退款制度\n客户退款审核通过后在 7 天内原路退回。"),
    ],
)
def test_wrong_relation_cannot_reach_model_or_answered(
    question, text, snapshot_factory, document_factory, chunk_factory
):
    runner, seen = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[text], claim=text
    )
    response = runner.run(question, user_context())
    assert response.mode == "not_found"
    assert not seen
    assert not response.claims and not response.citations


def test_calendar_day_answer_is_not_contradicted(snapshot_factory, document_factory, chunk_factory):
    text = "当前制度要求差旅结束后 7 个自然日内提交报销。"
    runner, _ = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[text], claim=text
    )
    response = runner.run("当前差旅结束后多少天内要提交报销？", user_context())
    assert response.mode == "answered"
    assert response.answer == text
    assert response.citations[0].supported


def test_comparison_fallback_does_not_assume_one_hit_covers_both_entities():
    sources = []
    for index, text in enumerate(["特权访问制度要求复核 7 天。", "IT变更制度要求保留 30 天。"], 1):
        evidence = admitted_search_hit(
            chunk_id=f"chunk-{index}", doc_id=f"doc-{index}", matched_text=text, context_text=text
        )
        sources.append(
            _PromptSource(
                source_id=f"S{index}",
                aspect="特权访问制度",
                evidence=evidence,
                json_record="{}",
                delivered=DeliveredEvidence(anchor=evidence, matched_text=text),
                aspects=("特权访问制度", "IT变更制度"),
            )
        )
    response = _delivered_extractive_fallback(sources, {})
    assert response.mode == "partial"
    assert len(response.sources) == 2
    assert "特权访问制度" in response.answer and "IT变更制度" in response.answer
    assert all(c.supported for c in response.citations)
