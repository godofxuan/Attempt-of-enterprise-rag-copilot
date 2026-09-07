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


def test_named_policy_cannot_be_replaced_by_shared_limit_word() -> None:
    hit = admitted_search_hit(
        matched_text="Freight policy: shipping limit is 100 yuan.",
        context_text="Freight policy: shipping limit is 100 yuan.",
    )
    assert not has_query_anchor_support('What is the limit in "Courier reimbursement"?', hit)


def test_named_policy_complete_list_can_match_without_generic_request_words() -> None:
    hit = admitted_search_hit(
        matched_text="Supplier onboarding. Business license and bank certificate.",
        context_text="Supplier onboarding. Business license and bank certificate.",
    )
    assert has_query_anchor_support('Give the complete list for "Supplier onboarding".', hit)


def test_named_policy_does_not_establish_unmentioned_predicate() -> None:
    hit = admitted_search_hit(
        matched_text="Supplier onboarding. Business license and bank certificate.",
        context_text="Supplier onboarding. Business license and bank certificate.",
    )
    assert not has_query_anchor_support('Does "Supplier onboarding" waive inspections?', hit)


def test_list_comparison_can_retrieve_one_named_document_at_a_time() -> None:
    hit = admitted_search_hit(
        matched_text="Supplier onboarding. Business license and bank certificate.",
        context_text="Supplier onboarding. Business license and bank certificate.",
    )
    assert has_query_anchor_support(
        'Compare the complete list for "Supplier onboarding" and "Employee onboarding".', hit
    )
