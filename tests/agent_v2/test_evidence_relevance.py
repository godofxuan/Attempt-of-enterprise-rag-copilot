from __future__ import annotations

from app.agent.evidence_relevance import has_query_anchor_support
from tests.v2_test_support import admitted_search_hit


def test_policy_title_match_alone_does_not_support_absent_future_claim() -> None:
    query = "《差旅报销制度》是否规定 2027 年所有额度自动翻倍？"
    hit = admitted_search_hit(
        matched_text=(
            "差旅报销制度 2026 当前制度规定国内住宿上限为每晚 800 元。"
        ),
        context_text=(
            "差旅报销制度 2026 当前制度规定国内住宿上限为每晚 800 元。"
        ),
    )

    assert has_query_anchor_support(query, hit) is False


def test_direct_policy_predicate_overlap_is_supported() -> None:
    query = "当前制度每周最多允许远程办公几天？"
    hit = admitted_search_hit(
        matched_text="当前制度每周最多允许远程办公 3 天。",
        context_text="当前制度每周最多允许远程办公 3 天。",
    )

    assert has_query_anchor_support(query, hit) is True


def test_explicit_year_anchor_must_be_present_in_evidence() -> None:
    query = "2027 年远程办公制度是否仍然允许远程办公？"
    hit = admitted_search_hit(
        matched_text="2026 年远程办公制度允许远程办公。",
        context_text="2026 年远程办公制度允许远程办公。",
    )

    assert has_query_anchor_support(query, hit) is False


def test_entity_only_query_can_use_entity_match() -> None:
    query = "《远程办公制度》"
    hit = admitted_search_hit(
        matched_text="远程办公制度",
        context_text="远程办公制度",
    )

    assert has_query_anchor_support(query, hit) is True
