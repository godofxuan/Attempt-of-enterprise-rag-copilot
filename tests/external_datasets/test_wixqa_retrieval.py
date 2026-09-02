from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from app.domain.enterprise_documents import EnterpriseDocument, RawProvenance
from app.evaluation.wixqa_article_chunk_reranker import WixQAArticleChunkReranker
from app.external_datasets.wixqa import WIXQA_REVISION, WixQAQuestion
from app.external_datasets.wixqa_retrieval import (
    WixQAArticleCandidate,
    build_flat_chunks,
    build_wixqa_flat_index,
    load_wixqa_flat_index,
    merge_reranked_article_ids,
    reciprocal_rank_fusion,
    score_wixqa_ranking,
    summarize_wixqa_scores,
    verify_wixqa_flat_index,
)


def _article(article_id: str, text: str) -> EnterpriseDocument:
    raw_hash = hashlib.sha256(text.encode()).hexdigest()
    return EnterpriseDocument(
        document_id=f"wixqa:article:{article_id}",
        source_type="support_article",
        source_native_id=article_id,
        title=f"Title {article_id}",
        text=text,
        timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        raw_provenance=RawProvenance(
            dataset_name="WixQA",
            source_revision=WIXQA_REVISION,
            source_file="fixture.jsonl",
            source_row=1,
            source_native_id=article_id,
            raw_record_sha256=raw_hash,
        ),
    )


def _question() -> WixQAQuestion:
    return WixQAQuestion(
        question_id="wixqa:simulated:" + "a" * 24,
        cohort="simulated",
        source_row=1,
        question="question",
        answer="answer",
        article_ids=["a", "b"],
        raw_record_sha256="b" * 64,
    )


def test_flat_chunks_are_deterministic_and_repeat_title() -> None:
    articles = [_article("a", "0123456789")]
    first = build_flat_chunks(articles, chunk_size=6, overlap=2)
    second = build_flat_chunks(articles, chunk_size=6, overlap=2)
    assert first == second
    assert [item.ordinal for item in first] == [1, 2]
    assert all(item.text.startswith("Title a\n") for item in first)


def test_flat_chunk_configuration_is_bounded() -> None:
    with pytest.raises(ValueError, match="invalid"):
        build_flat_chunks([_article("a", "text")], chunk_size=5, overlap=5)


def test_rrf_rewards_cross_retriever_agreement() -> None:
    ranking = reciprocal_rank_fusion(["a", "b", "c"], ["b", "a", "d"])
    assert ranking[:2] == ["a", "b"]
    assert set(ranking) == {"a", "b", "c", "d"}


def test_multi_article_metrics_separate_hit_from_completeness() -> None:
    question = _question()
    partial = score_wixqa_ranking(
        question,
        arm="hybrid_rrf",
        ranked_article_ids=["a", "x", "y", "z", "q"],
        latency_ms=1.0,
    )
    complete = score_wixqa_ranking(
        question,
        arm="hybrid_rrf",
        ranked_article_ids=["x", "a", "b", "z", "q"],
        latency_ms=2.0,
    )
    assert partial.hit_at_1 == 1.0
    assert partial.recall_at_5 == 0.5
    assert partial.complete_at_5 == 0.0
    assert complete.recall_at_5 == 1.0
    assert complete.complete_at_5 == 1.0
    summary = summarize_wixqa_scores([partial, complete], cohort="simulated", arm="hybrid_rrf")
    assert summary.article_recall_at_5 == 0.75
    assert summary.multi_article_completeness_at_5 == 0.5


