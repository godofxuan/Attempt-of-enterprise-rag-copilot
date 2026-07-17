from datetime import date

import pytest

from app.domain.queries import QueryFilters, SearchRequest, UserContext
from app.retrieval.pipeline import HybridRetrievalPipeline


USER = UserContext(
    user_id="employee-one",
    tenant_id="tenant-one",
    region="cn",
    groups=["employees"],
)


def search_request(**updates) -> SearchRequest:
    values = {
        "query": "needle",
        "purpose": "test ranking",
        "user": USER,
        "mode": "bm25",
        "top_k": 5,
        "candidate_k": 20,
        "include_parent": False,
    }
    values.update(updates)
    return SearchRequest(**values)


def test_bm25_mode_never_calls_embedder(chunk_factory, snapshot_factory) -> None:
    relevant = chunk_factory(
        chunk_id="relevant",
        doc_id="doc-relevant",
        text="needle policy",
        checksum="1" * 64,
    )
    others = [
        chunk_factory(
            chunk_id=f"other-{index}",
            doc_id=f"doc-other-{index}",
            text="unrelated handbook",
            checksum=str(index + 2) * 64,
        )
        for index in range(2)
    ]

    def fail_embed(text: str):
        raise AssertionError("BM25 mode must not call embedder")

    pipeline = HybridRetrievalPipeline(
        snapshot_factory([relevant, *others]),
        embed_text=fail_embed,
    )

    result = pipeline.search(search_request(top_k=1, candidate_k=3))

    assert result.hits[0].chunk_id == "relevant"
    assert result.hits[0].bm25_rank == 1
    assert result.hits[0].dense_rank is None


def test_dense_mode_rejects_wrong_embedding_dimension(
    chunk_factory,
    snapshot_factory,
) -> None:
    snapshot = snapshot_factory([chunk_factory()])
    pipeline = HybridRetrievalPipeline(snapshot, embed_text=lambda text: [1.0, 2.0, 3.0])

    with pytest.raises(ValueError, match="dimension"):
        pipeline.search(
            search_request(mode="dense", top_k=1, candidate_k=1)
        )


def test_hybrid_rrf_uses_deterministic_tie_break(
    chunk_factory,
    snapshot_factory,
) -> None:
    dense_first = chunk_factory(
        chunk_id="a-chunk",
        doc_id="doc-a",
        text="needle policy",
        checksum="1" * 64,
    )
    bm25_first = chunk_factory(
        chunk_id="b-chunk",
        doc_id="doc-b",
        text="needle needle policy",
        checksum="2" * 64,
    )
    third = chunk_factory(
        chunk_id="c-chunk",
        doc_id="doc-c",
        text="unrelated",
        checksum="3" * 64,
    )
    snapshot = snapshot_factory(
        [dense_first, bm25_first, third],
        vectors=[[1.0, 0.0], [0.8, 0.2], [0.0, 1.0]],
    )
    pipeline = HybridRetrievalPipeline(snapshot, embed_text=lambda text: [1.0, 0.0])

    first = pipeline.search(search_request(mode="hybrid", top_k=3, candidate_k=3))
    second = pipeline.search(search_request(mode="hybrid", top_k=3, candidate_k=3))

    assert [hit.chunk_id for hit in first.hits] == [
        hit.chunk_id for hit in second.hits
    ]
    assert first.hits[0].chunk_id == "a-chunk"


def test_metadata_current_authority_department_policy_and_as_of_filters(
    chunk_factory,
    snapshot_factory,
) -> None:
    active = chunk_factory(
        chunk_id="active-auth",
        doc_id="active-auth-doc",
        text="needle active authoritative",
        checksum="1" * 64,
    )
    supporting = chunk_factory(
        chunk_id="active-support",
        doc_id="active-support-doc",
        text="needle active supporting",
        variant="supporting",
        authority_level=40,
        checksum="2" * 64,
    )
    retired = chunk_factory(
        chunk_id="retired-auth",
        doc_id="retired-auth-doc",
        text="needle retired authoritative",
        version_id="policy-a@2025",
        version="2025",
        status="retired",
        effective_from=date(2024, 1, 1),
        effective_to=date(2026, 1, 1),
        checksum="3" * 64,
    )
    finance = chunk_factory(
        chunk_id="finance-auth",
        doc_id="finance-auth-doc",
        text="needle finance authoritative",
        policy_id="policy-b",
        department="finance",
        filed_department="finance",
        checksum="4" * 64,
    )
    pipeline = HybridRetrievalPipeline(snapshot_factory([active, supporting, retired, finance]))

    current = pipeline.search(search_request())
    assert {hit.chunk_id for hit in current.hits} == {"active-auth", "finance-auth"}

    scoped = pipeline.search(
        search_request(
            filters=QueryFilters(departments=["hr"], policy_ids=["policy-a"])
        )
    )
    assert [hit.chunk_id for hit in scoped.hits] == ["active-auth"]

    historical = pipeline.search(
        search_request(
            filters=QueryFilters(
                temporal_scope="as_of",
                as_of=date(2025, 6, 1),
                policy_ids=["policy-a"],
            )
        )
    )
    assert [hit.chunk_id for hit in historical.hits] == ["retired-auth"]

    all_variants = pipeline.search(
        search_request(
            filters=QueryFilters(
                temporal_scope="all",
                authoritative_only=False,
                policy_ids=["policy-a"],
            )
        )
    )
    assert {hit.chunk_id for hit in all_variants.hits} == {
        "active-auth",
        "active-support",
        "retired-auth",
    }


def test_result_diversity_limits_chunks_per_document(
    chunk_factory,
    snapshot_factory,
) -> None:
    chunks = [
        chunk_factory(
            chunk_id="doc-a-1",
            doc_id="doc-a",
            text="needle one",
            checksum="1" * 64,
        ),
        chunk_factory(
            chunk_id="doc-a-2",
            doc_id="doc-a",
            text="needle two",
            checksum="1" * 64,
        ),
        chunk_factory(
            chunk_id="doc-b-1",
            doc_id="doc-b",
            text="needle three",
            checksum="2" * 64,
        ),
    ]
    pipeline = HybridRetrievalPipeline(snapshot_factory(chunks))

    result = pipeline.search(
        search_request(top_k=3, candidate_k=3, max_chunks_per_doc=1)
    )

    assert len(result.hits) == 2
    assert {hit.doc_id for hit in result.hits} == {"doc-a", "doc-b"}
