from __future__ import annotations

import csv
import io
import json
import re
from collections import OrderedDict
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol

from app.domain.documents import (
    DocumentParseError,
    ParseResult,
    ParsedSection,
    ParsedTable,
    SourceLocator,
)


PARSER_VERSION = "1.0"
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s*(.*?)\s*$")


class DocumentParser(Protocol):
    name: str
    version: str
    suffixes: tuple[str, ...]

    def parse(self, path: Path) -> ParseResult: ...


def _parse_error(
    *,
    code: str,
    path: Path,
    parser: str,
    message: str,
) -> DocumentParseError:
    return DocumentParseError(
        code=code,
        path=path,
        parser=parser,
        message=message,
    )


def _read_utf8(path: Path, parser: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise _parse_error(
            code="decode_error",
            path=path,
            parser=parser,
            message=f"file is not valid UTF-8: {exc}",
        ) from exc


def _require_content(path: Path, parser: str, text: str, tables: list) -> None:
    if not text.strip() and not tables:
        raise _parse_error(
            code="empty_document",
            path=path,
            parser=parser,
            message="parser produced no text or tables",
        )


class ParserRegistry:
    def __init__(self) -> None:
        self._by_suffix: dict[str, DocumentParser] = {}

    def register(self, parser: DocumentParser) -> None:
        for suffix in parser.suffixes:
            normalized = suffix.lower()
            if not normalized.startswith("."):
                raise ValueError(f"parser suffix must start with '.': {suffix!r}")
            if normalized in self._by_suffix:
                raise ValueError(f"parser already registered for {normalized}")
            self._by_suffix[normalized] = parser

    def parse(self, path: Path) -> ParseResult:
        path = Path(path)
        parser = self._by_suffix.get(path.suffix.lower())
        if parser is None:
            raise _parse_error(
                code="unsupported_format",
                path=path,
                parser="registry",
                message=f"no parser registered for suffix {path.suffix.lower()!r}",
            )
        if not path.is_file():
            raise _parse_error(
                code="file_not_found",
                path=path,
                parser=parser.name,
                message="source path is not a file",
            )
        try:
            return parser.parse(path)
        except DocumentParseError:
            raise
        except Exception as exc:
            raise _parse_error(
                code="parser_failure",
                path=path,
                parser=parser.name,
                message=str(exc),
            ) from exc

    @property
    def supported_suffixes(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_suffix))


class MarkdownParser:
    name = "markdown"
    version = PARSER_VERSION
    suffixes = (".md", ".markdown")

    def parse(self, path: Path) -> ParseResult:
        raw = _read_utf8(path, self.name)
        lines = raw.splitlines()
        headings: list[str] = []
        sections: list[ParsedSection] = []
        path_stack: list[str] = []
        current_heading = "General"
        current_level = 0
        current_path = ["General"]
        body: list[tuple[int, str]] = []
        text_parts: list[str] = []

        def flush() -> None:
            nonlocal body
            meaningful = [(line_no, value) for line_no, value in body if value.strip()]
            if meaningful:
                sections.append(
                    ParsedSection(
                        heading=current_heading,
                        level=current_level,
                        path=current_path,
                        text="\n".join(value for _, value in meaningful),
                        locator=SourceLocator(
                            kind="line",
                            start=meaningful[0][0],
                            end=meaningful[-1][0],
                            label=f"lines {meaningful[0][0]}-{meaningful[-1][0]}",
                        ),
                    )
                )
            body = []

        for line_no, line in enumerate(lines, start=1):
            match = _MARKDOWN_HEADING.match(line)
            if match:
                flush()
                level = len(match.group(1))
                heading = match.group(2).strip() or "General"
                path_stack = path_stack[: level - 1]
                path_stack.append(heading)
                current_heading = heading
                current_level = level
                current_path = list(path_stack)
                headings.append(heading)
                text_parts.append(heading)
                continue
            body.append((line_no, line))
            if line.strip():
                text_parts.append(line.strip())
        flush()

        text = "\n".join(text_parts).strip()
        _require_content(path, self.name, text, [])
        if not sections:
            sections.append(
                ParsedSection(
                    heading="General",
                    level=0,
                    path=["General"],
                    text=text,
                    locator=SourceLocator(
                        kind="line",
                        start=1,
                        end=max(1, len(lines)),
                        label=f"lines 1-{max(1, len(lines))}",
                    ),
                )
            )
        return ParseResult(
            text=text,
            sections=sections,
            headings=headings,
            tables=[],
            metadata={},
            source_location=path.name,
            parse_warnings=[],
            parser_name=self.name,
            parser_version=self.version,
        )