def test_flat_index_is_hash_bound_and_loadable(tmp_path: Path) -> None:
    articles = [
        _article("a", "alpha setup instructions"),
        _article("b", "beta billing instructions"),
    ]
    state: dict[str, str] = {}

    def embed(chunks):
        state["build_id"] = "c" * 64
        rows = []
        for chunk in chunks:
            rows.append(
                [
                    1.0 if "alpha" in chunk.text else 0.0,
                    1.0 if "beta" in chunk.text else 0.0,
                ]
            )
        return np.asarray(rows, dtype="float32")

    manifest = build_wixqa_flat_index(
        output_root=tmp_path,
        run_id="fixture-v1",
        articles=articles,
        dataset_manifest_sha256="a" * 64,
        embedding_model="fixture",
        embedding_model_sha256="b" * 64,
        embed_chunks=embed,
        embedding_cache_build_id=lambda: state["build_id"],
        chunk_size=100,
        overlap=10,
    )
    version = tmp_path / "versions" / "fixture-v1"
    assert verify_wixqa_flat_index(version) == manifest
    loaded = load_wixqa_flat_index(tmp_path)
    assert (
        loaded.dense_article_ranking(np.asarray([[0.0, 1.0]], dtype="float32"), candidate_k=2)[0]
        == "b"
    )
    candidates = loaded.dense_article_candidates(
        np.asarray([[0.0, 1.0]], dtype="float32"), candidate_k=2
    )
    assert [item.article_id for item in candidates] == ["b", "a"]
    assert candidates[0].chunk_id.startswith("wixqa:b:flat:")
    assert "beta billing" in candidates[0].text


def test_dense_article_chunk_candidates_keep_two_chunks_for_selected_articles(
    tmp_path: Path,
) -> None:
    articles = [
        _article("a", "alpha first evidence alpha second evidence"),
        _article("b", "beta only evidence"),
        _article("c", "gamma only evidence"),
    ]
    state: dict[str, str] = {}

    def embed(chunks):
        state["build_id"] = "d" * 64
        # Preserve deterministic chunk order while making both article-a chunks
        # rank inside the top candidate window.
        rows = []
        for index, _chunk in enumerate(chunks):
            rows.append([1.0, 1.0 / (index + 2)])
        return np.asarray(rows, dtype="float32")

    build_wixqa_flat_index(
        output_root=tmp_path,
        run_id="multi-chunk-fixture-v1",
        articles=articles,
        dataset_manifest_sha256="a" * 64,
        embedding_model="fixture",
        embedding_model_sha256="b" * 64,
        embed_chunks=embed,
        embedding_cache_build_id=lambda: state["build_id"],
        chunk_size=24,
        overlap=4,
    )
    loaded = load_wixqa_flat_index(tmp_path)

    candidates = loaded.dense_article_chunk_candidates(
        np.asarray([[1.0, 0.5]], dtype="float32"),
        candidate_k=10,
        max_articles=2,
        chunks_per_article=2,
    )

    assert len({item.article_id for item in candidates}) == 2
    assert [item.article_id for item in candidates].count("a") == 2
    assert all(
        [item.article_id for item in candidates].count(article_id) <= 2
        for article_id in {item.article_id for item in candidates}
    )


def test_article_chunk_reranker_uses_max_chunk_score_and_dense_tie_break() -> None:
    candidates = [
        # Article a has a weak first chunk but the strongest second chunk.
        ("a", "a-1", "weak"),
        ("a", "a-2", "answer evidence"),
        ("b", "b-1", "medium"),
        ("c", "c-1", "same score"),
    ]
    score_by_text = {
        "weak": 0.1,
        "answer evidence": 0.9,
        "medium": 0.5,
        "same score": 0.5,
    }
    reranker = WixQAArticleChunkReranker(
        model_id="fixture",
        score_fn=lambda _question, texts: [score_by_text[text] for text in texts],
    )

    result = reranker.rerank(
        question="question",
        candidates=[
            WixQAArticleCandidate(
                article_id=article_id,
                chunk_id=chunk_id,
                text=text,
                dense_score=1.0,
            )
            for article_id, chunk_id, text in candidates
        ],
    )

    assert result.ranked_article_ids == ("a", "b", "c")
    assert result.article_scores == (("a", 0.9), ("b", 0.5), ("c", 0.5))
    assert result.admitted_chunk_count == 4


def test_reranked_articles_preserve_dense_head_and_candidate_set() -> None:
    merged = merge_reranked_article_ids(
        dense_article_ids=["a", "b", "c", "d", "e"],
        reranked_article_ids=["c", "b"],
        reranker_top_n=3,
        dense_head_count=1,
    )
    assert merged == ["a", "c", "b", "d", "e"]

    with pytest.raises(ValueError, match="unknown"):
        merge_reranked_article_ids(
            dense_article_ids=["a", "b"],
            reranked_article_ids=["x"],
            reranker_top_n=2,
            dense_head_count=0,
        )
