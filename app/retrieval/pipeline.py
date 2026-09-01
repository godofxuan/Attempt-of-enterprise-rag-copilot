from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from app.domain.documents import ChunkRecord
from app.domain.queries import (
    QueryFilters,
    RetrievalMode,
    SearchHit,
    SearchRequest,
    SearchResult,
    SearchStopReason,
)
from app.retrieval.snapshot import V2IndexSnapshot
from app.security.access import AccessPolicy
from app.utils import tokenize_for_bm25

EmbedText = Callable[[str], list[float]]


@dataclass(frozen=True)
class _RankedCandidate:
    index: int
    fused_score: float
    dense_score: float | None
    bm25_score: float | None
    dense_rank: int | None
    bm25_rank: int | None


@dataclass(frozen=True)
class _VisibleScope:
    acl_indices: tuple[int, ...]
    metadata_indices: tuple[int, ...]
    denied_count: int


@dataclass(frozen=True)
class RankedSearchCandidate:
    rank: int
    hit: SearchHit
    document_title: str | None


@dataclass(frozen=True)
class RankedSearchPool:
    request_id: str
    query: str
    mode: RetrievalMode
    index_run_id: str
    manifest_sha256: str
    candidates: tuple[RankedSearchCandidate, ...]
    visible_candidate_count: int
    internal_denied_count: int
    stage_counts: dict[str, int]
    stop_reason: SearchStopReason


