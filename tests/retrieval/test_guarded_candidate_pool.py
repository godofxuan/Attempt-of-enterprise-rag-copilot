from __future__ import annotations

from app.domain.queries import SearchRequest
from app.retrieval.navigation import DocumentNavigator
from app.retrieval.pipeline import HybridRetrievalPipeline
from tests.v2_test_support import user_context


def _request(*, mode: str = "dense", candidate_k: int = 3) -> SearchRequest:
    return SearchRequest(
        request_id="guarded-pool",
        user=user_context(),
        query="remote work policy",
        purpose="guard candidates before top-k truncation",
        mode=mode,
        top_k=2,
        candidate_k=candidate_k,
        max_chunks_per_doc=1,
        include_parent=False,
    )


def test_ranked_guard_pool_preserves_candidate_k_before_diversity(
    chunk_factory,
    document_factory,
    snapshot_factory,
) -> None:
    first = chunk_factory(
        chunk_id="doc-a::001",
        doc_id="doc-a",
        text="Remote work policy first fragment.",
        checksum="1" * 64,
    )
    second_same_doc = chunk_factory(
        chunk_id="doc-a::002",
        doc_id="doc-a",
        text="Remote work policy second fragment.",
        checksum="2" * 64,
    )
    third_other_doc = chunk_factory(
        chunk_id="doc-b::001",
        doc_id="doc-b",
        source_path="documents/doc-b.md",
        policy_id="policy-b",
        text="Remote work policy from document B.",
        checksum="3" * 64,
    )
    snapshot = snapshot_factory(
        [first, second_same_doc, third_other_doc],
        documents=[
            document_factory(doc_id="doc-a", title="Policy A"),
            document_factory(
                doc_id="doc-b",
                title="Policy B",
                source_path="documents/doc-b.md",
                policy_id="policy-b",
                checksum="4" * 64,
                normalized_text_hash="5" * 64,
            ),
        ],
        vectors=[[1.0, 0.0], [0.9, 0.1], [0.8, 0.2]],
    )
    embedding_calls: list[str] = []
    pipeline = HybridRetrievalPipeline(
        snapshot,
        embed_text=lambda text: embedding_calls.append(text) or [1.0, 0.0],
    )

    pool = pipeline.ranked_candidates_for_guard(_request())

    assert [candidate.rank for candidate in pool.candidates] == [1, 2, 3]
    assert [candidate.hit.chunk_id for candidate in pool.candidates] == [
        "doc-a::001",
        "doc-a::002",
        "doc-b::001",
    ]
    assert [candidate.document_title for candidate in pool.candidates] == [
        "Policy A",
        "Policy A",
        "Policy B",
    ]
    assert pool.stage_counts["dense_candidates"] == 3
    assert embedding_calls == ["remote work policy"]

    public_result = pipeline.search(_request())
    assert [hit.chunk_id for hit in public_result.hits] == [
        "doc-a::001",
        "doc-b::001",
    ]


def test_navigator_exposes_ranked_pool_without_public_search_truncation(
    chunk_factory,
    snapshot_factory,
) -> None:
    chunks = [
        chunk_factory(
            chunk_id=f"chunk-{index}",
            doc_id=f"doc-{index}",
            source_path=f"documents/doc-{index}.md",
            text=f"Remote work candidate {index}.",
            checksum=str(index) * 64,
        )
        for index in (1, 2, 3)
    ]
    snapshot = snapshot_factory(
        chunks,
        vectors=[[1.0, 0.0], [0.9, 0.1], [0.8, 0.2]],
    )
    pipeline = HybridRetrievalPipeline(
        snapshot,
        embed_text=lambda _text: [1.0, 0.0],
    )
    navigator = DocumentNavigator(snapshot, pipeline=pipeline)

    outcome = navigator.search_ranked(_request())

    assert len(outcome.candidates) == 3
    assert outcome.stop_reason == "ok"


def test_hybrid_guard_pool_is_capped_after_fusion(
    chunk_factory,
    snapshot_factory,
    monkeypatch,
) -> None:
    chunks = [
        chunk_factory(
            chunk_id=f"chunk-{index}",
            doc_id=f"doc-{index}",
            source_path=f"documents/doc-{index}.md",
            text=f"Candidate {index}",
            checksum=str(index) * 64,
        )
        for index in range(1, 7)
    ]
    pipeline = HybridRetrievalPipeline(
        snapshot_factory(chunks),
        embed_text=lambda _text: [1.0, 0.0],
    )
    monkeypatch.setattr(
        pipeline,
        "_rank_bm25",
        lambda _query, _visible, _limit: [(0, 1.0), (1, 0.9), (2, 0.8)],
    )
    monkeypatch.setattr(
        pipeline,
        "_rank_dense",
        lambda _query, _visible, _limit: [(3, 1.0), (4, 0.9), (5, 0.8)],
    )

    pool = pipeline.ranked_candidates_for_guard(
        _request(mode="hybrid", candidate_k=3)
    )

    assert len(pool.candidates) == 3
    assert [item.rank for item in pool.candidates] == [1, 2, 3]
    assert pool.stage_counts["fused_candidates"] == 6
