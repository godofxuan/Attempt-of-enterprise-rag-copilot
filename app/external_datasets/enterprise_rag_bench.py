from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enterprise_documents import EnterpriseDocument, RawProvenance
from app.external_datasets.wixqa import canonical_json_bytes


ENTERPRISE_RAG_BENCH_GITHUB_REVISION = (
    "d36685e273713975ee20299bbf1ab64165575b3c"
)
ENTERPRISE_RAG_BENCH_DATASET_REVISION = (
    "69916e31c68aa5963c00248fd7f0bc12d04fd235"
)
DEFAULT_ENTERPRISE_RAG_BENCH_ROOT = Path(
    ".private/external/enterprise_rag_bench/dataset"
)
QuestionType = Literal[
    "basic",
    "semantic",
    "intra_document_reasoning",
    "project_related",
    "constrained",
    "conflicting_info",
    "completeness",
    "miscellaneous",
    "high_level",
    "info_not_found",
]
SourceType = Literal[
    "slack",
    "gmail",
    "linear",
    "google_drive",
    "hubspot",
    "fireflies",
    "github",
    "jira",
    "confluence",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EnterpriseRAGBenchQuestion(_StrictModel):
    question_id: str = Field(pattern=r"^qst_[A-Za-z0-9_-]+$")
    question_type: QuestionType
    source_types: list[SourceType] = Field(default_factory=list)
    question: str = Field(min_length=1)
    expected_doc_ids: list[str] = Field(default_factory=list)
    gold_answer: str = Field(min_length=1)
    answer_facts: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ground_truth_boundary(self) -> "EnterpriseRAGBenchQuestion":
        if len(self.source_types) != len(set(self.source_types)):
            raise ValueError("source types must be unique")
        no_document_gold = self.question_type in {"high_level", "info_not_found"}
        if no_document_gold and (self.source_types or self.expected_doc_ids):
            raise ValueError("no-document category must not invent document gold")
        if not no_document_gold and not self.expected_doc_ids:
            raise ValueError("retrieval category requires expected documents")
        return self

    @property
    def unique_expected_doc_ids(self) -> list[str]:
        return list(dict.fromkeys(self.expected_doc_ids))

    @property
    def has_duplicate_expected_doc_ids(self) -> bool:
        return len(self.expected_doc_ids) != len(self.unique_expected_doc_ids)


class EnterpriseRAGBenchRawDocument(_StrictModel):
    doc_id: str = Field(pattern=r"^dsid_[A-Za-z0-9_-]+$")
    source_type: SourceType
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)


def load_enterprise_rag_bench_questions(
    path: Path = DEFAULT_ENTERPRISE_RAG_BENCH_ROOT / "questions" / "test.parquet",
) -> list[EnterpriseRAGBenchQuestion]:
    table = _read_parquet(Path(path))
    expected = {
        "question_id",
        "question_type",
        "source_types",
        "question",
        "expected_doc_ids",
        "gold_answer",
        "answer_facts",
    }
    if set(table.column_names) != expected:
        raise ValueError("EnterpriseRAG-Bench question schema mismatch")
    questions = [
        EnterpriseRAGBenchQuestion.model_validate(row) for row in table.to_pylist()
    ]
    _require_unique((item.question_id for item in questions), "question ID")
    return questions


def iter_enterprise_rag_bench_documents(
    path: Path = DEFAULT_ENTERPRISE_RAG_BENCH_ROOT / "documents" / "test.parquet",
    *,
    batch_size: int = 1000,
) -> Iterator[EnterpriseDocument]:
    if batch_size < 1 or batch_size > 10_000:
        raise ValueError("document batch size must be between 1 and 10000")
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(Path(path))
    expected = {"doc_id", "source_type", "title", "content"}
    if set(parquet.schema_arrow.names) != expected:
        raise ValueError("EnterpriseRAG-Bench document schema mismatch")
    seen: set[str] = set()
    source_row = 0
    for batch in parquet.iter_batches(batch_size=batch_size):
        for payload in batch.to_pylist():
            source_row += 1
            raw = EnterpriseRAGBenchRawDocument.model_validate(payload)
            if raw.doc_id in seen:
                raise ValueError(f"duplicate EnterpriseRAG-Bench doc ID: {raw.doc_id}")
            seen.add(raw.doc_id)
            raw_hash = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
            yield EnterpriseDocument(
                document_id=f"enterprise-rag-bench:{raw.doc_id}",
                source_type=raw.source_type,
                source_native_id=raw.doc_id,
                title=raw.title,
                text=raw.content,
                source_metadata={"source_type": raw.source_type},
                raw_provenance=RawProvenance(
                    dataset_name="EnterpriseRAG-Bench",
                    source_revision=ENTERPRISE_RAG_BENCH_DATASET_REVISION,
                    source_file="data/documents/test.parquet",
                    source_row=source_row,
                    source_native_id=raw.doc_id,
                    raw_record_sha256=raw_hash,
                ),
            )


def question_ids_sha256(questions: list[EnterpriseRAGBenchQuestion]) -> str:
    return hashlib.sha256(
        canonical_json_bytes([item.question_id for item in questions])
    ).hexdigest()


def _read_parquet(path: Path):
    import pyarrow.parquet as pq

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    return pq.read_table(path)


def _require_unique(values: Iterator[str], label: str) -> None:
    rows = list(values)
    if len(rows) != len(set(rows)):
        raise ValueError(f"EnterpriseRAG-Bench {label} values must be unique")


__all__ = [
    "DEFAULT_ENTERPRISE_RAG_BENCH_ROOT",
    "ENTERPRISE_RAG_BENCH_DATASET_REVISION",
    "ENTERPRISE_RAG_BENCH_GITHUB_REVISION",
    "EnterpriseRAGBenchQuestion",
    "EnterpriseRAGBenchRawDocument",
    "iter_enterprise_rag_bench_documents",
    "load_enterprise_rag_bench_questions",
    "question_ids_sha256",
]