class HybridRetrievalPipeline:
    def __init__(
        self,
        snapshot: V2IndexSnapshot,
        *,
        embed_text: EmbedText | None = None,
        access_policy: AccessPolicy | None = None,
        rrf_k: int = 60,
    ) -> None:
        if rrf_k < 1:
            raise ValueError("rrf_k must be at least 1")
        self.snapshot = snapshot
        self.embed_text = embed_text
        self.access_policy = access_policy or AccessPolicy()
        self.rrf_k = rrf_k

    def search(self, request: SearchRequest) -> SearchResult:
        return self._search(
            request,
            query_vectors=None,
            bm25_score_cache=None,
            dense_search_cache=None,
        )

    def search_many(self, requests: list[SearchRequest]) -> list[SearchResult]:
        query_vectors: dict[str, np.ndarray] = {}
        bm25_score_cache: dict[str, np.ndarray] = {}
        dense_search_cache: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        return [
            self._search(
                request,
                query_vectors=query_vectors,
                bm25_score_cache=bm25_score_cache,
                dense_search_cache=dense_search_cache,
            )
            for request in requests
        ]

    def search_many_same_scope(self, requests: list[SearchRequest]) -> list[SearchResult]:
        if not requests:
            return []
        first = requests[0]
        if any(
            request.user != first.user or request.filters != first.filters
            for request in requests[1:]
        ):
            raise ValueError("same-scope search requires identical user and filters")
        visible_scope = self._resolve_visible_scope(first)
        query_vectors: dict[str, np.ndarray] = {}
        dense_search_cache: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        return [
            self._search(
                request,
                query_vectors=query_vectors,
                bm25_score_cache=None,
                dense_search_cache=dense_search_cache,
                visible_scope=visible_scope,
            )
            for request in requests
        ]

    def _search(
        self,
        request: SearchRequest,
        *,
        query_vectors: dict[str, np.ndarray] | None,
        bm25_score_cache: dict[str, np.ndarray] | None,
        dense_search_cache: dict[str, tuple[np.ndarray, np.ndarray]] | None,
        visible_scope: _VisibleScope | None = None,
    ) -> SearchResult:
        pool = self.ranked_candidates_for_guard(
            request,
            query_vectors=query_vectors,
            bm25_score_cache=bm25_score_cache,
            dense_search_cache=dense_search_cache,
            visible_scope=visible_scope,
        )
        selected = self._select_diverse_ranked(
            pool.candidates,
            top_k=request.top_k,
            max_chunks_per_doc=request.max_chunks_per_doc,
        )
        hits = [candidate.hit for candidate in selected]
        stage_counts = {**pool.stage_counts, "returned": len(hits)}
        stop_reason: SearchStopReason = pool.stop_reason
        if stop_reason == "ok" and not hits:
            stop_reason = "no_match"
        return SearchResult(
            request_id=pool.request_id,
            query=pool.query,
            mode=pool.mode,
            index_run_id=pool.index_run_id,
            manifest_sha256=pool.manifest_sha256,
            hits=hits,
            visible_candidate_count=pool.visible_candidate_count,
            internal_denied_count=pool.internal_denied_count,
            stage_counts=stage_counts,
            stop_reason=stop_reason,
        )

    def ranked_candidates_for_guard(
        self,
        request: SearchRequest,
        *,
        query_vectors: dict[str, np.ndarray] | None = None,
        bm25_score_cache: dict[str, np.ndarray] | None = None,
        dense_search_cache: dict[str, tuple[np.ndarray, np.ndarray]] | None = None,
        visible_scope: _VisibleScope | None = None,
    ) -> RankedSearchPool:
        started = time.perf_counter()
        scope = visible_scope or self._resolve_visible_scope(request)
        acl_indices = scope.acl_indices
        metadata_indices = scope.metadata_indices
        denied_count = scope.denied_count
        stage_counts = {
            "acl_visible": len(acl_indices),
            "metadata_visible": len(metadata_indices),
            "bm25_candidates": 0,
            "dense_candidates": 0,
            "fused_candidates": 0,
            "returned": 0,
        }
        if not metadata_indices:
            stop_reason = "no_visible_evidence" if not acl_indices and denied_count else "no_match"
            return self._empty_pool(
                request,
                denied_count=denied_count,
                stage_counts=stage_counts,
                stop_reason=stop_reason,
            )

        bm25_ranked: list[tuple[int, float]] = []
        dense_ranked: list[tuple[int, float]] = []
        if request.mode in {"bm25", "hybrid"}:
            bm25_ranked = (
                self._rank_bm25(
                    request.query,
                    metadata_indices,
                    request.candidate_k,
                )
                if bm25_score_cache is None
                else self._rank_bm25(
                    request.query,
                    metadata_indices,
                    request.candidate_k,
                    score_cache=bm25_score_cache,
                )
            )
            stage_counts["bm25_candidates"] = len(bm25_ranked)
        if request.mode in {"dense", "hybrid"}:
            dense_ranked = (
                self._rank_dense(
                    request.query,
                    metadata_indices,
                    request.candidate_k,
                )
                if query_vectors is None
                else self._rank_dense(
                    request.query,
                    metadata_indices,
                    request.candidate_k,
                    query_vectors=query_vectors,
                    search_cache=dense_search_cache,
                )
            )
            stage_counts["dense_candidates"] = len(dense_ranked)

        candidates = self._fuse(
            mode=request.mode,
            bm25_ranked=bm25_ranked,
            dense_ranked=dense_ranked,
        )
        stage_counts["fused_candidates"] = len(candidates)
        candidates = candidates[: request.candidate_k]
        ranked_candidates = tuple(
            RankedSearchCandidate(
                rank=rank,
                hit=self._to_hit(candidate, request),
                document_title=self._document_title(candidate),
            )
            for rank, candidate in enumerate(candidates, start=1)
        )

        elapsed_ms = (time.perf_counter() - started) * 1000
        if elapsed_ms > request.timeout_ms:
            return self._empty_pool(
                request,
                denied_count=denied_count,
                stage_counts={**stage_counts, "returned": 0},
                stop_reason="timeout",
            )
        if not ranked_candidates:
            return self._empty_pool(
                request,
                denied_count=denied_count,
                stage_counts=stage_counts,
                stop_reason="no_match",
            )
        return RankedSearchPool(
            request_id=request.request_id,
            query=request.query,
            mode=request.mode,
            index_run_id=self.snapshot.version.manifest.run_id,
            manifest_sha256=self.snapshot.version.manifest_sha256,
            candidates=ranked_candidates,
            visible_candidate_count=len(metadata_indices),
            internal_denied_count=denied_count,
            stage_counts=stage_counts,
            stop_reason="ok",
        )

    def _resolve_visible_scope(self, request: SearchRequest) -> _VisibleScope:
        acl_indices, denied_count = self.access_policy.visible_indices(
            request.user,
            self.snapshot.chunks,
        )
        metadata_indices = tuple(
            index
            for index in acl_indices
            if _matches_filters(self.snapshot.chunks[index], request.filters)
        )
        return _VisibleScope(
            acl_indices=tuple(acl_indices),
            metadata_indices=metadata_indices,
            denied_count=denied_count,
        )

    def _rank_bm25(
        self,
        query: str,
        visible_indices: Sequence[int],
        candidate_k: int,
        *,
        score_cache: dict[str, np.ndarray] | None = None,
    ) -> list[tuple[int, float]]:
        scores = score_cache.get(query) if score_cache is not None else None
        query_tokens = tokenize_for_bm25(query)
        if scores is None and score_cache is None:
            batch_indices = list(visible_indices)
            visible_scores = self.snapshot.bm25.get_batch_scores(
                query_tokens,
                batch_indices,
            )
            score_by_index = dict(zip(batch_indices, visible_scores, strict=True))
        else:
            if scores is None:
                assert score_cache is not None
                scores = np.asarray(self.snapshot.bm25.get_scores(query_tokens))
                score_cache[query] = scores
            score_by_index = {index: float(scores[index]) for index in visible_indices}
        ranked = sorted(
            visible_indices,
            key=lambda index: (
                -score_by_index[index],
                self.snapshot.chunks[index].chunk_id,
            ),
        )
        return [(index, score_by_index[index]) for index in ranked[:candidate_k]]

    def _rank_dense(
        self,
        query: str,
        visible_indices: Sequence[int],
        candidate_k: int,
        *,
        query_vectors: dict[str, np.ndarray] | None = None,
        search_cache: dict[str, tuple[np.ndarray, np.ndarray]] | None = None,
    ) -> list[tuple[int, float]]:
        vector = query_vectors.get(query) if query_vectors is not None else None
        if vector is None:
            vector = self._normalized_query_vector(query)
            if query_vectors is not None:
                query_vectors[query] = vector
        search_result = search_cache.get(query) if search_cache is not None else None
        if search_result is None:
            search_result = self.snapshot.faiss_index.search(
                vector,
                self.snapshot.faiss_index.ntotal,
            )
            if search_cache is not None:
                search_cache[query] = search_result
        scores, indices = search_result
        visible = set(visible_indices)
        ranked: list[tuple[int, float]] = []
        for index, score in zip(
            indices[0].tolist(),
            scores[0].tolist(),
            strict=True,
        ):
            if index == -1 or index not in visible:
                continue
            ranked.append((index, float(score)))
            if len(ranked) == candidate_k:
                break
        return ranked

    def _normalized_query_vector(self, query: str) -> np.ndarray:
        if self.embed_text is None:
            raise ValueError("dense retrieval requires an embed_text function")
        vector = np.asarray(self.embed_text(query), dtype="float32")
        expected = self.snapshot.version.manifest.embedding.dimension
        if vector.ndim != 1 or len(vector) != expected:
            raise ValueError(
                f"query embedding dimension mismatch: expected {expected}, got {vector.shape}"
            )
        if not np.isfinite(vector).all():
            raise ValueError("query embedding contains non-finite values")
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            raise ValueError("query embedding must not be a zero vector")
        return (vector / norm).reshape(1, -1)

    def _fuse(
        self,
        *,
        mode: str,
        bm25_ranked: list[tuple[int, float]],
        dense_ranked: list[tuple[int, float]],
    ) -> list[_RankedCandidate]:
        bm25 = {index: (rank, score) for rank, (index, score) in enumerate(bm25_ranked, start=1)}
        dense = {index: (rank, score) for rank, (index, score) in enumerate(dense_ranked, start=1)}
        indices = (
            set(bm25)
            if mode == "bm25"
            else set(dense)
            if mode == "dense"
            else set(bm25) | set(dense)
        )
        candidates: list[_RankedCandidate] = []
        for index in indices:
            bm25_rank, bm25_score = bm25.get(index, (None, None))
            dense_rank, dense_score = dense.get(index, (None, None))
            if mode == "bm25":
                assert bm25_score is not None
                fused_score = float(bm25_score)
            elif mode == "dense":
                assert dense_score is not None
                fused_score = float(dense_score)
            else:
                fused_score = 0.0
                if bm25_rank is not None:
                    fused_score += 1.0 / (self.rrf_k + bm25_rank)
                if dense_rank is not None:
                    fused_score += 1.0 / (self.rrf_k + dense_rank)
            candidates.append(
                _RankedCandidate(
                    index=index,
                    fused_score=fused_score,
                    dense_score=dense_score,
                    bm25_score=bm25_score,
                    dense_rank=dense_rank,
                    bm25_rank=bm25_rank,
                )
            )
        return sorted(candidates, key=self._candidate_sort_key)

    def _candidate_sort_key(self, candidate: _RankedCandidate) -> tuple:
        chunk = self.snapshot.chunks[candidate.index]
        return (
            -candidate.fused_score,
            -chunk.authority_level,
            0 if chunk.status == "active" else 1,
            chunk.chunk_id,
        )

    def _select_diverse_ranked(
        self,
        candidates: tuple[RankedSearchCandidate, ...],
        *,
        top_k: int,
        max_chunks_per_doc: int,
    ) -> list[RankedSearchCandidate]:
        selected: list[RankedSearchCandidate] = []
        per_doc: Counter[str] = Counter()
        for candidate in candidates:
            doc_id = candidate.hit.doc_id
            if per_doc[doc_id] >= max_chunks_per_doc:
                continue
            per_doc[doc_id] += 1
            selected.append(candidate)
            if len(selected) == top_k:
                break
        return selected

    def _document_title(self, candidate: _RankedCandidate) -> str | None:
        doc_id = self.snapshot.chunks[candidate.index].doc_id
        document = self.snapshot.documents_by_id.get(doc_id)
        return document.title if document is not None else None

    def _to_hit(
        self,
        candidate: _RankedCandidate,
        request: SearchRequest,
    ) -> SearchHit:
        chunk = self.snapshot.chunks[candidate.index]
        context_text = chunk.text
        context_from_parent = False
        if request.include_parent and chunk.parent_chunk_id:
            parent = self.snapshot.parents_by_id.get(chunk.parent_chunk_id)
            if (
                parent is not None
                and parent.doc_id == chunk.doc_id
                and self.access_policy.evaluate(request.user, parent).allowed
                and _matches_filters(parent, request.filters)
            ):
                context_text = parent.text
                context_from_parent = True
        return SearchHit(
            index_run_id=self.snapshot.version.manifest.run_id,
            chunk_id=chunk.chunk_id,
            doc_id=chunk.doc_id,
            parent_chunk_id=chunk.parent_chunk_id,
            policy_id=chunk.policy_id,
            source_path=chunk.source_path,
            section_path=chunk.section_path,
            locator=chunk.locator,
            matched_text=chunk.text,
            context_text=context_text,
            context_from_parent=context_from_parent,
            tenant_id=chunk.tenant_id,
            region=chunk.region,
            acl_groups=chunk.acl_groups,
            version_id=chunk.version_id,
            version=chunk.version,
            status=chunk.status,
            authority_level=chunk.authority_level,
            variant=chunk.variant,
            fact_ids=chunk.fact_ids,
            fused_score=candidate.fused_score,
            dense_score=candidate.dense_score,
            bm25_score=candidate.bm25_score,
            dense_rank=candidate.dense_rank,
            bm25_rank=candidate.bm25_rank,
        )

    def _empty_pool(
        self,
        request: SearchRequest,
        *,
        denied_count: int,
        stage_counts: dict[str, int],
        stop_reason: str,
    ) -> RankedSearchPool:
        return RankedSearchPool(
            request_id=request.request_id,
            query=request.query,
            mode=request.mode,
            index_run_id=self.snapshot.version.manifest.run_id,
            manifest_sha256=self.snapshot.version.manifest_sha256,
            candidates=(),
            visible_candidate_count=stage_counts["metadata_visible"],
            internal_denied_count=denied_count,
            stage_counts=stage_counts,
            stop_reason=stop_reason,
        )


def _matches_filters(chunk: ChunkRecord, filters: QueryFilters) -> bool:
    if filters.departments and chunk.department not in filters.departments:
        return False
    if filters.policy_ids and chunk.policy_id not in filters.policy_ids:
        return False
    if filters.statuses and chunk.status not in filters.statuses:
        return False
    if filters.authoritative_only and chunk.variant != "authoritative":
        return False
    if chunk.authority_level < filters.min_authority:
        return False

    if filters.temporal_scope == "current":
        return chunk.status == "active"
    if filters.temporal_scope == "historical":
        return chunk.status == "retired"
    if filters.temporal_scope == "as_of":
        as_of = filters.as_of
        if as_of is None:
            return False
        return chunk.effective_from <= as_of and (
            chunk.effective_to is None or as_of < chunk.effective_to
        )
    return True


__all__ = [
    "HybridRetrievalPipeline",
    "RankedSearchCandidate",
    "RankedSearchPool",
]
