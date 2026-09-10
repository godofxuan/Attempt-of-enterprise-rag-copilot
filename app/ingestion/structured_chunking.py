"""Bounded table-aware chunks; legacy chunk modes keep their original meaning."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.domain.documents import DocumentRecord, SourceLocator
from app.ingestion.markdown_tables import without_markdown_tables

if TYPE_CHECKING:
    from app.ingestion.chunking import ChunkerConfig


def _prose(text: str, record: DocumentRecord) -> str:
    if record.parser_name == "markdown" and record.tables:
        return without_markdown_tables(text)
    for table in record.tables:
        serialized = "\n".join(
            [" | ".join(table.headers), *(" | ".join(row) for row in table.rows)]
        )
        # Only remove the complete, exact serialized table, never common row values.
        text = text.replace(serialized, "", 1)
    return text.strip()


def structure_chunks(record: DocumentRecord, config: ChunkerConfig):
    from app.ingestion.chunking import _fallback_section, _make_chunk, _windows

    chunks = []
    for table in record.tables:
        if any(
            "\n" in cell or "\r" in cell for row in [table.headers, *table.rows] for cell in row
        ):
            raise ValueError(f"multiline_table_cell:{table.table_id}")
    sections = record.sections or [_fallback_section(record)]
    for section in sections:
        prose = _prose(section.text, record)
        for _, _, text in _windows(prose, config.chunk_size, config.overlap):
            chunks.append(
                _make_chunk(
                    record,
                    config,
                    kind="section",
                    indexable=True,
                    text=text,
                    section_path=list(section.path),
                    locator=section.locator,
                    ordinal=len(chunks) + 1,
                )
            )
    for table in record.tables:
        header = " | ".join(table.headers)
        prefix = header
        if table.caption:
            prefix = table.caption + "\n" + header
        offset = 0
        while offset < len(table.rows):
            rows: list[str] = []
            while offset + len(rows) < len(table.rows) and len(rows) < config.table_rows_per_chunk:
                row = " | ".join(table.rows[offset + len(rows)])
                candidate = "\n".join([prefix, *rows, row])
                if len(candidate) > config.chunk_size:
                    if not rows:
                        raise ValueError(
                            f"table_row_budget_exceeded:{table.table_id}:row={offset + 1}"
                        )
                    break
                rows.append(row)
            if not rows:
                raise ValueError("table_chunk_made_no_progress")
            row_addressable = table.locator.kind in {"row", "line"}
            header_offset = (
                1 if record.parser_name in {"docx", "html"} and table.locator.kind == "row" else 0
            )
            start = (
                table.locator.start + header_offset + offset
                if row_addressable
                else table.locator.start
            )
            end = start + len(rows) - 1 if row_addressable else (table.locator.end or start)
            chunks.append(
                _make_chunk(
                    record,
                    config,
                    kind="table",
                    indexable=True,
                    text="\n".join([prefix, *rows]),
                    section_path=[record.title, table.caption or table.table_id],
                    locator=SourceLocator(
                        kind=table.locator.kind,
                        start=start,
                        end=end,
                        label=(
                            f"{table.table_id}: rows={offset + 1}-{offset + len(rows)}; "
                            f"{table.locator.label or 'source table'}"
                        ),
                    ),
                    ordinal=len(chunks) + 1,
                )
            )
            offset += len(rows)
    return chunks
