from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.documents import SourceLocator
from app.domain.queries import SearchHit
from app.external_datasets.uda_finance_r3_page_eval import (
    load_page_protocol,
    rerank_page_hits,
)
from scripts.eval_uda_finance_r3_pages import claim_split_execution


def _hit(rank: int, page: int, *, text: str | None = None) -> SearchHit:
    return SearchHit(
        index_run_id="index-r3",
        chunk_id=f"chunk-{page}-{rank}",
        doc_id="uda-fin-a-2020",
        policy_id="uda-fin-a-2020",
        source_path="documents/A_2020.pdf",
        section_path=[f"Page {page}"],
        locator=SourceLocator(kind="page", start=page, end=page),
        matched_text=text or f"page {page}",
        context_text=text or f"page {page}",
        tenant_id="uda-external",
        region="global",
        acl_groups=["uda-evaluator"],
        version_id="uda-fin-a-2020-r3-v1",
        version="r3.1",
        status="active",
        authority_level=90,
        variant="authoritative",
        fused_score=1.0 / rank,
        dense_score=1.0 / rank,
        dense_rank=rank,
    )


def test_page_max_removes_duplicate_page_slots() -> None:
    hits = [_hit(1, 5), _hit(2, 5), _hit(3, 8), _hit(4, 9), _hit(5, 10), _hit(6, 11)]
    ranked = rerank_page_hits(
        hits,
        query="What was revenue?",
        strategy="dense_page_max",
        page_representatives={},
    )

    assert [item.locator.start for item in ranked] == [5, 8, 9, 10, 11]


def test_neighbor_strategy_uses_real_same_boundary_page() -> None:
    source = _hit(1, 5)
    neighbor = _hit(99, 6)
    ranked = rerank_page_hits(
        [source, _hit(2, 10)],
        query="What was revenue?",
        strategy="dense_page_neighbor",
        page_representatives={(source.doc_id, 6): neighbor},
    )

    assert [item.locator.start for item in ranked] == [5, 6, 10]
    assert ranked[1].matched_text == "page 6"
    assert ranked[1].fused_score == pytest.approx(0.7)


def test_structure_strategy_is_bounded_and_deterministic() -> None:
    numeric = " ".join(str(value) for value in range(12))
    ranked = rerank_page_hits(
        [_hit(1, 5, text=numeric), _hit(2, 5, text=numeric), _hit(3, 8)],
        query="What was the percentage increase?",
        strategy="dense_page_structure",
        page_representatives={},
    )

    assert [item.locator.start for item in ranked] == [5, 8]
    assert ranked[0].fused_score == pytest.approx(1.08)


def test_page_protocol_is_frozen_and_index_bound() -> None:
    protocol, digest = load_page_protocol()

    assert len(digest) == 64
    assert protocol["index_build"]["index_manifest_sha256"] == (
        "08773dde88cf71bbccc199a45390af89802355a2f3ca7ff1482e3901513ba27b"
    )
    assert protocol["promotion_gates"]["min_page_hit_at_5_delta"] == 0.05


def test_validation_marker_is_one_shot(tmp_path: Path) -> None:
    kwargs = {
        "split": "validation",
        "run_id": "r3-validation-v1",
        "code_revision": "a" * 40,
        "page_protocol_sha256": "b" * 64,
        "cases_sha256": "c" * 64,
        "strategies": ["dense_chunk", "dense_page_max"],
    }
    marker = claim_split_execution(tmp_path, **kwargs)

    assert marker.is_file()
    with pytest.raises(FileExistsError):
        claim_split_execution(tmp_path, **kwargs)
