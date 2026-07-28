import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pytest

from app.corpus.schemas import EvalCase, EvalUserContext
from app.domain.documents import SourceLocator
from app.domain.queries import SearchHit, SearchRequest, SearchResult
from app.external_datasets.financebench import (
    FinanceBenchPreparedCase,
    FinanceBenchPreparedEvidence,
)
from app.external_datasets.financebench_page_eval import (
    build_financebench_page_manifest,
    evaluate_financebench_page_cases,
    load_financebench_page_freeze_protocol,
    publish_financebench_page_run,
    summarize_financebench_page_cases,
    verify_financebench_page_run,
)
from app.retrieval.page_reranker import PageRerankResult


def _case(
    *,
    case_id: str = "fb-1",
    question: str = "What was Alpha's FY2022 revenue?",
) -> EvalCase:
    return EvalCase(
        case_id=case_id,
        question=question,
        task_type="fact_lookup",
        answer_mode="answered",
        user_context=EvalUserContext(
            user_id="financebench-evaluator",
            tenant="financebench-public",
            region="global",
            groups=["public_benchmark"],
        ),
        required_fact_ids=[case_id],
        gold_doc_ids=["doc-a"],
        expected_answer="$1.00",
        expected_authority_doc_ids=["doc-a"],
        tags=["external", "financebench"],
    )


def _evidence_case(
    *,
    case_id: str = "fb-1",
    question: str = "What was Alpha's FY2022 revenue?",
    split: Literal["dev", "test"] = "dev",
) -> FinanceBenchPreparedCase:
    return FinanceBenchPreparedCase(
        case_id=case_id,
        split=split,
        company="Alpha",
        question=question,
        answer="$1.00",
        justification="The filing reports the value.",
        question_type="metrics-generated",
        question_reasoning="Information extraction",
        gold_doc_ids=["doc-a"],
        evidence=[
            FinanceBenchPreparedEvidence(
                doc_id="doc-a",
                page_number=2,
                evidence_text="Revenue was $1.00.",
                evidence_text_full_page="Revenue was $1.00 in FY2022.",
            )
        ],
    )


def _hit(
    rank: int,
    *,
    doc_id: str,
    page_number: int,
    score: float | None = None,
) -> SearchHit:
    return SearchHit(
        index_run_id="index-v1",
        chunk_id=f"chunk-{rank}",
        doc_id=doc_id,
        policy_id=f"policy-{doc_id}",
        source_path=f"{doc_id}.pdf",
        section_path=[f"Page {page_number}"],
        locator=SourceLocator(
            kind="page",
            start=page_number,
            end=page_number,
            label=f"page {page_number}",
        ),
        matched_text=f"matched text {rank}",
        context_text=f"context text {rank}",
        tenant_id="financebench-public",
        region="global",
        acl_groups=["public_benchmark"],
        version_id=f"{doc_id}-version",
        version="2022",
        status="active",
        authority_level=100,
        variant="authoritative",
        fused_score=score if score is not None else 1.0 / rank,
        dense_score=score,
    )


class _Pipeline:
    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.calls = 0
        self.last_request: SearchRequest | None = None

    def search(self, request: SearchRequest) -> SearchResult:
        self.calls += 1
        self.last_request = request
        return SearchResult(
            request_id=request.request_id,
            query=request.query,
            mode=request.mode,
            index_run_id="index-v1",
            manifest_sha256="a" * 64,
            hits=self.hits[: request.top_k],
            visible_candidate_count=len(self.hits),
            internal_denied_count=0,
            stage_counts={"returned": min(len(self.hits), request.top_k)},
            stop_reason="ok" if self.hits else "no_match",
        )


class _PolicyPipeline(_Pipeline):
    def __init__(self, hits_by_policy: dict[str, list[SearchHit]]) -> None:
        super().__init__([])
        self.hits_by_policy = hits_by_policy

    def search(self, request: SearchRequest) -> SearchResult:
        policy_ids = request.filters.policy_ids
        assert len(policy_ids) == 1
        self.hits = self.hits_by_policy[policy_ids[0]]
        return super().search(request)