class TextParser:
    name = "text"
    version = PARSER_VERSION
    suffixes = (".txt",)

    def parse(self, path: Path) -> ParseResult:
        raw = _read_utf8(path, self.name)
        text = raw.strip()
        _require_content(path, self.name, text, [])
        line_count = max(1, len(raw.splitlines()))
        return ParseResult(
            text=text,
            sections=[
                ParsedSection(
                    heading="General",
                    level=0,
                    path=["General"],
                    text=text,
                    locator=SourceLocator(
                        kind="line",
                        start=1,
                        end=line_count,
                        label=f"lines 1-{line_count}",
                    ),
                )
            ],
            headings=[],
            tables=[],
            metadata={},
            source_location=path.name,
            parse_warnings=[],
            parser_name=self.name,
            parser_version=self.version,
        )


class _StructuredHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: list[str] = []
        self.paragraphs: list[tuple[list[str], str, str]] = []
        self.tables: list[list[list[str]]] = []
        self._path_stack: list[str] = []
        self._capture: str | None = None
        self._capture_level = 0
        self._buffer: list[str] = []
        self._table_rows: list[list[str]] | None = None
        self._table_row: list[str] | None = None
        self._cell_buffer: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if len(tag) == 2 and tag.startswith("h") and tag[1].isdigit():
            self._capture = "heading"
            self._capture_level = int(tag[1])
            self._buffer = []
        elif tag in {"p", "li"}:
            self._capture = "paragraph"
            self._buffer = []
        elif tag == "table":
            self._table_rows = []
        elif tag == "tr" and self._table_rows is not None:
            self._table_row = []
        elif tag in {"th", "td"} and self._table_row is not None:
            self._cell_buffer = []

    def handle_data(self, data: str) -> None:
        if self._cell_buffer is not None:
            self._cell_buffer.append(data)
        elif self._capture is not None:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"th", "td"} and self._cell_buffer is not None:
            self._table_row.append(" ".join("".join(self._cell_buffer).split()))
            self._cell_buffer = None
        elif tag == "tr" and self._table_row is not None:
            if any(cell for cell in self._table_row):
                self._table_rows.append(self._table_row)
            self._table_row = None
        elif tag == "table" and self._table_rows is not None:
            if self._table_rows:
                self.tables.append(self._table_rows)
            self._table_rows = None
        elif self._capture == "heading" and tag == f"h{self._capture_level}":
            heading = " ".join("".join(self._buffer).split()) or "General"
            self._path_stack = self._path_stack[: self._capture_level - 1]
            self._path_stack.append(heading)
            self.headings.append(heading)
            self._capture = None
            self._buffer = []
        elif self._capture == "paragraph" and tag in {"p", "li"}:
            paragraph = " ".join("".join(self._buffer).split())
            if paragraph:
                path = list(self._path_stack) or ["General"]
                self.paragraphs.append((path, path[-1], paragraph))
            self._capture = None
            self._buffer = []


class HtmlDocumentParser:
    name = "html"
    version = PARSER_VERSION
    suffixes = (".html", ".htm")

    def parse(self, path: Path) -> ParseResult:
        raw = _read_utf8(path, self.name)
        parser = _StructuredHTMLParser()
        parser.feed(raw)
        parser.close()

        grouped: OrderedDict[tuple[str, ...], list[tuple[int, str]]] = OrderedDict()
        for paragraph_no, (section_path, _, text) in enumerate(
            parser.paragraphs, start=1
        ):
            grouped.setdefault(tuple(section_path), []).append((paragraph_no, text))
        sections = [
            ParsedSection(
                heading=section_path[-1],
                level=min(6, len(section_path)),
                path=list(section_path),
                text="\n".join(text for _, text in paragraphs),
                locator=SourceLocator(
                    kind="paragraph",
                    start=paragraphs[0][0],
                    end=paragraphs[-1][0],
                    label=f"paragraphs {paragraphs[0][0]}-{paragraphs[-1][0]}",
                ),
            )
            for section_path, paragraphs in grouped.items()
        ]
        tables: list[ParsedTable] = []
        for table_no, rows in enumerate(parser.tables, start=1):
            headers = rows[0]
            body = rows[1:]
            if not headers or any(not header for header in headers):
                raise _parse_error(
                    code="invalid_html_table",
                    path=path,
                    parser=self.name,
                    message=f"table {table_no} has an empty header",
                )
            if any(len(row) != len(headers) for row in body):
                raise _parse_error(
                    code="invalid_html_table",
                    path=path,
                    parser=self.name,
                    message=f"table {table_no} has inconsistent row widths",
                )
            tables.append(
                ParsedTable(
                    table_id=f"table-{table_no}",
                    headers=headers,
                    rows=body,
                    locator=SourceLocator(
                        kind="row",
                        start=1,
                        end=max(1, len(rows)),
                        label=f"HTML table {table_no}",
                    ),
                )
            )

        text_parts = [*parser.headings]
        text_parts.extend(text for _, _, text in parser.paragraphs)
        for table in tables:
            text_parts.append(" | ".join(table.headers))
            text_parts.extend(" | ".join(row) for row in table.rows)
        text = "\n".join(text_parts).strip()
        _require_content(path, self.name, text, tables)
        return ParseResult(
            text=text,
            sections=sections,
            headings=parser.headings,
            tables=tables,
            metadata={},
            source_location=path.name,
            parse_warnings=[],
            parser_name=self.name,
            parser_version=self.version,
        )


