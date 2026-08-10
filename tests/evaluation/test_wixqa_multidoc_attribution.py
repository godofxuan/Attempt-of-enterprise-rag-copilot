from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from app.agent.runner_v2 import V2AgentRunner
from app.agent.tools_v2 import V2ToolRegistry
from app.domain.agent import AgentBudget
from app.domain.enterprise_documents import EnterpriseDocument, RawProvenance
from app.domain.queries import UserContext
from app.evaluation.wixqa_multidoc_attribution import (
    FirstLossStage,
    FrozenMultiDocCase,
    MultiDocAttributionCase,
    RecordingWixQANavigator,
    citation_complete,
    classify_first_loss,
    gold_coverage,
    run_recorded_agent,
    validate_frozen_case,
)
from app.external_datasets.wixqa import WixQAQuestion
from app.external_datasets.wixqa_agent_eval import WixQARankedNavigator
from app.external_datasets.wixqa_retrieval import WixQAFlatChunk


def _article(article_id: str, text: str) -> EnterpriseDocument:
    digest = hashlib.sha256(text.encode()).hexdigest()
    return EnterpriseDocument(
        document_id=f"wixqa:{article_id}",
        source_type="support_article",
        source_native_id=article_id,
        title=article_id,
        text=text,
        raw_provenance=RawProvenance(
            dataset_name="WixQA",
            source_revision="a" * 40,
            source_file="corpus.jsonl",
            source_row=1,
            source_native_id=article_id,
            raw_record_sha256=digest,
        ),
    )