class _BatchPolicyPipeline(_PolicyPipeline):
    def __init__(self, hits_by_policy: dict[str, list[SearchHit]]) -> None:
        super().__init__(hits_by_policy)
        self.batch_calls = 0

    def search_many(
        self,
        requests: list[SearchRequest],
    ) -> list[SearchResult]:
        self.batch_calls += 1
        return [self.search(request) for request in requests]


class _MalformedBatchPipeline(_BatchPolicyPipeline):
    def __init__(
        self,
        hits_by_policy: dict[str, list[SearchHit]],
        *,
        failure: str,
    ) -> None:
        super().__init__(hits_by_policy)
        self.failure = failure

    def search_many(
        self,
        requests: list[SearchRequest],
    ) -> list[SearchResult]:
        results = super().search_many(requests)
        if self.failure == "missing":
            return results[:-1]
        return list(reversed(results))


class _ReversePageReranker:
    def __init__(self) -> None:
        self.calls = 0

    def rerank(self, *, question, candidates) -> PageRerankResult:
        self.calls += 1
        rows = tuple(reversed(candidates))
        return PageRerankResult(
            hits=rows,
            admitted_count=len(rows),
            quarantined_count=0,
            guard_rule_ids=(),
        )


def _evaluated_details():
    pipeline = _Pipeline(
        [
            _hit(1, doc_id="doc-a", page_number=2),
            _hit(2, doc_id="doc-b", page_number=4),
        ]
    )
    details = evaluate_financebench_page_cases(
        cases=[_case()],
        evidence_cases=[_evidence_case()],
        pipeline=pipeline,
    )
    return details, pipeline


def test_financebench_page_eval_combines_document_and_page_metrics() -> None:
    details, pipeline = _evaluated_details()
    summary = summarize_financebench_page_cases(details)

    assert pipeline.calls == 1
    assert details[0].document_recall_at_5 == 1.0
    assert details[0].page_score.cutoffs[-1].page_recall == 1.0
    assert details[0].page_score.cutoffs[-1].page_precision == 0.5
    assert details[0].passed is True
    assert summary.case_count == 1
    assert summary.passed_case_rate == 1.0
    assert summary.cutoffs[-1].complete_page_recall_rate == 1.0


def test_financebench_page_eval_applies_explicit_document_depth() -> None:
    pipeline = _Pipeline([_hit(1, doc_id="doc-a", page_number=2)])

    evaluate_financebench_page_cases(
        cases=[_case()],
        evidence_cases=[_evidence_case()],
        pipeline=pipeline,
        max_chunks_per_doc=4,
        include_parent=False,
    )

    assert pipeline.last_request is not None
    assert pipeline.last_request.max_chunks_per_doc == 4
    assert pipeline.last_request.include_parent is False


def test_financebench_page_eval_drills_into_ranked_documents() -> None:
    broad = _Pipeline(
        [
            _hit(1, doc_id="doc-a", page_number=90),
            _hit(2, doc_id="doc-b", page_number=10),
        ]
    )
    focused = _BatchPolicyPipeline(
        {
            "policy-doc-a": [
                _hit(11, doc_id="doc-a", page_number=2),
                _hit(12, doc_id="doc-a", page_number=3),
                _hit(13, doc_id="doc-a", page_number=4),
                _hit(14, doc_id="doc-a", page_number=5),
                _hit(15, doc_id="doc-a", page_number=6),
            ],
            "policy-doc-b": [
                _hit(21, doc_id="doc-b", page_number=10),
                _hit(22, doc_id="doc-b", page_number=11),
            ],
        }
    )

    details = evaluate_financebench_page_cases(
        cases=[_case()],
        evidence_cases=[_evidence_case()],
        pipeline=broad,
        page_drilldown_backend=focused,
        drilldown_max_documents=3,
        drilldown_chunks_per_doc=5,
        drilldown_mode="dense",
    )

    assert broad.calls == 1
    assert focused.calls == 2
    assert focused.batch_calls == 1
    assert focused.last_request is not None
    assert focused.last_request.mode == "dense"
    assert details[0].document_recall_at_5 == 1.0
    assert details[0].page_search_count == 2
    assert details[0].page_candidate_score is not None
    assert details[0].page_candidate_score.cutoffs[-1].page_recall == 1.0
    assert details[0].page_score.cutoffs[-1].page_recall == 1.0
    summary = summarize_financebench_page_cases(details)
    assert [item.cutoff for item in summary.candidate_cutoffs] == [5, 10, 20]
    assert [
        (item.doc_id, item.page_number)
        for item in details[0].page_score.ranked_pages
    ] == [
        ("doc-a", 2),
        ("doc-a", 3),
        ("doc-a", 4),
        ("doc-a", 5),
        ("doc-b", 10),
    ]


