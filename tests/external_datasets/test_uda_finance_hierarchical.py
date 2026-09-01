from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.domain.documents import SourceLocator
from app.domain.queries import (
    QueryFilters,
    SearchHit,
    SearchRequest,
    SearchResult,
    UserContext,
)
from app.external_datasets.uda_finance_hierarchical import (
    FocusedPageFusionPipeline,
    focus_financial_query,
    fuse_unique_pages,
)


def _hit(rank: int, page: int, *, channel: str = "dense") -> SearchHit:
    return SearchHit(
        index_run_id="index-r4",
        chunk_id=f"{channel}-chunk-{page}-{rank}",
        doc_id="uda-fin-a-2020",
        policy_id="uda-fin-a-2020",
        source_path="documents/A_2020.pdf",
        section_path=[f"Page {page}"],
        locator=SourceLocator(kind="page", start=page, end=page),
        matched_text=f"original visible page {page} text",
        context_text=f"original visible page {page} text",
        tenant_id="uda-external",
        region="global",
        acl_groups=["uda-evaluator"],
        version_id="uda-fin-a-2020-r4-v1",
        version="r4.1",
        status="active",
        authority_level=90,
        variant="authoritative",
        fused_score=1.0 / rank,
        dense_score=1.0 / rank if channel == "dense" else None,
        bm25_score=1.0 / rank if channel == "bm25" else None,
    )


def _request() -> SearchRequest:
    return SearchRequest(
        request_id="r4-case-1",
        query="What was the percentage change in R&D expenses from 2015 to 2016?",
        purpose="R4 paired page evaluation",
        user=UserContext(
            user_id="uda-evaluator",
            tenant_id="uda-external",
            region="global",
            groups=["uda-evaluator"],
        ),
        filters=QueryFilters(
            policy_ids=["uda-fin-a-2020"],
            temporal_scope="all",
            authoritative_only=False,
        ),
        top_k=5,
        candidate_k=20,
        mode="dense",
        include_parent=False,
        max_chunks_per_doc=5,
    )


@dataclass
class _FakePipeline:
    calls: list[SearchRequest] = field(default_factory=list)

    def search(self, request: SearchRequest) -> SearchResult:
        self.calls.append(request)
        pages = [1, 2, 3, 4, 5, 6] if request.mode == "dense" else [6, 5, 4, 7, 8]
        hits = [_hit(rank, page, channel=request.mode) for rank, page in enumerate(pages, 1)]
        return SearchResult(
            request_id=request.request_id,
            query=request.query,
            mode=request.mode,
            index_run_id="index-r4",
            manifest_sha256="a" * 64,
            hits=hits,
            visible_candidate_count=len(hits),
            internal_denied_count=0,
            stage_counts={"ranked": len(hits)},
            stop_reason="ok",
        )


def test_focus_query_keeps_metrics_entities_and_periods() -> None:
    assert (
        focus_financial_query("What was the percentage change in R&D expenses from 2015 to 2016?")
        == "r&d expenses 2015 2016"
    )


def test_focus_query_falls_back_when_every_token_is_removed() -> None:
    assert focus_financial_query("What was the change?") == "What was the change?"


def test_page_fusion_deduplicates_chunks_before_assigning_rank() -> None:
    dense = [_hit(1, 1), _hit(2, 1), _hit(3, 2)]
    bm25 = [_hit(1, 2, channel="bm25"), _hit(2, 3, channel="bm25")]

    fused = fuse_unique_pages(dense, bm25, lexical_weight=0.5)

    assert [item.locator.start for item in fused] == [2, 1, 3]
    assert len({item.locator.start for item in fused}) == len(fused)


def test_page_fusion_validates_frozen_parameters() -> None:
    with pytest.raises(ValueError, match="lexical_weight"):
        fuse_unique_pages([], [], lexical_weight=1.1)


def test_pipeline_reuses_server_owned_scope_and_returns_original_hits() -> None:
    base = _FakePipeline()
    result = FocusedPageFusionPipeline(base).search(_request())

    assert [call.mode for call in base.calls] == ["dense", "bm25"]
    assert base.calls[1].query == "r&d expenses 2015 2016"
    assert base.calls[0].user == base.calls[1].user
    assert base.calls[0].filters == base.calls[1].filters
    assert all(call.top_k == 20 for call in base.calls)
    assert all(call.candidate_k == 80 for call in base.calls)
    assert result.request_id == "r4-case-1"
    assert result.query == _request().query
    assert result.mode == "hybrid"
    assert len(result.hits) == 5
    assert all(hit.context_text.startswith("original visible") for hit in result.hits)
    assert result.stage_counts["page_fusion_returned"] == 5
