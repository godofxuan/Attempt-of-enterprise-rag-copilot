from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.external_datasets.enterprise_rag_bench import (
    ENTERPRISE_RAG_BENCH_DATASET_REVISION,
    EnterpriseRAGBenchQuestion,
    EnterpriseRAGBenchRawDocument,
)


ROOT = Path(__file__).resolve().parents[2]


def test_partial_manifest_is_honest_about_corpus_state() -> None:
    payload = json.loads(
        (ROOT / "data_manifests" / "ENTERPRISE_RAG_BENCH_QUESTIONS_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["dataset_revision"] == ENTERPRISE_RAG_BENCH_DATASET_REVISION
    assert payload["questions"]["question_count"] == 500
    assert payload["questions"]["download_status"] == "VERIFIED"
    assert payload["corpus"]["download_status"] == "NOT_DOWNLOADED"
    assert payload["corpus"]["sha256"] is None


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