def test_financebench_page_eval_global_page_score_merges_and_deduplicates() -> None:
    broad = _Pipeline(
        [
            _hit(1, doc_id="doc-a", page_number=90),
            _hit(2, doc_id="doc-b", page_number=10),
        ]
    )
    focused = _BatchPolicyPipeline(
        {
            "policy-doc-a": [
                _hit(11, doc_id="doc-a", page_number=8, score=0.80),
                _hit(12, doc_id="doc-a", page_number=8, score=0.79),
                _hit(13, doc_id="doc-a", page_number=9, score=0.60),
            ],
            "policy-doc-b": [
                _hit(21, doc_id="doc-b", page_number=2, score=0.95),
                _hit(22, doc_id="doc-b", page_number=3, score=0.70),
            ],
        }
    )

    details = evaluate_financebench_page_cases(
        cases=[_case()],
        evidence_cases=[_evidence_case()],
        pipeline=broad,
        page_drilldown_backend=focused,
        drilldown_max_documents=2,
        drilldown_chunks_per_doc=5,
        drilldown_mode="dense",
        drilldown_merge_mode="global_page_score",
    )

    assert [
        (item.doc_id, item.page_number)
        for item in details[0].page_score.ranked_pages
    ] == [
        ("doc-b", 2),
        ("doc-a", 8),
        ("doc-b", 3),
        ("doc-a", 9),
    ]
    assert details[0].stage_counts["page_drilldown_candidates"] == 4


def test_financebench_page_eval_global_score_rejects_non_dense_mode() -> None:
    with pytest.raises(ValueError, match="requires comparable dense"):
        evaluate_financebench_page_cases(
            cases=[_case()],
            evidence_cases=[_evidence_case()],
            pipeline=_Pipeline([]),
            drilldown_mode="hybrid",
            drilldown_merge_mode="global_page_score",
        )


def test_financebench_page_eval_applies_page_reranker_to_candidate_pool() -> None:
    broad = _Pipeline([_hit(1, doc_id="doc-a", page_number=90)])
    focused = _PolicyPipeline(
        {
            "policy-doc-a": [
                _hit(11, doc_id="doc-a", page_number=8, score=0.80),
                _hit(12, doc_id="doc-a", page_number=2, score=0.70),
            ]
        }
    )
    reranker = _ReversePageReranker()

    details = evaluate_financebench_page_cases(
        cases=[_case()],
        evidence_cases=[_evidence_case()],
        pipeline=broad,
        page_drilldown_backend=focused,
        drilldown_max_documents=1,
        drilldown_mode="dense",
        drilldown_merge_mode="global_page_score",
        page_reranker=reranker,
    )

    assert reranker.calls == 1
    assert details[0].page_score.ranked_pages[0].page_number == 2
    assert details[0].stage_counts["page_reranker_calls"] == 1
    assert details[0].stage_counts["page_reranker_admitted"] == 2
    assert details[0].stage_counts["page_reranker_quarantined"] == 0
    assert details[0].page_reranker_score is not None
    assert details[0].page_reranker_latency_ms >= 0


