from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.external_datasets.wixqa_retrieval import WixQAArticleCandidate
from app.security.retrieved_content import RetrievedContentGuard

MAX_WIXQA_RERANK_ARTICLES = 50
MAX_WIXQA_CHUNKS_PER_ARTICLE = 2
MAX_WIXQA_RERANK_CHUNKS = MAX_WIXQA_RERANK_ARTICLES * MAX_WIXQA_CHUNKS_PER_ARTICLE
MAX_WIXQA_RERANK_TEXT_CHARS = 1200
MAX_WIXQA_RAW_RERANK_CHUNKS = 50


class WixQAChunkScoreFn(Protocol):
    def __call__(
        self,
        question: str,
        candidate_texts: Sequence[str],
    ) -> Sequence[float]: ...


@dataclass(frozen=True)
class WixQAArticleChunkRerankResult:
    ranked_article_ids: tuple[str, ...]
    article_scores: tuple[tuple[str, float], ...]
    admitted_chunk_count: int
    quarantined_chunk_count: int
    guard_rule_ids: tuple[str, ...]


class WixQAArticleChunkReranker:
    """Offline article reranker that aggregates independent chunk scores by max."""

    def __init__(
        self,
        *,
        model_id: str,
        score_fn: WixQAChunkScoreFn,
        guard: RetrievedContentGuard | None = None,
    ) -> None:
        if not model_id.strip():
            raise ValueError("WixQA reranker model ID must be non-empty")
        self.model_id = model_id.strip()
        self.score_fn = score_fn
        self.guard = guard or RetrievedContentGuard()

    def rerank(
        self,
        *,
        question: str,
        candidates: Sequence[WixQAArticleCandidate],
    ) -> WixQAArticleChunkRerankResult:
        normalized_question = question.strip()
        rows = list(candidates)
        if not normalized_question or len(normalized_question) > 1000:
            raise ValueError("WixQA reranker question must contain 1-1000 characters")
        if not 1 <= len(rows) <= MAX_WIXQA_RERANK_CHUNKS:
            raise ValueError("WixQA reranker requires 1-100 article chunks")

        chunk_ids = [item.chunk_id for item in rows]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("WixQA reranker chunk IDs must be unique")

        article_order: list[str] = []
        chunk_counts: dict[str, int] = {}
        for item in rows:
            if item.article_id not in chunk_counts:
                article_order.append(item.article_id)
                chunk_counts[item.article_id] = 0
            chunk_counts[item.article_id] += 1
        if len(article_order) > MAX_WIXQA_RERANK_ARTICLES:
            raise ValueError("WixQA reranker supports at most 50 articles")
        if any(count > MAX_WIXQA_CHUNKS_PER_ARTICLE for count in chunk_counts.values()):
            raise ValueError("WixQA reranker supports at most two chunks per article")

        admitted: list[WixQAArticleCandidate] = []
        rule_ids: set[str] = set()
        for item in rows:
            decision = self.guard.scan(item.text)
            rule_ids.update(decision.rule_ids)
            if decision.disposition == "ADMIT":
                admitted.append(item)
        if not admitted:
            raise ValueError("WixQA reranker guard quarantined every candidate")

        raw_scores = self.score_fn(
            normalized_question,
            [item.text[:MAX_WIXQA_RERANK_TEXT_CHARS] for item in admitted],
        )
        scores = [float(item) for item in raw_scores]
        if len(scores) != len(admitted):
            raise ValueError("WixQA cross-encoder returned the wrong score count")
        if any(not math.isfinite(item) for item in scores):
            raise ValueError("WixQA cross-encoder scores must be finite")

        max_scores: dict[str, float] = {}
        for item, score in zip(admitted, scores, strict=True):
            max_scores[item.article_id] = max(max_scores.get(item.article_id, -math.inf), score)
        dense_rank = {article_id: rank for rank, article_id in enumerate(article_order)}
        ranked = sorted(
            max_scores, key=lambda article_id: (-max_scores[article_id], dense_rank[article_id])
        )
        return WixQAArticleChunkRerankResult(
            ranked_article_ids=tuple(ranked),
            article_scores=tuple((article_id, max_scores[article_id]) for article_id in ranked),
            admitted_chunk_count=len(admitted),
            quarantined_chunk_count=len(rows) - len(admitted),
            guard_rule_ids=tuple(sorted(rule_ids)),
        )


