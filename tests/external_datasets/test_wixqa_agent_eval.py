from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.agent.runner_v2 import V2AgentRunner
from app.agent.tools_v2 import V2ToolRegistry
from app.domain.enterprise_documents import EnterpriseDocument, RawProvenance
from app.domain.queries import UserContext
from app.external_datasets.wixqa import WixQAQuestion
from app.external_datasets.wixqa_agent_eval import (
    WixQARankedNavigator,
    score_wixqa_agent_case,
    summarize_wixqa_agent_cases,
)
from app.external_datasets.wixqa_retrieval import WixQAFlatChunk
from scripts.publish_wixqa_agent_eval import build_public_evidence


ROOT = Path(__file__).resolve().parents[2]


def _article(article_id: str, title: str, text: str) -> EnterpriseDocument:
    raw_hash = hashlib.sha256(text.encode()).hexdigest()
    return EnterpriseDocument(
        document_id=f"wixqa:{article_id}",
        source_type="wix_kb_article",
        source_native_id=article_id,
        title=title,
        text=text,
        raw_provenance=RawProvenance(
            dataset_name="WixQA",
            source_revision="a" * 40,
            source_file="corpus.jsonl",
            source_row=1,
            source_native_id=article_id,
            raw_record_sha256=raw_hash,
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


def test_wixqa_navigator_runs_through_real_agent_tool_boundary() -> None:
    articles = [
        _article("article-a", "Reset access", "Reset access from account settings."),
        _article("article-b", "Billing", "Invoices are available in billing."),
    ]
    navigator = WixQARankedNavigator(
        rank_articles=lambda _query: ["article-a", "article-b"],
        articles=articles,
        chunks=[_chunk(item) for item in articles],
        index_run_id="fixture-index",
        manifest_sha256="b" * 64,
    )
    user = UserContext(
        user_id="evaluator",
        tenant_id="wixqa-public",
        region="global",
        groups=["public"],
    )
    response = V2AgentRunner(registry=V2ToolRegistry(navigator)).run(
        "How to reset access?", user, top_k=2
    )
    assert response.trace["budget"]["search_calls"] == 1
    assert navigator.searched_article_ids() == ["article-a", "article-b"]
    assert response.sources[0].doc_id == "article-a"


def test_agent_scoring_separates_search_and_citation_coverage() -> None:
    question = WixQAQuestion(
        question_id="wixqa:simulated:aaaaaaaaaaaaaaaaaaaaaaaa",
        cohort="simulated",
        source_row=1,
        question="List all required articles",
        answer="Use both articles.",
        article_ids=["article-a", "article-b"],
        raw_record_sha256="c" * 64,
    )
    case = score_wixqa_agent_case(
        question,
        cohort="fixture",
        b2_ranked_article_ids=["article-a", "article-b"],
        searched_article_ids=["article-a", "article-b"],
        cited_article_ids=["article-a"],
        response_mode="answered",
        stop_reason="complete",
        trace={
            "budget": {"search_calls": 1, "find_calls": 0, "open_calls": 1},
            "steps": [{"tool": "search"}, {"tool": "open"}, {"tool": "answer"}],
        },
        b2_latency_ms=10,
        agent_latency_ms=15,
    )
    assert case.search_evidence_recall == 1.0
    assert case.citation_precision == 1.0
    assert case.citation_recall == 0.5
    assert case.citation_complete == 0.0
    summary = summarize_wixqa_agent_cases([case], cohort="fixture")
    assert summary.multi_article_citation_complete == 0.0
    assert summary.latency_ratio_p95 == 1.5


def test_agent_protocol_matches_pinned_question_ids() -> None:
    protocol = json.loads(
        (
            ROOT
            / "docs"
            / "enterprise_eval"
            / "evidence"
            / "WIXQA_AGENT_PROTOCOL_V1.json"
        ).read_text(encoding="utf-8")
    )
    assert protocol["cohorts"]["simulated"]["question_ids_sha256"] == (
        "871550a19297d3c267f03f2d819f0fd1cef566a8e3c11fdb92ea18792d71b465"
    )
    assert protocol["cohorts"]["expertwritten"]["question_ids_sha256"] == (
        "ec11e3e4733bd6701441b127952fa98b0973f9961a0aacabfae570da45976110"
    )


def test_agent_publication_rejects_debug_runs() -> None:
    run = {
        "mode": "PIPELINE_DEBUG",
        "cohort": "simulated",
        "case_count": 200,
        "claim_boundary": {"answer_correctness": "NOT_MEASURED"},
        "code_revision": "a" * 40,
    }
    with pytest.raises(ValueError, match="not a fixed missing-arm run"):
        build_public_evidence(
            run,
            {**run, "cohort": "expertwritten"},
            simulated_private_sha256="b" * 64,
            expertwritten_private_sha256="c" * 64,
        )
