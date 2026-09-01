from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence

from app.domain.queries import SearchHit, SearchRequest, SearchResult

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

    scores: dict[tuple[str, int], float] = defaultdict(float)
    representatives: dict[tuple[str, int], SearchHit] = {}
    for hits, weight in ((dense_hits, 1.0), (focused_bm25_hits, lexical_weight)):
        seen: set[tuple[str, int]] = set()
        page_rank = 0
        for hit in hits:
            key = _page_key(hit)
            if key is None or key in seen:
                continue
            seen.add(key)
            page_rank += 1
            scores[key] += weight / (rrf_k + page_rank)
            current = representatives.get(key)
            if current is None or (weight == 1.0 and current not in dense_hits):
                representatives[key] = hit

    ordered = sorted(scores, key=lambda key: (-scores[key], key[0], key[1]))
    return [
        representatives[key].model_copy(update={"fused_score": scores[key]})
        for key in ordered[:limit]
    ]


class FocusedPageFusionPipeline:
    """Two-stage page retrieval candidate for frozen external evaluation only."""

    def __init__(
        self,
        base_pipeline,
        *,
        source_top_k: int = 20,
        candidate_k: int = 80,
        max_chunks_per_doc: int = 10,
        lexical_weight: float = 0.5,
        rrf_k: int = 60,
    ) -> None:
        self.base_pipeline = base_pipeline
        self.source_top_k = source_top_k
        self.candidate_k = candidate_k
        self.max_chunks_per_doc = max_chunks_per_doc
        self.lexical_weight = lexical_weight
        self.rrf_k = rrf_k

    def search(self, request: SearchRequest) -> SearchResult:
        common = {
            "top_k": self.source_top_k,
            "candidate_k": self.candidate_k,
            "include_parent": False,
            "max_chunks_per_doc": self.max_chunks_per_doc,
        }
        dense = self.base_pipeline.search(request.model_copy(update={**common, "mode": "dense"}))
        focused_query = focus_financial_query(request.query)
        focused_bm25 = self.base_pipeline.search(
            request.model_copy(
                update={
                    **common,
                    "request_id": f"{request.request_id[:180]}-focused-bm25",
                    "query": focused_query,
                    "mode": "bm25",
                }
            )
        )
        if (
            dense.index_run_id != focused_bm25.index_run_id
            or dense.manifest_sha256 != focused_bm25.manifest_sha256
        ):
            raise ValueError("page fusion sources came from different index snapshots")
        hits = fuse_unique_pages(
            dense.hits,
            focused_bm25.hits,
            lexical_weight=self.lexical_weight,
            rrf_k=self.rrf_k,
            limit=request.top_k,
        )
        stage_counts = {
            **{f"dense_{key}": value for key, value in dense.stage_counts.items()},
            **{f"focused_bm25_{key}": value for key, value in focused_bm25.stage_counts.items()},
            "focused_query_tokens": len(focused_query.split()),
            "page_fusion_returned": len(hits),
        }
        stop_reason = (
            "ok"
            if hits
            else (
                "timeout"
                if "timeout" in {dense.stop_reason, focused_bm25.stop_reason}
                else "no_visible_evidence"
                if "no_visible_evidence" in {dense.stop_reason, focused_bm25.stop_reason}
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
            visible_candidate_count=max(
                dense.visible_candidate_count,
                focused_bm25.visible_candidate_count,
            ),
            internal_denied_count=(
                dense.internal_denied_count + focused_bm25.internal_denied_count
            ),
            stage_counts=stage_counts,
            stop_reason=stop_reason,
        )


__all__ = [
    "FocusedPageFusionPipeline",
    "focus_financial_query",
    "fuse_unique_pages",
]
