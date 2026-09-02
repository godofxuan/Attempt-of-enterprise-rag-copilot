from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor

from app.domain.queries import SearchHit, SearchRequest, SearchResult
from app.retrieval.pipeline import RankedSearchCandidate, RankedSearchPool

_TOKEN = re.compile(r"[a-z0-9]+(?:[&'-][a-z0-9]+)*", re.IGNORECASE)
_FOCUS_STOPWORDS = frozenset(
    """
    a an the what which who how much many was were is are did does do has have had
    in on at of for from to by between during over under with and or if assuming
    calculate determine find company years year ended as compared versus than total
    percent percentage change difference increase decrease ratio average
    approximately million millions billion thousands dollars
    """.split()
)

FINANCE_KNOWN_REPORT_CANARY_PROFILE = "finance_known_report_page_fusion_v1"


def focus_financial_query(question: str) -> str:
    """Keep evidence-bearing entities, metrics, and periods from a question."""

    tokens = [
        token.casefold()
        for token in _TOKEN.findall(question)
        if token.casefold() not in _FOCUS_STOPWORDS
    ]
    return " ".join(tokens) or question


def _page_key(hit: SearchHit) -> tuple[str, int] | None:
    locator = hit.locator
    if locator is None or locator.kind != "page" or locator.end != locator.start:
        return None
    return hit.doc_id, locator.start


def fuse_unique_pages(
    dense_hits: Sequence[SearchHit],
    focused_bm25_hits: Sequence[SearchHit],
    *,
    lexical_weight: float = 0.5,
    rrf_k: int = 60,
    limit: int = 5,
) -> list[SearchHit]:
    if not 0.0 <= lexical_weight <= 1.0:
        raise ValueError("lexical_weight must be between zero and one")
    if rrf_k < 1:
        raise ValueError("rrf_k must be positive")
    if limit < 1:
        raise ValueError("limit must be positive")

    return fuse_unique_page_rankings(
        ((dense_hits, 1.0), (focused_bm25_hits, lexical_weight)),
        rrf_k=rrf_k,
        limit=limit,
    )


def fuse_unique_page_rankings(
    rankings: Sequence[tuple[Sequence[SearchHit], float]],
    *,
    rrf_k: int = 60,
    limit: int = 5,
) -> list[SearchHit]:
    if not rankings:
        raise ValueError("page fusion requires at least one ranking")
    if any(not 0.0 <= weight <= 1.0 for _, weight in rankings):
        raise ValueError("page fusion weights must be between zero and one")
    if rrf_k < 1:
        raise ValueError("rrf_k must be positive")
    if limit < 1:
        raise ValueError("limit must be positive")

    scores: dict[tuple[str, int], float] = defaultdict(float)
    representatives: dict[tuple[str, int], SearchHit] = {}
    for hits, weight in rankings:
        seen: set[tuple[str, int]] = set()
        page_rank = 0
        for hit in hits:
            key = _page_key(hit)
            if key is None or key in seen:
                continue
            seen.add(key)
            page_rank += 1
            scores[key] += weight / (rrf_k + page_rank)
            if key not in representatives:
                representatives[key] = hit

    ordered = sorted(scores, key=lambda key: (-scores[key], key[0], key[1]))
    return [
        representatives[key].model_copy(update={"fused_score": scores[key]})
        for key in ordered[:limit]
    ]