class WixQARawChunkReranker:
    """Guard and rerank raw dense chunks before deduplicating articles."""

    def __init__(
        self,
        *,
        model_id: str,
        score_fn: WixQAChunkScoreFn,
        guard: RetrievedContentGuard | None = None,
    ) -> None:
        if not model_id.strip():
            raise ValueError("WixQA reranker model ID must be non-empty")
        self.model_id = model_id.strip()
        self.score_fn = score_fn
        self.guard = guard or RetrievedContentGuard()

    def rerank(
        self,
        *,
        question: str,
        candidates: Sequence[WixQAArticleCandidate],
    ) -> WixQAArticleChunkRerankResult:
        normalized_question = question.strip()
        rows = list(candidates)
        if not normalized_question or len(normalized_question) > 1000:
            raise ValueError("WixQA reranker question must contain 1-1000 characters")
        if not 1 <= len(rows) <= MAX_WIXQA_RAW_RERANK_CHUNKS:
            raise ValueError("WixQA raw reranker requires 1-50 chunks")
        chunk_ids = [item.chunk_id for item in rows]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("WixQA reranker chunk IDs must be unique")

        admitted: list[WixQAArticleCandidate] = []
        rule_ids: set[str] = set()
        for item in rows:
            decision = self.guard.scan(item.text)
            rule_ids.update(decision.rule_ids)
            if decision.disposition == "ADMIT":
                admitted.append(item)
        if not admitted:
            raise ValueError("WixQA reranker guard quarantined every candidate")

        raw_scores = self.score_fn(
            normalized_question,
            # Raw chunks are Guard-scanned in full. The pinned cross-encoder
            # tokenizer, rather than an unrelated character limit, owns
            # truncation for the selected GPU quality profile.
            [item.text for item in admitted],
        )
        scores = [float(item) for item in raw_scores]
        if len(scores) != len(admitted):
            raise ValueError("WixQA cross-encoder returned the wrong score count")
        if any(not math.isfinite(item) for item in scores):
            raise ValueError("WixQA cross-encoder scores must be finite")

        dense_chunk_rank = {item.chunk_id: rank for rank, item in enumerate(rows)}
        ranked_chunks = sorted(
            zip(admitted, scores, strict=True),
            key=lambda item: (-item[1], dense_chunk_rank[item[0].chunk_id]),
        )
        ranked_articles: list[str] = []
        article_scores: list[tuple[str, float]] = []
        seen: set[str] = set()
        for item, score in ranked_chunks:
            if item.article_id in seen:
                continue
            seen.add(item.article_id)
            ranked_articles.append(item.article_id)
            article_scores.append((item.article_id, score))
        return WixQAArticleChunkRerankResult(
            ranked_article_ids=tuple(ranked_articles),
            article_scores=tuple(article_scores),
            admitted_chunk_count=len(admitted),
            quarantined_chunk_count=len(rows) - len(admitted),
            guard_rule_ids=tuple(sorted(rule_ids)),
        )


__all__ = [
    "MAX_WIXQA_CHUNKS_PER_ARTICLE",
    "MAX_WIXQA_RERANK_ARTICLES",
    "MAX_WIXQA_RERANK_CHUNKS",
    "MAX_WIXQA_RAW_RERANK_CHUNKS",
    "WixQAArticleChunkRerankResult",
    "WixQAArticleChunkReranker",
    "WixQARawChunkReranker",
]
