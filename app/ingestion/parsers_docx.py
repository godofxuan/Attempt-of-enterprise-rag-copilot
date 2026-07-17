from __future__ import annotations

import re
from pathlib import Path

import docx
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.domain.documents import (
    DocumentParseError,
    ParseResult,
    ParsedSection,
    ParsedTable,
    SourceLocator,
)


_HEADING_STYLE = re.compile(r"^Heading\s+([1-6])$", re.IGNORECASE)


class DocxDocumentParser:
    name = "docx"
    version = docx.__version__
    suffixes = (".docx",)

    def parse(self, path: Path) -> ParseResult:
        document = Document(path)
        headings: list[str] = []
        sections: list[ParsedSection] = []
        tables: list[ParsedTable] = []
        path_stack: list[str] = []
        current_heading = "General"
        current_level = 0
        current_path = ["General"]
        body: list[tuple[int, str]] = []
        text_parts: list[str] = []
        paragraph_number = 0
        table_number = 0

        def flush() -> None:
            nonlocal body
            if body:
                sections.append(
                    ParsedSection(
                        heading=current_heading,
                        level=current_level,
                        path=current_path,
                        text="\n".join(text for _, text in body),
                        locator=SourceLocator(
                            kind="paragraph",
                            start=body[0][0],
                            end=body[-1][0],
                            label=f"paragraphs {body[0][0]}-{body[-1][0]}",
                        ),
                    )
                )
            body = []

        for block in document.iter_inner_content():
            if isinstance(block, Paragraph):
                paragraph_number += 1
                text = block.text.strip()
                if not text:
                    continue
                style_name = block.style.name if block.style is not None else ""
                match = _HEADING_STYLE.match(style_name)
                if match:
                    flush()
                    level = int(match.group(1))
                    path_stack = path_stack[: level - 1]
                    path_stack.append(text)
                    current_heading = text
                    current_level = level
                    current_path = list(path_stack)
                    headings.append(text)
                    text_parts.append(text)
                    continue
                body.append((paragraph_number, text))
                text_parts.append(text)
                continue

            if isinstance(block, Table):
                table_number += 1
                rows = [
                    [cell.text.strip() for cell in row.cells]
                    for row in block.rows
                ]
                if not rows or not rows[0] or any(not header for header in rows[0]):
                    raise DocumentParseError(
                        code="invalid_docx_table",
                        path=path,
                        parser=self.name,
                        message=f"table {table_number} has an empty header",
                    )
                headers = rows[0]
                body_rows = rows[1:]
                if any(len(row) != len(headers) for row in body_rows):
                    raise DocumentParseError(
                        code="invalid_docx_table",
                        path=path,
                        parser=self.name,
                        message=f"table {table_number} has inconsistent row widths",
                    )
                tables.append(
                    ParsedTable(
                        table_id=f"table-{table_number}",
                        headers=headers,
                        rows=body_rows,
                        locator=SourceLocator(
                            kind="row",
                            start=1,
                            end=max(1, len(rows)),
                            label=f"DOCX table {table_number}",
                        ),
                    )
                )
                text_parts.append(" | ".join(headers))
                text_parts.extend(" | ".join(row) for row in body_rows)
        flush()

        full_text = "\n".join(text_parts).strip()
        if not full_text and not tables:
            raise DocumentParseError(
                code="empty_document",
                path=path,
                parser=self.name,
                message="DOCX has no extractable paragraphs or tables",
            )
        return ParseResult(
            text=full_text,
            sections=sections,
            headings=headings,
            tables=tables,
            metadata={
                "core_title": document.core_properties.title or "",
                "block_order": "preserved",
            },
            source_location=path.name,
            parse_warnings=[],
            parser_name=self.name,
            parser_version=self.version,
        )