class FocusedPageFusionPipeline:
    """Two-stage page retrieval for evaluation or the explicit finance canary."""

    def __init__(
        self,
        base_pipeline,
        *,
        source_top_k: int = 20,
        candidate_k: int = 80,
        max_chunks_per_doc: int = 10,
        lexical_weight: float = 0.5,
        original_bm25_weight: float = 0.0,
        rrf_k: int = 60,
        parallel_search: bool = False,
        shared_scope_search: bool = False,
        allowed_policy_ids: Iterable[str] | None = None,
    ) -> None:
        self.base_pipeline = base_pipeline
        self.source_top_k = source_top_k
        self.candidate_k = candidate_k
        self.max_chunks_per_doc = max_chunks_per_doc
        self.lexical_weight = lexical_weight
        self.original_bm25_weight = original_bm25_weight
        self.rrf_k = rrf_k
        self.parallel_search = parallel_search
        self.shared_scope_search = shared_scope_search
        self.allowed_policy_ids = (
            None if allowed_policy_ids is None else frozenset(allowed_policy_ids)
        )

    def search(self, request: SearchRequest) -> SearchResult:
        if not self._is_known_report_request(request):
            return self.base_pipeline.search(request)
        common = {
            "top_k": self.source_top_k,
            "candidate_k": self.candidate_k,
            "include_parent": False,
            "max_chunks_per_doc": self.max_chunks_per_doc,
        }
        focused_query = focus_financial_query(request.query)
        requests = [request.model_copy(update={**common, "mode": "dense"})]
        labels = ["dense"]
        weights = [1.0]
        if self.original_bm25_weight > 0:
            requests.append(
                request.model_copy(
                    update={
                        **common,
                        "request_id": f"{request.request_id[:185]}-bm25",
                        "mode": "bm25",
                    }
                )
            )
            labels.append("bm25")
            weights.append(self.original_bm25_weight)
        requests.append(
            request.model_copy(
                update={
                    **common,
                    "request_id": f"{request.request_id[:180]}-focused-bm25",
                    "query": focused_query,
                    "mode": "bm25",
                }
            )
        )
        labels.append("focused_bm25")
        weights.append(self.lexical_weight)
        if self.parallel_search and self.shared_scope_search:
            raise ValueError("parallel and shared-scope search are mutually exclusive")
        if self.parallel_search:
            with ThreadPoolExecutor(max_workers=len(requests)) as executor:
                results = list(executor.map(self.base_pipeline.search, requests))
        elif self.shared_scope_search:
            search_many_same_scope = getattr(
                self.base_pipeline,
                "search_many_same_scope",
                None,
            )
            if search_many_same_scope is None:
                raise TypeError("shared-scope search requires pipeline support")
            results = list(search_many_same_scope(requests))
        else:
            results = [self.base_pipeline.search(item) for item in requests]
        dense = results[0]
        if any(
            result.index_run_id != dense.index_run_id
            or result.manifest_sha256 != dense.manifest_sha256
            for result in results[1:]
        ):
            raise ValueError("page fusion sources came from different index snapshots")
        hits = fuse_unique_page_rankings(
            tuple((result.hits, weight) for result, weight in zip(results, weights, strict=True)),
            rrf_k=self.rrf_k,
            limit=request.top_k,
        )
        stage_counts = {"focused_query_tokens": len(focused_query.split())}
        for label, result in zip(labels, results, strict=True):
            stage_counts.update(
                {f"{label}_{key}": value for key, value in result.stage_counts.items()}
            )
        stage_counts["page_fusion_returned"] = len(hits)
        stop_reasons = {result.stop_reason for result in results}
        stop_reason = (
            "ok"
            if hits
            else (
                "timeout"
                if "timeout" in stop_reasons
                else "no_visible_evidence"
                if "no_visible_evidence" in stop_reasons
                else "no_match"
            )
        )
        return SearchResult(
            request_id=request.request_id,
            query=request.query,
            mode="hybrid",
            index_run_id=dense.index_run_id,
            manifest_sha256=dense.manifest_sha256,
            hits=hits,
            visible_candidate_count=max(result.visible_candidate_count for result in results),
            internal_denied_count=sum(result.internal_denied_count for result in results),
            stage_counts=stage_counts,
            stop_reason=stop_reason,
        )

    def ranked_candidates_for_guard(self, request: SearchRequest) -> RankedSearchPool:
        if not self._is_known_report_request(request):
            return self.base_pipeline.ranked_candidates_for_guard(request)
        pool_request = request.model_copy(
            update={"top_k": min(request.candidate_k, self.source_top_k)}
        )
        result = self.search(pool_request)
        snapshot = getattr(self.base_pipeline, "snapshot", None)
        documents = getattr(snapshot, "documents_by_id", {})
        candidates = tuple(
            RankedSearchCandidate(
                rank=rank,
                hit=hit,
                document_title=(documents[hit.doc_id].title if hit.doc_id in documents else None),
            )
            for rank, hit in enumerate(result.hits, start=1)
        )
        return RankedSearchPool(
            request_id=result.request_id,
            query=result.query,
            mode=result.mode,
            index_run_id=result.index_run_id,
            manifest_sha256=result.manifest_sha256,
            candidates=candidates,
            visible_candidate_count=result.visible_candidate_count,
            internal_denied_count=result.internal_denied_count,
            stage_counts={**result.stage_counts, "guard_candidates": len(candidates)},
            stop_reason=result.stop_reason,
        )

    def _is_known_report_request(self, request: SearchRequest) -> bool:
        if len(request.filters.policy_ids) != 1:
            return False
        return self.allowed_policy_ids is None or request.filters.policy_ids[0] in (
            self.allowed_policy_ids
        )


def build_finance_known_report_canary(
    base_pipeline,
    *,
    allowed_policy_ids: Iterable[str] | None = None,
) -> FocusedPageFusionPipeline:
    """Build the reviewed profile without changing the application's default search."""

    return FocusedPageFusionPipeline(
        base_pipeline,
        source_top_k=20,
        candidate_k=80,
        max_chunks_per_doc=10,
        lexical_weight=0.5,
        original_bm25_weight=0.5,
        rrf_k=60,
        parallel_search=False,
        shared_scope_search=True,
        allowed_policy_ids=allowed_policy_ids,
    )


__all__ = [
    "FINANCE_KNOWN_REPORT_CANARY_PROFILE",
    "FocusedPageFusionPipeline",
    "build_finance_known_report_canary",
    "focus_financial_query",
    "fuse_unique_page_rankings",
    "fuse_unique_pages",
]
