import pytest

from app.agent.evidence_relevance import has_query_anchor_support
from app.agent.question_parts import assess_question_parts, explicit_question_parts
from tests.v2_test_support import admitted_search_hit


def test_partial_evidence_for_one_explicit_question_is_relevant():
    text = "年假需要提交申请。"
    assert has_query_anchor_support(
        "年假怎么申请，有效期多久？",
        admitted_search_hit(matched_text=text, context_text=text),
    )


@pytest.mark.parametrize("text", ["年假按规定执行。", "采购需要提交申请。"])
def test_shared_topic_or_shared_predicate_alone_is_not_enough(text):
    assert not has_query_anchor_support(
        "年假怎么申请，有效期多久？",
        admitted_search_hit(matched_text=text, context_text=text),
    )


def test_partial_anchor_does_not_waive_explicit_year():
    text = "年假需要提交申请。"
    assert not has_query_anchor_support(
        "2027年年假怎么申请，有效期多久？",
        admitted_search_hit(matched_text=text, context_text=text),
    )


def test_question_clauses_remain_literal_with_conditions():
    question = "不超过500元要哪些材料，2026-09-01制度BX-07由谁审批？"
    assert explicit_question_parts(question) == (
        "不超过500元要哪些材料",
        "2026-09-01制度BX-07由谁审批",
    )


@pytest.mark.parametrize(
    "text",
    [
        "入职需要身份证。试用期未说明，年假有效期为三个月。",
        "入职需要身份证。试用期按照相关规定执行。",
    ],
)
def test_other_duration_or_vague_text_cannot_cover_probation(text):
    coverage = assess_question_parts("入职需要哪些材料，试用期多久？", [text])
    assert "试用期多久" in coverage.missing


def test_no_implicit_llm_decomposition_or_query_mutation():
    assert explicit_question_parts("我这次出差能不能报销？") == ("我这次出差能不能报销",)
    assert assess_question_parts("我这次出差能不能报销？", []).requested == ()