def test_financebench_page_eval_can_preserve_dense_head_before_reranking() -> None:
    broad = _Pipeline([_hit(1, doc_id="doc-a", page_number=90)])
    focused = _PolicyPipeline(
        {
            "policy-doc-a": [
                _hit(11, doc_id="doc-a", page_number=2, score=0.80),
                _hit(12, doc_id="doc-a", page_number=8, score=0.70),
            ]
        }
    )

    details = evaluate_financebench_page_cases(
        cases=[_case()],
        evidence_cases=[_evidence_case()],
        pipeline=broad,
        page_drilldown_backend=focused,
        drilldown_max_documents=1,
        drilldown_mode="dense",
        drilldown_merge_mode="global_page_score",
        page_reranker=_ReversePageReranker(),
        reranker_dense_head_count=1,
    )

    assert [
        item.page_number for item in details[0].page_score.ranked_pages
    ] == [2, 8]
    assert details[0].passed is True


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("missing", "different result count"),
        ("reordered", "out of order"),
    ],
)
def test_financebench_page_eval_rejects_malformed_batch_results(
    failure: str,
    message: str,
) -> None:
    broad = _Pipeline(
        [
            _hit(1, doc_id="doc-a", page_number=90),
            _hit(2, doc_id="doc-b", page_number=10),
        ]
    )
    focused = _MalformedBatchPipeline(
        {
            "policy-doc-a": [_hit(11, doc_id="doc-a", page_number=2)],
            "policy-doc-b": [_hit(21, doc_id="doc-b", page_number=10)],
        },
        failure=failure,
    )

    with pytest.raises(ValueError, match=message):
        evaluate_financebench_page_cases(
            cases=[_case()],
            evidence_cases=[_evidence_case()],
            pipeline=broad,
            page_drilldown_backend=focused,
            drilldown_max_documents=2,
            drilldown_mode="dense",
        )


def test_financebench_page_eval_rejects_misaligned_private_sidecar() -> None:
    pipeline = _Pipeline([])

    with pytest.raises(ValueError, match="mismatch"):
        evaluate_financebench_page_cases(
            cases=[_case()],
            evidence_cases=[_evidence_case(question="Different question")],
            pipeline=pipeline,
        )

    assert pipeline.calls == 0


def test_financebench_page_eval_keeps_dev_and_test_sidecars_separate() -> None:
    pipeline = _Pipeline([_hit(1, doc_id="doc-a", page_number=2)])

    with pytest.raises(ValueError, match="expected dev evidence"):
        evaluate_financebench_page_cases(
            cases=[_case()],
            evidence_cases=[_evidence_case(split="test")],
            pipeline=pipeline,
        )

    details = evaluate_financebench_page_cases(
        cases=[_case()],
        evidence_cases=[_evidence_case(split="test")],
        pipeline=pipeline,
        split="test",
    )
    assert details[0].passed is True


def test_financebench_page_eval_normalizes_same_page_evidence_snippets() -> None:
    evidence = _evidence_case().model_copy(
        update={
            "evidence": [
                *_evidence_case().evidence,
                FinanceBenchPreparedEvidence(
                    doc_id="doc-a",
                    page_number=2,
                    evidence_text="A second supporting excerpt.",
                    evidence_text_full_page="Revenue and a second excerpt.",
                ),
            ]
        }
    )

    details = evaluate_financebench_page_cases(
        cases=[_case()],
        evidence_cases=[evidence],
        pipeline=_Pipeline([_hit(1, doc_id="doc-a", page_number=2)]),
    )

    assert len(details[0].page_score.gold_pages) == 1
    assert details[0].stage_counts["gold_evidence_snippets"] == 2
    assert details[0].stage_counts["gold_unique_pages"] == 1
    assert details[0].passed is True


def test_financebench_page_freeze_protocol_is_strict(tmp_path: Path) -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "external_datasets"
        / "evidence"
        / "financebench_page_retrieval_freeze_v1.json"
    )
    protocol, protocol_sha256 = load_financebench_page_freeze_protocol(source)

    assert protocol.configuration.drilldown_max_documents == 1
    assert protocol.configuration.drilldown_mode == "dense"
    assert len(protocol_sha256) == 64

    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["configuration"]["drilldown_max_documents"] = 2
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Input should be 1"):
        load_financebench_page_freeze_protocol(tampered)


