from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.documents import SourceLocator
from app.domain.queries import SearchHit, SearchResult
from app.external_datasets.uda_finance import UdaFinancePreparedCase
from app.external_datasets.uda_finance_page_eval import (
    evaluate_uda_finance_pages,
    publish_uda_finance_page_run,
    summarize_uda_finance_pages,
    verify_uda_finance_page_run,
)


def _case() -> UdaFinancePreparedCase:
    return UdaFinancePreparedCase(
        case_id="uda-case-1",
        split="dev",
        company_id="A",
        doc_name="A_2020",
        q_uid="A/2020/page_3.pdf-1",
        question="What was revenue?",
        answers=["1"],
        gold_doc_id="uda-fin-a-2020",
        page_number=3,
    )


def _hit(rank: int, page: int) -> SearchHit:
    return SearchHit(
        index_run_id="index-v1",
        chunk_id=f"chunk-{rank}",
        doc_id="uda-fin-a-2020",
        policy_id="uda-fin-a-2020",
        source_path="documents/A_2020.pdf",
        section_path=[f"Page {page}"],
        locator=SourceLocator(kind="page", start=page, end=page),
        matched_text=f"page {page}",
        context_text=f"page {page}",
        tenant_id="uda-external",
        region="global",
        acl_groups=["uda-evaluator"],
        version_id="uda-fin-a-2020-v1",
        version="1.0",
        status="active",
        authority_level=90,
        variant="authoritative",
        fused_score=1.0 / rank,
    )


class _Pipeline:
    def search(self, request):
        assert request.filters.policy_ids == ["uda-fin-a-2020"]
        assert request.top_k == 5
        return SearchResult(
            request_id=request.request_id,
            query=request.query,
            mode=request.mode,
            index_run_id="index-v1",
            manifest_sha256="a" * 64,
            hits=[_hit(1, 8), _hit(2, 3), _hit(3, 9), _hit(4, 10), _hit(5, 11)],
            visible_candidate_count=5,
            internal_denied_count=0,
            stage_counts={"visible": 5},
            stop_reason="ok",
        )


def test_document_conditioned_page_metrics_and_latency() -> None:
    details = evaluate_uda_finance_pages(
        cases=[_case()],
        pipeline=_Pipeline(),
        retrieval_arm="dense",
    )
    summary = summarize_uda_finance_pages(details, embedding_calls=1)

    assert summary.page_hit_at_1 == 0
    assert summary.page_hit_at_3 == 1
    assert summary.page_hit_at_5 == 1
    assert summary.page_mrr_at_5 == 0.5
    assert summary.page_ndcg_at_5 == pytest.approx(1 / 1.584962500721156)
    assert summary.macro_page_recall_at_5 == 1
    assert summary.page_locator_coverage_at_5 == 1
    assert summary.embedding_calls == 1


def test_page_run_is_immutable_and_hash_verified(tmp_path: Path) -> None:
    details = evaluate_uda_finance_pages(
        cases=[_case()], pipeline=_Pipeline(), retrieval_arm="bm25"
    )
    summary = summarize_uda_finance_pages(details, embedding_calls=0)
    run_dir = publish_uda_finance_page_run(
        root=tmp_path,
        run_id="uda-dev-bm25-v1",
        split="dev",
        retrieval_arm="bm25",
        code_revision="b" * 40,
        protocol_sha256="c" * 64,
        dataset_manifest_sha256="d" * 64,
        cases_sha256="e" * 64,
        index_run_id="index-v1",
        index_manifest_sha256="f" * 64,
        embedding_model="bge-m3@sha256:abc",
        candidate_k=20,
        max_chunks_per_doc=5,
        include_parent=False,
        details=details,
        summary=summary,
    )

    assert verify_uda_finance_page_run(run_dir).summary.page_hit_at_5 == 1
    with pytest.raises(FileExistsError):
        publish_uda_finance_page_run(
            root=tmp_path,
            run_id="uda-dev-bm25-v1",
            split="dev",
            retrieval_arm="bm25",
            code_revision="b" * 40,
            protocol_sha256="c" * 64,
            dataset_manifest_sha256="d" * 64,
            cases_sha256="e" * 64,
            index_run_id="index-v1",
            index_manifest_sha256="f" * 64,
            embedding_model="bge-m3@sha256:abc",
            candidate_k=20,
            max_chunks_per_doc=5,
            include_parent=False,
            details=details,
            summary=summary,
        )
    (run_dir / "summary.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_uda_finance_page_run(run_dir)
