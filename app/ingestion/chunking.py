from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.documents import (
    ChunkKind,
    ChunkRecord,
    DocumentRecord,
    ParsedSection,
    SourceLocator,
)


ChunkMode = Literal["fixed", "heading", "parent_child"]


class ChunkerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: ChunkMode
    chunk_size: int = Field(default=500, ge=1)
    overlap: int = Field(default=80, ge=0)
    parent_size: int = Field(default=1000, ge=1)
    child_size: int = Field(default=250, ge=1)
    table_rows_per_chunk: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def validate_sizes(self) -> ChunkerConfig:
        window_size = self.child_size if self.mode == "parent_child" else self.chunk_size
        if self.overlap >= window_size:
            raise ValueError("overlap must be smaller than the active chunk size")
        if self.mode == "parent_child" and self.child_size > self.parent_size:
            raise ValueError("child_size must not exceed parent_size")
        return self


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _windows(text: str, size: int, overlap: int) -> list[tuple[int, int, str]]:
    windows: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        value = text[start:end].strip()
        if value:
            windows.append((start, end, value))
        if end == len(text):
            break
        start = end - overlap
    return windows


def _chunk_id(
    record: DocumentRecord,
    config: ChunkerConfig,
    *,
    kind: ChunkKind,
    section_path: list[str],
    locator: SourceLocator,
    ordinal: int,
    text: str,
    parent_chunk_id: str | None,
) -> str:
    payload = {
        "doc_id": record.doc_id,
        "config": config.model_dump(mode="json"),
        "kind": kind,
        "section_path": section_path,
        "locator": locator.model_dump(mode="json"),
        "ordinal": ordinal,
        "text_hash": _text_hash(text),
        "parent_chunk_id": parent_chunk_id,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:20]
    return f"{record.doc_id}::{kind}::{digest}"


def _make_chunk(
    record: DocumentRecord,
    config: ChunkerConfig,
    *,
    kind: ChunkKind,
    indexable: bool,
    text: str,
    section_path: list[str],
    locator: SourceLocator,
    ordinal: int,
    parent_chunk_id: str | None = None,
) -> ChunkRecord:
    version = record.document_version
    return ChunkRecord(
        chunk_id=_chunk_id(
            record,
            config,
            kind=kind,
            section_path=section_path,
            locator=locator,
            ordinal=ordinal,
            text=text,
            parent_chunk_id=parent_chunk_id,
        ),
        doc_id=record.doc_id,
        parent_chunk_id=parent_chunk_id,
        kind=kind,
        indexable=indexable,
        text=text,
        section_path=section_path,
        locator=locator,
        source_path=record.source_path,
        format=record.format,
        source_type=record.source_type,
        policy_id=record.policy_id,
        department=record.department,
        filed_department=record.filed_department,
        tenant_id=record.tenant_id,
        region=record.region,
        acl_groups=list(record.acl_groups),
        version_id=version.version_id,
        version=version.version,
        status=version.status,
        effective_from=version.effective_from,
        effective_to=version.effective_to,
        supersedes_doc_id=version.supersedes_doc_id,
        authority_level=record.authority_level,
        fact_ids=list(record.fact_ids),
        variant=record.variant,
        checksum=record.checksum,
        text_hash=_text_hash(text),
    )


def _fallback_section(record: DocumentRecord) -> ParsedSection:
    return ParsedSection(
        heading=record.title,
        level=0,
        path=[record.title],
        text=record.text,
        locator=SourceLocator(
            kind="document",
            start=1,
            end=1,
            label="whole document",
        ),
    )


def _fixed_chunks(
    record: DocumentRecord,
    config: ChunkerConfig,
) -> list[ChunkRecord]:
    result: list[ChunkRecord] = []
    for ordinal, (start, end, text) in enumerate(
        _windows(record.text, config.chunk_size, config.overlap),
        start=1,
    ):
        result.append(
            _make_chunk(
                record,
                config,
                kind="fixed",
                indexable=True,
                text=text,
                section_path=[record.title],
                locator=SourceLocator(
                    kind="character",
                    start=start + 1,
                    end=end,
                    label=f"characters {start + 1}-{end}",
                ),
                ordinal=ordinal,
            )
        )
    return result


def _heading_chunks(
    record: DocumentRecord,
    config: ChunkerConfig,
) -> list[ChunkRecord]:
    result: list[ChunkRecord] = []
    ordinal = 0
    for section in record.sections or [_fallback_section(record)]:
        for _, _, text in _windows(section.text, config.chunk_size, config.overlap):
            ordinal += 1
            result.append(
                _make_chunk(
                    record,
                    config,
                    kind="section",
                    indexable=True,
                    text=text,
                    section_path=list(section.path),
                    locator=section.locator,
                    ordinal=ordinal,
                )
            )
    return result


def _parent_child_chunks(
    record: DocumentRecord,
    config: ChunkerConfig,
) -> list[ChunkRecord]:
    result: list[ChunkRecord] = []
    parent_ordinal = 0
    child_ordinal = 0
    for section in record.sections or [_fallback_section(record)]:
        for _, _, parent_text in _windows(section.text, config.parent_size, 0):
            parent_ordinal += 1
            parent = _make_chunk(
                record,
                config,
                kind="parent",
                indexable=False,
                text=parent_text,
                section_path=list(section.path),
                locator=section.locator,
                ordinal=parent_ordinal,
            )
            result.append(parent)
            for _, _, child_text in _windows(
                parent_text,
                config.child_size,
                config.overlap,
            ):
                child_ordinal += 1
                result.append(
                    _make_chunk(
                        record,
                        config,
                        kind="child",
                        indexable=True,
                        text=child_text,
                        section_path=list(section.path),
                        locator=section.locator,
                        ordinal=child_ordinal,
                        parent_chunk_id=parent.chunk_id,
                    )
                )

    table_ordinal = 0
    for table in record.tables:
        for offset in range(0, len(table.rows), config.table_rows_per_chunk):
            rows = table.rows[offset : offset + config.table_rows_per_chunk]
            if not rows:
                continue
            table_ordinal += 1
            text = "\n".join(
                [
                    " | ".join(table.headers),
                    *(" | ".join(row) for row in rows),
                ]
            )
            start = table.locator.start + offset
            end = start + len(rows) - 1
            result.append(
                _make_chunk(
                    record,
                    config,
                    kind="table",
                    indexable=True,
                    text=text,
                    section_path=[table.caption or f"Table {table.table_id}"],
                    locator=SourceLocator(
                        kind="row",
                        start=start,
                        end=end,
                        label=f"{table.table_id} rows {start}-{end}",
                    ),
                    ordinal=table_ordinal,
                )
            )
    return result


def chunk_document(
    record: DocumentRecord,
    config: ChunkerConfig,
) -> list[ChunkRecord]:
    if config.mode == "fixed":
        chunks = _fixed_chunks(record, config)
    elif config.mode == "heading":
        chunks = _heading_chunks(record, config)
    else:
        chunks = _parent_child_chunks(record, config)
    if not chunks:
        raise ValueError(f"chunker produced no chunks for {record.doc_id!r}")
    ids = [chunk.chunk_id for chunk in chunks]
    if len(ids) != len(set(ids)):
        raise AssertionError(f"chunk IDs are not unique for {record.doc_id!r}")
    return chunks
