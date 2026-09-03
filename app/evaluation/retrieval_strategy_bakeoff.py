"""Deterministic retrieval-strategy primitives for the offline WixQA bake-off.

This module deliberately has no serving dependency.  It evaluates alternative
ways to select five articles from the already-produced hybrid RRF ranking.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from app.external_datasets.wixqa_retrieval import LoadedWixQAFlatIndex


DIVERSITY_ALPHA = 0.75


def reciprocal_rank_fusion_scores(
    bm25_articles: Sequence[str],
    dense_articles: Sequence[str],
    *,
    rrf_k: int = 60,
) -> list[tuple[str, float]]:
    """Return the existing RRF ordering together with its deterministic score."""
    if rrf_k < 1:
        raise ValueError("rrf_k must be positive")
    scores: dict[str, float] = {}
    source_ranks: dict[str, tuple[int, int]] = {}
    for source_index, ranking in enumerate((bm25_articles, dense_articles)):
        for rank, article_id in enumerate(ranking, start=1):
            scores[article_id] = scores.get(article_id, 0.0) + 1.0 / (rrf_k + rank)
            previous = list(source_ranks.get(article_id, (10**9, 10**9)))
            previous[source_index] = rank
            source_ranks[article_id] = (previous[0], previous[1])
    return [
        (article_id, scores[article_id])
        for article_id in sorted(
            scores,
            key=lambda item: (
                -scores[item],
                min(source_ranks[item]),
                source_ranks[item],
                item,
            ),
        )
    ]


def fuse_ranked_lists(rankings: Sequence[Sequence[str]], *, rrf_k: int = 60) -> list[str]:
    """Fuse two or more complete rankings with deterministic multi-query RRF."""
    if len(rankings) < 1 or rrf_k < 1:
        raise ValueError("rankings and rrf_k must be positive")
    scores: dict[str, float] = {}
    first_positions: dict[str, tuple[int, int]] = {}
    for list_index, ranking in enumerate(rankings):
        for rank, article_id in enumerate(ranking, start=1):
            scores[article_id] = scores.get(article_id, 0.0) + 1.0 / (rrf_k + rank)
            first_positions.setdefault(article_id, (list_index, rank))
    return sorted(
        scores,
        key=lambda article_id: (-scores[article_id], first_positions[article_id], article_id),
    )


def representative_article_vectors(
    index: LoadedWixQAFlatIndex,
    *,
    article_ids: Sequence[str],
    query_vector: np.ndarray,
) -> dict[str, np.ndarray]:
    """Choose each article's query-most-similar stored chunk vector.

    The FAISS index stores L2-normalized BGE chunk embeddings.  Reconstructing
    only chunks belonging to the small RRF window avoids a second corpus
    embedding pass while keeping diversity comparisons on the same vector space.
    """
    query = _normalized_vector(query_vector)
    requested = list(dict.fromkeys(article_ids))
    known = {chunk.article_id for chunk in index.chunks}
    unknown = set(requested).difference(known)
    if unknown:
        raise ValueError("article IDs are not present in the WixQA index")

    positions_by_article: dict[str, list[int]] = {article_id: [] for article_id in requested}
    for position, chunk in enumerate(index.chunks):
        if chunk.article_id in positions_by_article:
            positions_by_article[chunk.article_id].append(position)

    result: dict[str, np.ndarray] = {}
    for article_id in requested:
        positions = positions_by_article[article_id]
        if not positions:
            raise ValueError("article has no chunks in the WixQA index")
        vectors = np.asarray(
            [index.faiss_index.reconstruct(position) for position in positions],
            dtype="float32",
        )
        vectors = _normalized_rows(vectors)
        best = int(np.argmax(vectors @ query))
        result[article_id] = vectors[best]
    return result


def select_diverse_articles(
    candidate_article_ids: Sequence[str],
    *,
    article_vectors: Mapping[str, np.ndarray],
    final_k: int = 5,
    alpha: float = DIVERSITY_ALPHA,
) -> list[str]:
    """Greedily choose high-ranked, non-redundant articles from an RRF window.

    Relevance is reciprocal RRF position (1/rank); redundancy is the maximum
    cosine similarity to an item already selected.  Stable article-id ties make
    the selector deterministic for a fixed RRF ranking and index.
    """
    candidates = list(dict.fromkeys(candidate_article_ids))
    if not candidates:
        raise ValueError("diversity selector requires candidates")
    if not 1 <= final_k <= len(candidates):
        raise ValueError("final_k must fit candidate list")
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must be between zero and one")
    missing = set(candidates).difference(article_vectors)
    if missing:
        raise ValueError("diversity selector lacks candidate vectors")
    vectors = {article_id: _normalized_vector(article_vectors[article_id]) for article_id in candidates}
    original_rank = {article_id: rank for rank, article_id in enumerate(candidates, start=1)}
    selected: list[str] = []
    remaining = set(candidates)
    while len(selected) < final_k:
        def score(article_id: str) -> tuple[float, str]:
            relevance = 1.0 / original_rank[article_id]
            redundancy = max(
                (float(vectors[article_id] @ vectors[chosen]) for chosen in selected),
                default=0.0,
            )
            return (alpha * relevance - (1.0 - alpha) * redundancy, article_id)

        # max score, then lexicographically smallest article ID for exact ties.
        winner = min(remaining, key=lambda article_id: (-score(article_id)[0], score(article_id)[1]))
        selected.append(winner)
        remaining.remove(winner)
    return selected


def _normalized_vector(vector: np.ndarray) -> np.ndarray:
    rows = _normalized_rows(np.asarray(vector, dtype="float32"))
    if rows.shape[0] != 1:
        raise ValueError("expected exactly one query or article vector")
    return rows[0]


def _normalized_rows(matrix: np.ndarray) -> np.ndarray:
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2 or not matrix.size or not np.isfinite(matrix).all():
        raise ValueError("vectors must be finite and non-empty")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("vectors must not be zero")
    return np.asarray(matrix / norms, dtype="float32")


__all__ = [
    "DIVERSITY_ALPHA",
    "fuse_ranked_lists",
    "reciprocal_rank_fusion_scores",
    "representative_article_vectors",
    "select_diverse_articles",
]
