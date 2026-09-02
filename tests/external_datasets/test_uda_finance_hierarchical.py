from __future__ import annotations

from dataclasses import dataclass, field
from threading import Barrier

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
    FINANCE_KNOWN_REPORT_CANARY_PROFILE,
    FocusedPageFusionPipeline,
    build_finance_known_report_canary,
    focus_financial_query,
    fuse_unique_page_rankings,
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


def test_reviewed_canary_profile_is_explicit_and_uses_v3_parameters() -> None:
    pipeline = build_finance_known_report_canary(_FakePipeline())

    assert FINANCE_KNOWN_REPORT_CANARY_PROFILE == "finance_known_report_page_fusion_v1"
    assert pipeline.source_top_k == 20
    assert pipeline.candidate_k == 80
    assert pipeline.max_chunks_per_doc == 10
    assert pipeline.lexical_weight == 0.5
    assert pipeline.original_bm25_weight == 0.5
    assert not pipeline.parallel_search
    assert pipeline.shared_scope_search


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


def test_page_fusion_combines_three_rankings_and_keeps_first_representative() -> None:
    dense = [_hit(1, 1), _hit(2, 2)]
    bm25 = [_hit(1, 3, channel="bm25"), _hit(2, 2, channel="bm25")]
    focused_bm25 = [_hit(1, 2, channel="bm25"), _hit(2, 4, channel="bm25")]

    fused = fuse_unique_page_rankings(
        ((dense, 1.0), (bm25, 0.5), (focused_bm25, 0.5)),
        limit=4,
    )

    assert [item.locator.start for item in fused] == [2, 1, 3, 4]
    assert fused[0].chunk_id == dense[1].chunk_id


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


def test_v2_pipeline_reuses_scope_for_all_three_channels() -> None:
    base = _FakePipeline()
    request = _request()

    FocusedPageFusionPipeline(
        base,
        original_bm25_weight=0.5,
        parallel_search=True,
    ).search(request)

    assert sorted(call.mode for call in base.calls) == ["bm25", "bm25", "dense"]
    assert sorted(call.query for call in base.calls) == [
        "What was the percentage change in R&D expenses from 2015 to 2016?",
        "What was the percentage change in R&D expenses from 2015 to 2016?",
        "r&d expenses 2015 2016",
    ]
    assert all(call.user == request.user for call in base.calls)
    assert all(call.filters == request.filters for call in base.calls)
    assert all(call.purpose == request.purpose for call in base.calls)


@dataclass
class _BarrierPipeline(_FakePipeline):
    barrier: Barrier = field(default_factory=lambda: Barrier(3))

    def search(self, request: SearchRequest) -> SearchResult:
        self.barrier.wait(timeout=2)
        return super().search(request)


def test_v2_parallel_search_starts_all_channels_concurrently() -> None:
    base = _BarrierPipeline()

    result = FocusedPageFusionPipeline(
        base,
        original_bm25_weight=0.5,
        parallel_search=True,
    ).search(_request())

    assert result.stop_reason == "ok"
    assert len(base.calls) == 3


@dataclass
class _SameScopePipeline(_FakePipeline):
    batches: list[list[SearchRequest]] = field(default_factory=list)

    def search_many_same_scope(self, requests: list[SearchRequest]) -> list[SearchResult]:
        self.batches.append(requests)
        return [self.search(request) for request in requests]


def test_v3_uses_one_server_owned_same_scope_batch() -> None:
    base = _SameScopePipeline()

    result = FocusedPageFusionPipeline(
        base,
        original_bm25_weight=0.5,
        shared_scope_search=True,
    ).search(_request())

    assert result.stop_reason == "ok"
    assert len(base.batches) == 1
    assert len(base.batches[0]) == 3


def test_canary_exposes_ranked_candidates_to_the_guard() -> None:
    base = _SameScopePipeline()
    pipeline = build_finance_known_report_canary(base)

    pool = pipeline.ranked_candidates_for_guard(_request().model_copy(update={"candidate_k": 8}))

    assert pool.stop_reason == "ok"
    assert len(pool.candidates) == 8
    assert [candidate.rank for candidate in pool.candidates] == list(range(1, 9))
    assert pool.stage_counts["guard_candidates"] == 8
    assert len(base.batches) == 1


def test_canary_falls_back_when_the_known_report_is_not_allowlisted() -> None:
    base = _FakePipeline()
    pipeline = build_finance_known_report_canary(
        base,
        allowed_policy_ids=["another-report"],
    )

    result = pipeline.search(_request())

    assert result.mode == "dense"
    assert len(base.calls) == 1
    assert base.calls[0] == _request()
