from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from typing import Callable

import numpy as np

from app.domain.documents import ChunkRecord
from app.domain.queries import (
    QueryFilters,
    SearchHit,
    SearchRequest,
    SearchResult,
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
        started = time.perf_counter()
        acl_indices, denied_count = self.access_policy.visible_indices(
            request.user,
            self.snapshot.chunks,
        )
        metadata_indices = [
            index
            for index in acl_indices
            if _matches_filters(self.snapshot.chunks[index], request.filters)
        ]
        stage_counts = {
            "acl_visible": len(acl_indices),
            "metadata_visible": len(metadata_indices),
            "bm25_candidates": 0,
            "dense_candidates": 0,
            "fused_candidates": 0,
            "returned": 0,
        }
        if not metadata_indices:
            stop_reason = (
                "no_visible_evidence" if not acl_indices and denied_count else "no_match"
            )
            return self._empty_result(
                request,
                denied_count=denied_count,
                stage_counts=stage_counts,
                stop_reason=stop_reason,
            )

        bm25_ranked: list[tuple[int, float]] = []
        dense_ranked: list[tuple[int, float]] = []
        if request.mode in {"bm25", "hybrid"}:
            bm25_ranked = self._rank_bm25(
                request.query,
                metadata_indices,
                request.candidate_k,
            )
            stage_counts["bm25_candidates"] = len(bm25_ranked)
        if request.mode in {"dense", "hybrid"}:
            dense_ranked = self._rank_dense(
                request.query,
                metadata_indices,
                request.candidate_k,
            )
            stage_counts["dense_candidates"] = len(dense_ranked)

        candidates = self._fuse(
            mode=request.mode,
            bm25_ranked=bm25_ranked,
            dense_ranked=dense_ranked,
        )
        stage_counts["fused_candidates"] = len(candidates)
        selected = self._select_diverse(
            candidates,
            top_k=request.top_k,
            max_chunks_per_doc=request.max_chunks_per_doc,
        )
        hits = [self._to_hit(candidate, request) for candidate in selected]
        stage_counts["returned"] = len(hits)

        elapsed_ms = (time.perf_counter() - started) * 1000
        if elapsed_ms > request.timeout_ms:
            return self._empty_result(
                request,
                denied_count=denied_count,
                stage_counts={**stage_counts, "returned": 0},
                stop_reason="timeout",
            )
        if not hits:
            return self._empty_result(
                request,
                denied_count=denied_count,
                stage_counts=stage_counts,
                stop_reason="no_match",
            )
        return SearchResult(
            request_id=request.request_id,
            query=request.query,
            mode=request.mode,
            index_run_id=self.snapshot.version.manifest.run_id,
            manifest_sha256=self.snapshot.version.manifest_sha256,
            hits=hits,
            visible_candidate_count=len(metadata_indices),
            internal_denied_count=denied_count,
            stage_counts=stage_counts,
            stop_reason="ok",
        )

    def _rank_bm25(
        self,
        query: str,
        visible_indices: list[int],
        candidate_k: int,
    ) -> list[tuple[int, float]]:
        scores = self.snapshot.bm25.get_scores(tokenize_for_bm25(query))
        ranked = sorted(
            visible_indices,
            key=lambda index: (
                -float(scores[index]),
                self.snapshot.chunks[index].chunk_id,
            ),
        )
        return [(index, float(scores[index])) for index in ranked[:candidate_k]]

    def _rank_dense(
        self,
        query: str,
        visible_indices: list[int],
        candidate_k: int,
    ) -> list[tuple[int, float]]:
        if self.embed_text is None:
            raise ValueError("dense retrieval requires an embed_text function")
        vector = np.asarray(self.embed_text(query), dtype="float32")
        expected = self.snapshot.version.manifest.embedding.dimension
        if vector.ndim != 1 or len(vector) != expected:
            raise ValueError(
                f"query embedding dimension mismatch: expected {expected}, "
                f"got {vector.shape}"
            )
        if not np.isfinite(vector).all():
            raise ValueError("query embedding contains non-finite values")
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            raise ValueError("query embedding must not be a zero vector")
        vector = (vector / norm).reshape(1, -1)
        scores, indices = self.snapshot.faiss_index.search(
            vector,
            self.snapshot.faiss_index.ntotal,
        )
        visible = set(visible_indices)
        ranked: list[tuple[int, float]] = []
        for index, score in zip(indices[0].tolist(), scores[0].tolist()):
            if index == -1 or index not in visible:
                continue
            ranked.append((index, float(score)))
            if len(ranked) == candidate_k:
                break
        return ranked

    def _fuse(
        self,
        *,
        mode: str,
        bm25_ranked: list[tuple[int, float]],
        dense_ranked: list[tuple[int, float]],
    ) -> list[_RankedCandidate]:
        bm25 = {
            index: (rank, score)
            for rank, (index, score) in enumerate(bm25_ranked, start=1)
        }
        dense = {
            index: (rank, score)
            for rank, (index, score) in enumerate(dense_ranked, start=1)
        }
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
                fused_score = float(bm25_score)
            elif mode == "dense":
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

    def _select_diverse(
        self,
        candidates: list[_RankedCandidate],
        *,
        top_k: int,
        max_chunks_per_doc: int,
    ) -> list[_RankedCandidate]:
        selected: list[_RankedCandidate] = []
        per_doc: Counter[str] = Counter()
        for candidate in candidates:
            doc_id = self.snapshot.chunks[candidate.index].doc_id
            if per_doc[doc_id] >= max_chunks_per_doc:
                continue
            per_doc[doc_id] += 1
            selected.append(candidate)
            if len(selected) == top_k:
                break
        return selected

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

    def _empty_result(
        self,
        request: SearchRequest,
        *,
        denied_count: int,
        stage_counts: dict[str, int],
        stop_reason: str,
    ) -> SearchResult:
        return SearchResult(
            request_id=request.request_id,
            query=request.query,
            mode=request.mode,
            index_run_id=self.snapshot.version.manifest.run_id,
            manifest_sha256=self.snapshot.version.manifest_sha256,
            hits=[],
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


__all__ = ["HybridRetrievalPipeline"]