def _chunk(article: EnterpriseDocument) -> WixQAFlatChunk:
    text = f"{article.title}\n{article.text}"
    return WixQAFlatChunk(
        chunk_id=f"chunk:{article.source_native_id}",
        article_id=article.source_native_id,
        ordinal=1,
        text=text,
        text_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def _question() -> WixQAQuestion:
    return WixQAQuestion(
        question_id="wixqa:expertwritten:" + "a" * 24,
        cohort="expertwritten",
        source_row=1,
        question="Which access and billing steps are required?",
        answer="Use both documents.",
        article_ids=["a" * 64, "b" * 64],
        raw_record_sha256="c" * 64,
    )


def _frozen(question: WixQAQuestion) -> FrozenMultiDocCase:
    return FrozenMultiDocCase(
        question_id=question.question_id,
        question_sha256=hashlib.sha256(question.question.encode()).hexdigest(),
        answer_sha256=hashlib.sha256(question.answer.encode()).hexdigest(),
        gold_support_article_ids=question.article_ids,
    )


def _user() -> UserContext:
    return UserContext(
        user_id="evaluator",
        tenant_id="wixqa-public",
        region="global",
        groups=["public"],
        roles=["evaluator"],
    )


def _budget() -> AgentBudget:
    return AgentBudget(
        max_search_calls=3,
        max_find_calls=2,
        max_open_calls=4,
        max_steps=12,
        max_context_chars=12_000,
        deadline_ms=15_000,
    )


def test_multidoc_gold_requires_multiple_distinct_documents() -> None:
    question = _question()
    with pytest.raises(ValidationError, match="distinct"):
        FrozenMultiDocCase(
            question_id=question.question_id,
            question_sha256="d" * 64,
            answer_sha256="e" * 64,
            gold_support_article_ids=["a" * 64, "a" * 64],
        )


def test_frozen_case_reads_only_declared_protocol_fields() -> None:
    question = _question()
    frozen = FrozenMultiDocCase.from_protocol_record(
        {
            "case_type": "multi_document",
            "question_id": question.question_id,
            "question_sha256": hashlib.sha256(
                question.question.encode()
            ).hexdigest(),
            "answer_sha256": hashlib.sha256(
                question.answer.encode()
            ).hexdigest(),
            "gold_support_article_ids": question.article_ids,
            "future_protocol_field": "ignored at the compatibility boundary",
        }
    )
    assert frozen.gold_support_article_ids == question.article_ids
    with pytest.raises(ValueError, match="not a multi-document"):
        FrozenMultiDocCase.from_protocol_record(
            {
                "case_type": "single_document",
                "question_id": question.question_id,
            }
        )


def test_multidoc_gold_document_ids_resolve() -> None:
    question = _question()
    validate_frozen_case(_frozen(question), question, set(question.article_ids))
    with pytest.raises(ValueError, match="does not resolve"):
        validate_frozen_case(_frozen(question), question, {question.article_ids[0]})


def test_multidoc_evaluator_counts_complete_document_set_correctly() -> None:
    gold = ["a", "b"]
    assert citation_complete(gold, ["noise", "b", "a"])
    assert gold_coverage(gold, ["a", "b", "noise"]) == 1.0


def test_multidoc_evaluator_rejects_partial_document_coverage() -> None:
    gold = ["a", "b"]
    assert not citation_complete(gold, ["a"])
    assert gold_coverage(gold, ["a"]) == 0.5


def test_first_loss_prefers_candidate_pool_before_top5_selection() -> None:
    values = {
        "gold_document_ids": ["a", "b"],
        "retrieval_top20_document_ids": ["a"],
        "retrieval_top5_document_ids": ["a"],
        "controller_retrieved_document_ids": ["a"],
        "post_acl_document_ids": ["a"],
        "post_guard_document_ids": ["a"],
        "ledger_document_ids": ["a"],
        "response_selected_document_ids": ["a"],
        "post_grounding_document_ids": ["a"],
        "final_document_ids": ["a"],
    }
    assert classify_first_loss(**values) == FirstLossStage.RETRIEVAL_TOP20_MISS
    values["retrieval_top20_document_ids"] = ["a", "b"]
    assert classify_first_loss(**values) == FirstLossStage.RETRIEVAL_TOP5_MISS


def test_schema_rejects_incorrect_first_loss_or_coverage() -> None:
    gold = ["a" * 64, "b" * 64]
    with pytest.raises(ValidationError, match="coverage mismatch"):
        MultiDocAttributionCase(
            case_id="case-1",
            question_id_sha256="c" * 64,
            gold_document_ids=gold,
            gold_document_count=2,
            retrieval_top5_document_ids=gold,
            retrieval_top10_document_ids=gold,
            retrieval_top20_document_ids=gold,
            controller_retrieved_document_ids=gold,
            post_acl_document_ids=gold,
            pre_guard_document_ids=gold,
            post_guard_document_ids=gold,
            intent="fact",
            required_aspects=["answer"],
            controller_search_query_sha256=["d" * 64],
            controller_search_call_count=1,
            controller_find_call_count=0,
            controller_open_call_count=0,
            controller_stop_reason="completed",
            ledger_supported_aspects=["answer"],
            ledger_document_ids=gold,
            ledger_coverage=1.0,
            ledger_recommended_action="answer",
            prompt_stage_status="NOT_APPLICABLE_SOURCE_RUN_EXTRACTIVE",
            prompt_document_ids=[],
            generation_stage_status="NOT_APPLICABLE_SOURCE_RUN_EXTRACTIVE",
            model_proposed_citation_document_ids=[],
            response_selected_document_ids=gold,
            pre_grounding_citation_document_ids=gold,
            post_grounding_citation_document_ids=gold,
            final_source_document_ids=gold,
            source_observed_citation_complete=False,
            gold_retrieval_oracle_post_guard_document_ids=gold,
            gold_retrieval_oracle_final_source_document_ids=[gold[0]],
            guard_quarantined_count=0,
            guard_risk_categories=[],
            coverage_by_stage={
                "retrieval_top20": 0.5,
                "retrieval_top5": 1.0,
                "controller_search": 1.0,
                "post_acl": 1.0,
                "post_guard": 1.0,
                "ledger": 1.0,
                "response_selection": 1.0,
                "post_grounding": 1.0,
                "final": 1.0,
            },
            first_loss_stage="NO_FAILURE",
            query_analysis_underspecified=True,
            ledger_false_completeness=False,
        )

    with pytest.raises(ValidationError, match="first_loss_stage"):
        MultiDocAttributionCase.model_validate(
            {
                "case_id": "case-1",
                "question_id_sha256": "c" * 64,
                "gold_document_ids": gold,
                "gold_document_count": 2,
                "retrieval_top5_document_ids": gold,
                "retrieval_top10_document_ids": gold,
                "retrieval_top20_document_ids": gold,
                "controller_retrieved_document_ids": gold,
                "post_acl_document_ids": gold,
                "pre_guard_document_ids": gold,
                "post_guard_document_ids": gold,
                "intent": "fact",
                "required_aspects": ["answer"],
                "controller_search_query_sha256": ["d" * 64],
                "controller_search_call_count": 1,
                "controller_find_call_count": 0,
                "controller_open_call_count": 0,
                "controller_stop_reason": "completed",
                "ledger_supported_aspects": ["answer"],
                "ledger_document_ids": gold,
                "ledger_coverage": 1.0,
                "ledger_recommended_action": "answer",
                "prompt_stage_status": "NOT_APPLICABLE_SOURCE_RUN_EXTRACTIVE",
                "prompt_document_ids": [],
                "generation_stage_status": "NOT_APPLICABLE_SOURCE_RUN_EXTRACTIVE",
                "model_proposed_citation_document_ids": [],
                "response_selected_document_ids": gold,
                "pre_grounding_citation_document_ids": gold,
                "post_grounding_citation_document_ids": gold,
                "final_source_document_ids": gold,
                "source_observed_citation_complete": False,
                "gold_retrieval_oracle_post_guard_document_ids": gold,
                "gold_retrieval_oracle_final_source_document_ids": [gold[0]],
                "guard_quarantined_count": 0,
                "guard_risk_categories": [],
                "coverage_by_stage": {
                    "retrieval_top20": 1.0,
                    "retrieval_top5": 1.0,
                    "controller_search": 1.0,
                    "post_acl": 1.0,
                    "post_guard": 1.0,
                    "ledger": 1.0,
                    "response_selection": 1.0,
                    "post_grounding": 1.0,
                    "final": 1.0,
                },
                "first_loss_stage": "ARBITRARY_FAILURE_LABEL",
                "query_analysis_underspecified": True,
                "ledger_false_completeness": False,
            }
        )


def test_multidoc_diagnostics_do_not_change_agent_response() -> None:
    articles = [
        _article("a" * 64, "Access steps include account settings."),
        _article("b" * 64, "Billing steps include the invoice page."),
    ]
    ranking = [item.source_native_id for item in articles]
    chunks = [_chunk(item) for item in articles]
    common = {
        "rank_articles": lambda _query: ranking,
        "articles": articles,
        "chunks": chunks,
        "index_run_id": "fixture-index",
        "manifest_sha256": "f" * 64,
    }
    normal_nav = WixQARankedNavigator(**common)
    normal = V2AgentRunner(
        registry=V2ToolRegistry(normal_nav), budget=_budget()
    ).run("What access steps are required?", _user(), top_k=2)

    diagnostic_nav = RecordingWixQANavigator(**common)
    diagnostic, capture = run_recorded_agent(
        question="What access steps are required?",
        user=_user(),
        navigator=diagnostic_nav,
        budget=_budget(),
        top_k=2,
    )

    assert diagnostic.mode == normal.mode
    assert diagnostic.answer == normal.answer
    assert diagnostic.claims == normal.claims
    assert diagnostic.citations == normal.citations
    assert diagnostic.sources == normal.sources
    assert diagnostic.stop_reason == normal.stop_reason
    assert diagnostic.trace["budget"] == normal.trace["budget"]
    assert diagnostic_nav.searched_article_ids() == normal_nav.searched_article_ids()
    assert capture.response_selected_document_ids == ["a" * 64]
    assert diagnostic.trace["steps"][0]["retrieved_content_security"] == (
        normal.trace["steps"][0]["retrieved_content_security"]
    )


def test_multidoc_stage_ids_are_deterministic() -> None:
    articles = [_article("a" * 64, "Access steps include account settings.")]
    common = {
        "rank_articles": lambda _query: ["a" * 64],
        "articles": articles,
        "chunks": [_chunk(articles[0])],
        "index_run_id": "fixture-index",
        "manifest_sha256": "f" * 64,
    }
    observed = []
    for _ in range(2):
        response, capture = run_recorded_agent(
            question="What access steps are required?",
            user=_user(),
            navigator=RecordingWixQANavigator(**common),
            budget=_budget(),
        )
        observed.append(
            (
                [source.doc_id for source in response.sources],
                capture.response_selected_document_ids,
                [decision.action.tool for decision in capture.decisions],
            )
        )
    assert observed[0] == observed[1]