def test_financebench_page_run_is_immutable_and_self_verifying(
    tmp_path: Path,
) -> None:
    details, _ = _evaluated_details()
    summary = summarize_financebench_page_cases(details)
    manifest = build_financebench_page_manifest(
        run_id="financebench-pages-dev-v1",
        source_hashes={
            "dataset_manifest": "1" * 64,
            "dev_eval": "2" * 64,
            "dev_evidence": "3" * 64,
        },
        index_run_id="index-v1",
        index_manifest_sha256="4" * 64,
        entity_catalog_sha256="5" * 64,
        embedding_model="bge-m3",
        embedding_calls=1,
        candidate_k=20,
        max_chunks_per_doc=2,
        include_parent=True,
        page_drilldown=False,
        drilldown_max_documents=3,
        drilldown_chunks_per_doc=5,
        drilldown_mode="hybrid",
        summary=summary,
        created_at_utc=datetime(2026, 7, 28, tzinfo=timezone.utc),
    )

    output = publish_financebench_page_run(
        root=tmp_path / "runs",
        manifest=manifest,
        details=details,
    )
    verified = verify_financebench_page_run(output)

    assert verified.schema_version == "financebench_page_retrieval_run_v2"
    assert verified.config["drilldown_merge_mode"] == "quota"
    assert verified.config["page_reranker"] == "none"
    assert verified.config["reranker_dense_head_count"] == 0
    assert verified.generation_calls == 0
    assert verified.summary == summary
    assert set(verified.artifacts) == {"summary.json", "details.jsonl"}
    assert all(item.byte_count > 1 for item in verified.artifacts.values())
    with pytest.raises(FileExistsError):
        publish_financebench_page_run(
            root=tmp_path / "runs",
            manifest=manifest,
            details=details,
        )

    (output / "summary.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact mismatch"):
        verify_financebench_page_run(output)


def test_financebench_page_manifest_rejects_unsafe_run_id() -> None:
    details, _ = _evaluated_details()
    summary = summarize_financebench_page_cases(details)

    with pytest.raises(ValueError, match="run ID"):
        build_financebench_page_manifest(
            run_id="../escape",
            source_hashes={
                "dataset_manifest": "1" * 64,
                "dev_eval": "2" * 64,
                "dev_evidence": "3" * 64,
            },
            index_run_id="index-v1",
            index_manifest_sha256="4" * 64,
            entity_catalog_sha256="5" * 64,
            embedding_model="bge-m3",
            embedding_calls=1,
            candidate_k=20,
            max_chunks_per_doc=2,
            include_parent=True,
            page_drilldown=False,
            drilldown_max_documents=3,
            drilldown_chunks_per_doc=5,
            drilldown_mode="hybrid",
            summary=summary,
        )


def test_financebench_test_manifest_requires_frozen_provenance() -> None:
    details, _ = _evaluated_details()
    summary = summarize_financebench_page_cases(details)

    with pytest.raises(ValueError, match="requires code and freeze provenance"):
        build_financebench_page_manifest(
            run_id="financebench-pages-test-v1",
            split="test",
            source_hashes={
                "dataset_manifest": "1" * 64,
                "test_eval": "2" * 64,
                "test_evidence": "3" * 64,
            },
            index_run_id="index-v1",
            index_manifest_sha256="4" * 64,
            entity_catalog_sha256="5" * 64,
            embedding_model="bge-m3",
            embedding_calls=1,
            candidate_k=20,
            max_chunks_per_doc=2,
            include_parent=True,
            page_drilldown=True,
            drilldown_max_documents=1,
            drilldown_chunks_per_doc=5,
            drilldown_mode="dense",
            summary=summary,
        )

    manifest = build_financebench_page_manifest(
        run_id="financebench-pages-test-v1",
        split="test",
        source_hashes={
            "dataset_manifest": "1" * 64,
            "test_eval": "2" * 64,
            "test_evidence": "3" * 64,
        },
        index_run_id="index-v1",
        index_manifest_sha256="4" * 64,
        entity_catalog_sha256="5" * 64,
        embedding_model="bge-m3",
        embedding_calls=1,
        code_revision="6" * 40,
        freeze_protocol_sha256="7" * 64,
        candidate_k=20,
        max_chunks_per_doc=2,
        include_parent=True,
        page_drilldown=True,
        drilldown_max_documents=1,
        drilldown_chunks_per_doc=5,
        drilldown_mode="dense",
        summary=summary,
    )
    assert manifest.split == "test"
