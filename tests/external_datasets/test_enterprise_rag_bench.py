from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.external_datasets.enterprise_rag_bench import (
    ENTERPRISE_RAG_BENCH_DATASET_REVISION,
    EnterpriseRAGBenchQuestion,
    EnterpriseRAGBenchRawDocument,
    iter_enterprise_rag_bench_documents,
)
from scripts.profile_enterprise_rag_bench import flat_chunk_count, sample_document
from scripts.publish_enterprise_rag_bench_capacity import build_public_evidence


ROOT = Path(__file__).resolve().parents[2]


def test_manifest_is_honest_about_corpus_state() -> None:
    payload = json.loads(
        (ROOT / "data_manifests" / "ENTERPRISERAG_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["dataset_revision"] == ENTERPRISE_RAG_BENCH_DATASET_REVISION
    assert payload["questions"]["question_count"] == 500
    assert payload["questions"]["download_status"] == "VERIFIED"
    assert payload["corpus"]["download_status"] == "VERIFIED_NOT_INDEXED"
    assert payload["corpus"]["sha256"] == "6b0747bf160af9427b12101537d53056ac592ada9831c1a98ae01fa50a8d2a9f"


def test_no_document_question_does_not_invent_gold() -> None:
    question = EnterpriseRAGBenchQuestion(
        question_id="qst_1",
        question_type="info_not_found",
        source_types=[],
        question="What is unavailable?",
        expected_doc_ids=[],
        gold_answer="The information is not available.",
        answer_facts=["not available"],
    )
    assert question.expected_doc_ids == []
    with pytest.raises(ValueError, match="must not invent"):
        question.model_copy(update={"expected_doc_ids": ["dsid_fake"]}).model_validate(
            {
                **question.model_dump(),
                "expected_doc_ids": ["dsid_fake"],
            }
        )


def test_retrieval_question_requires_document_gold() -> None:
    with pytest.raises(ValueError, match="requires expected documents"):
        EnterpriseRAGBenchQuestion(
            question_id="qst_2",
            question_type="basic",
            source_types=["slack"],
            question="Where is the fact?",
            expected_doc_ids=[],
            gold_answer="Answer",
            answer_facts=["Answer"],
        )


def test_duplicate_official_gold_is_preserved_with_unique_metric_view() -> None:
    question = EnterpriseRAGBenchQuestion(
        question_id="qst_0413",
        question_type="conflicting_info",
        source_types=["slack"],
        question="Which statements conflict?",
        expected_doc_ids=["dsid_1", "dsid_1"],
        gold_answer="The source contains conflicting statements.",
        answer_facts=["conflict"],
    )
    assert question.expected_doc_ids == ["dsid_1", "dsid_1"]
    assert question.unique_expected_doc_ids == ["dsid_1"]
    assert question.has_duplicate_expected_doc_ids is True


def test_document_schema_contains_only_official_fields() -> None:
    document = EnterpriseRAGBenchRawDocument(
        doc_id="dsid_1",
        source_type="gmail",
        title="Subject",
        content="Message body",
    )
    assert set(document.model_dump()) == {"doc_id", "source_type", "title", "content"}
    with pytest.raises(ValueError):
        EnterpriseRAGBenchRawDocument.model_validate(
            {**document.model_dump(), "timestamp": "invented"}
        )


def test_official_empty_fields_have_auditable_normalization() -> None:
    empty_title = EnterpriseRAGBenchRawDocument(
        doc_id="dsid_empty_title",
        source_type="slack",
        title="",
        content="real message",
    )
    assert empty_title.normalized_title == "dsid_empty_title"
    assert empty_title.normalized_text == "real message"

    empty_content = EnterpriseRAGBenchRawDocument(
        doc_id="dsid_empty_content",
        source_type="slack",
        title="general",
        content="",
    )
    assert empty_content.normalized_title == "general"
    assert empty_content.normalized_text == "general"


def test_distinct_records_with_reused_source_id_are_preserved(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = tmp_path / "documents.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "doc_id": "dsid_reused",
                    "source_type": "jira",
                    "title": "Earlier ticket",
                    "content": "Infra manager approval was requested.",
                },
                {
                    "doc_id": "dsid_reused",
                    "source_type": "jira",
                    "title": "Later ticket",
                    "content": "Cost-ops approval is sufficient.",
                },
            ]
        ),
        path,
    )

    documents = list(iter_enterprise_rag_bench_documents(path, batch_size=1))
    assert len(documents) == 2
    assert documents[0].source_native_id == documents[1].source_native_id
    assert documents[0].document_id != documents[1].document_id
    assert documents[0].raw_provenance.raw_record_sha256 != (
        documents[1].raw_provenance.raw_record_sha256
    )


def test_capacity_profile_chunk_formula_and_sampling_are_deterministic() -> None:
    assert flat_chunk_count(1, chunk_size=1800, overlap=150) == 1
    assert flat_chunk_count(1800, chunk_size=1800, overlap=150) == 1
    assert flat_chunk_count(1801, chunk_size=1800, overlap=150) == 2
    assert flat_chunk_count(3450, chunk_size=1800, overlap=150) == 2
    assert sample_document("dsid_1", modulus=50) == sample_document(
        "dsid_1", modulus=50
    )


def test_capacity_publication_rejects_quality_label_use() -> None:
    profile = {
        "schema_version": "enterprise_rag_bench_capacity_profile_v1",
        "dataset_revision": ENTERPRISE_RAG_BENCH_DATASET_REVISION,
        "documents_sha256": (
            "6b0747bf160af9427b12101537d53056ac592ada9831c1a98ae01fa50a8d2a9f"
        ),
        "documents_byte_count": 1_409_893_131,
        "document_count": 511_962,
        "unique_document_count": 511_958,
        "duplicate_document_id_count": 4,
        "source_counts": {
            "confluence": 5189,
            "fireflies": 10173,
            "github": 8052,
            "gmail": 121390,
            "google_drive": 25108,
            "hubspot": 15017,
            "jira": 6120,
            "linear": 35308,
            "slack": 285605,
        },
        "quality_labels_used": True,
        "profile_peak_rss_bytes": 1,
    }
    with pytest.raises(ValueError, match="must not consume quality labels"):
        build_public_evidence(
            profile,
            execution_git_sha="a" * 40,
            profile_sha256="b" * 64,
        )


def test_public_capacity_evidence_is_bound_and_not_a_quality_claim() -> None:
    payload = json.loads(
        (
            ROOT
            / "docs"
            / "enterprise_eval"
            / "evidence"
            / "enterprise_rag_bench_capacity_public_v1.json"
        ).read_text(encoding="utf-8")
    )
    assert payload["execution_git_sha"] == (
        "7c10f48d35c587edb6cf5a6d9d90c76d3f95e392"
    )
    assert payload["dataset"]["row_count"] == 511_962
    assert payload["measured_capacity"]["flat_chunk_count"] == 1_702_370
    assert payload["protocol"]["quality_labels_used"] is False
    assert payload["decision"]["full_scale_index"] == "CAPACITY_BLOCKED"
    assert payload["decision"]["formal_quality_score"] == "NOT_RUN"