class CsvDocumentParser:
    name = "csv"
    version = PARSER_VERSION
    suffixes = (".csv",)

    def parse(self, path: Path) -> ParseResult:
        raw = _read_utf8(path, self.name)
        try:
            rows = list(csv.reader(io.StringIO(raw, newline=""), strict=True))
        except csv.Error as exc:
            raise _parse_error(
                code="malformed_csv",
                path=path,
                parser=self.name,
                message=str(exc),
            ) from exc
        if not rows:
            raise _parse_error(
                code="empty_document",
                path=path,
                parser=self.name,
                message="CSV has no header",
            )
        headers = [header.strip() for header in rows[0]]
        if any(not header for header in headers) or len(headers) != len(set(headers)):
            raise _parse_error(
                code="invalid_csv_header",
                path=path,
                parser=self.name,
                message="CSV headers must be non-empty and unique",
            )
        body = [[cell.strip() for cell in row] for row in rows[1:] if any(row)]
        if any(len(row) != len(headers) for row in body):
            raise _parse_error(
                code="malformed_csv",
                path=path,
                parser=self.name,
                message="CSV row width does not match header",
            )
        table = ParsedTable(
            table_id="table-1",
            headers=headers,
            rows=body,
            locator=SourceLocator(
                kind="row",
                start=2,
                end=max(2, len(rows)),
                label=f"rows 2-{max(2, len(rows))}",
            ),
        )
        text = "\n".join([" | ".join(headers), *(" | ".join(row) for row in body)])
        return ParseResult(
            text=text,
            sections=[],
            headings=[],
            tables=[table],
            metadata={},
            source_location=path.name,
            parse_warnings=[],
            parser_name=self.name,
            parser_version=self.version,
        )


class JsonlDocumentParser:
    name = "jsonl"
    version = PARSER_VERSION
    suffixes = (".jsonl",)

    def parse(self, path: Path) -> ParseResult:
        raw = _read_utf8(path, self.name)
        objects: list[dict] = []
        headers: list[str] = []
        for line_no, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise _parse_error(
                    code="malformed_jsonl",
                    path=path,
                    parser=self.name,
                    message=f"line {line_no} is invalid JSON: {exc.msg}",
                ) from exc
            if not isinstance(value, dict):
                raise _parse_error(
                    code="malformed_jsonl",
                    path=path,
                    parser=self.name,
                    message=f"line {line_no} must contain a JSON object",
                )
            objects.append(value)
            for key in value:
                if key not in headers:
                    headers.append(key)
        if not objects:
            raise _parse_error(
                code="empty_document",
                path=path,
                parser=self.name,
                message="JSONL has no object rows",
            )

        def cell(value) -> str:
            if value is None:
                return ""
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False, sort_keys=True)
            return str(value)

        rows = [[cell(obj.get(header)) for header in headers] for obj in objects]
        table = ParsedTable(
            table_id="table-1",
            headers=headers,
            rows=rows,
            locator=SourceLocator(
                kind="line",
                start=1,
                end=max(1, len(raw.splitlines())),
                label=f"lines 1-{max(1, len(raw.splitlines()))}",
            ),
        )
        text = "\n".join([" | ".join(headers), *(" | ".join(row) for row in rows)])
        return ParseResult(
            text=text,
            sections=[],
            headings=[],
            tables=[table],
            metadata={},
            source_location=path.name,
            parse_warnings=[],
            parser_name=self.name,
            parser_version=self.version,
        )


def build_default_registry() -> ParserRegistry:
    from app.ingestion.parsers_docx import DocxDocumentParser
    from app.ingestion.parsers_pdf import PdfDocumentParser

    registry = ParserRegistry()
    for parser in (
        MarkdownParser(),
        TextParser(),
        HtmlDocumentParser(),
        CsvDocumentParser(),
        JsonlDocumentParser(),
        PdfDocumentParser(),
        DocxDocumentParser(),
    ):
        registry.register(parser)
    return registry
