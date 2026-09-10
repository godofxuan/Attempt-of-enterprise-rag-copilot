"""Qrel-blind structural diagnostics, bound to source and materialized chunks."""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.documents import ChunkRecord, DocumentRecord

if TYPE_CHECKING:
    from app.ingestion.chunking import ChunkerConfig


QUALITY_ARTIFACT = "document_quality.json"


class DocumentQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["document_quality_v1"] = "document_quality_v1"
    assessment_scope: Literal["structural_checks_not_semantic_truth"] = (
        "structural_checks_not_semantic_truth"
    )
    doc_id: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_name: str
    parser_version: str
    config_sha256: str
    chunk_ids: list[str]
    chunk_layout_sha256: str
    table_rows: int
    covered_table_rows: int
    decision: Literal["ACCEPT", "REVIEW_REQUIRED", "REJECT"]
    reason_codes: list[str]


class DocumentQualityError(ValueError):
    def __init__(self, report: DocumentQualityReport):
        self.report = report
        self.code = "document_quality_" + report.decision.lower()
        super().__init__(self.code + ":" + ",".join(report.reason_codes))


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def assess_document_quality(
    document: DocumentRecord, chunks: list[ChunkRecord], config: ChunkerConfig
) -> DocumentQualityReport:
    chunks = [chunk for chunk in chunks if chunk.doc_id == document.doc_id and chunk.indexable]
    reasons = []
    covered = 0
    total = 0
    for table in document.tables:
        header = " | ".join(table.headers)
        for offset, row in enumerate(table.rows):
            total += 1
            value = " | ".join(row)
            header_offset = (
                1 if document.parser_name in {"docx", "html"} and table.locator.kind == "row" else 0
            )
            source_row = (
                table.locator.start + header_offset + offset
                if table.locator.kind in {"row", "line"}
                else table.locator.start
            )
            if any(
                chunk.kind == "table"
                and header in chunk.text.splitlines()
                and value in chunk.text.splitlines()
                and chunk.locator.label is not None
                and (
                    match := re.match(
                        re.escape(table.table_id) + r": rows=(\d+)-(\d+);", chunk.locator.label
                    )
                )
                and int(match[1]) <= offset + 1 <= int(match[2])
                and chunk.locator.kind == table.locator.kind
                and chunk.locator.start <= source_row <= (chunk.locator.end or chunk.locator.start)
                for chunk in chunks
            ):
                covered += 1
    if total != covered:
        reasons.append("missing_table_rows")
    if not chunks:
        reasons.append("no_indexable_chunks")
    if any(len(chunk.text) > config.chunk_size for chunk in chunks):
        reasons.append("chunk_budget_exceeded")
    source_fields = (
        "tenant_id",
        "acl_groups",
        "checksum",
        "region",
        "policy_id",
        "source_path",
        "format",
        "source_type",
        "department",
        "filed_department",
        "authority_level",
        "fact_ids",
        "variant",
    )
    version_fields = (
        "version_id",
        "version",
        "status",
        "effective_from",
        "effective_to",
        "supersedes_doc_id",
    )
    if any(
        any(getattr(chunk, field) != getattr(document, field) for field in source_fields)
        or any(
            getattr(chunk, field) != getattr(document.document_version, field)
            for field in version_fields
        )
        for chunk in chunks
    ):
        reasons.append("source_binding_mismatch")
    if any(
        chunk.text_hash != hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
        for chunk in chunks
    ):
        reasons.append("chunk_text_hash_mismatch")
    hard_failure = bool(reasons) or any(w.severity == "error" for w in document.parse_warnings)
    if any(w.severity == "error" for w in document.parse_warnings):
        reasons.append("parser_error_warning")
    for warning in document.parse_warnings:
        if warning.severity != "info":
            reasons.append("parse_warning:" + warning.code)
    decision = "REJECT" if hard_failure else "REVIEW_REQUIRED" if reasons else "ACCEPT"
    return DocumentQualityReport(
        doc_id=document.doc_id,
        source_sha256=document.checksum,
        parser_name=document.parser_name,
        parser_version=document.parser_version,
        config_sha256=hashlib.sha256(_canonical(config.model_dump(mode="json"))).hexdigest(),
        chunk_ids=[chunk.chunk_id for chunk in chunks],
        chunk_layout_sha256=hashlib.sha256(
            _canonical([chunk.model_dump(mode="json") for chunk in chunks])
        ).hexdigest(),
        table_rows=total,
        covered_table_rows=covered,
        decision=decision,
        reason_codes=sorted(set(reasons)),
    )


def require_document_quality(
    document: DocumentRecord, chunks: list[ChunkRecord], config: ChunkerConfig
) -> DocumentQualityReport:
    report = assess_document_quality(document, chunks, config)
    if report.decision != "ACCEPT":
        raise DocumentQualityError(report)
    return report


def quality_artifact(
    documents: list[DocumentRecord], chunks: list[ChunkRecord], config: ChunkerConfig
) -> bytes:
    reports = [require_document_quality(document, chunks, config) for document in documents]
    return _canonical([report.model_dump(mode="json") for report in reports])
