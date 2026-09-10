"""Use the pinned Markdown parser for table boundaries, not a pipe regex."""

from __future__ import annotations

from dataclasses import dataclass

from markdown_it import MarkdownIt
from markdown_it.rules_block.table import escapedSplit

from app.domain.documents import ParsedTable, SourceLocator


@dataclass(frozen=True)
class MarkdownTable:
    table: ParsedTable
    start: int
    end: int


def extract_markdown_tables(text: str) -> list[MarkdownTable]:
    tokens = MarkdownIt("commonmark").enable("table").parse(text)
    lines = text.splitlines()
    result: list[MarkdownTable] = []
    heading_path: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == "heading_open":
            level = int(token.tag[1:])
            heading_path = heading_path[: level - 1] + [tokens[index + 1].content]
        if token.type != "table_open":
            index += 1
            continue
        start, end = token.map
        rows: list[list[str]] = []
        row: list[str] = []
        index += 1
        while tokens[index].type != "table_close":
            item = tokens[index]
            if item.type == "tr_open":
                row = []
            elif item.type == "inline":
                row.append(
                    "".join(
                        "\n" if child.type in {"softbreak", "hardbreak"} else child.content
                        for child in (item.children or [])
                        if child.type in {"text", "code_inline", "softbreak", "hardbreak", "image"}
                    )
                )
            elif item.type == "tr_close":
                rows.append(row)
            index += 1
        # Markdown accepts ragged rows by dropping/padding cells; ingestion must not.
        for line in [lines[start], *lines[start + 2 : end]]:
            cells = escapedSplit(line.strip())
            if cells and cells[0] == "":
                cells.pop(0)
            if cells and cells[-1] == "":
                cells.pop()
            if len(cells) != len(rows[0]):
                raise ValueError("markdown_table_row_width_mismatch")
        if not all(cell.strip() for cell in rows[0]):
            raise ValueError("markdown_table_empty_header")
        if rows[1:]:
            result.append(
                MarkdownTable(
                    table=ParsedTable(
                        table_id=f"table-{len(result) + 1}",
                        headers=rows[0],
                        rows=rows[1:],
                        caption=" / ".join(heading_path) or None,
                        locator=SourceLocator(
                            kind="line",
                            start=start + 3,
                            end=end,
                            label=f"Markdown table lines {start + 1}-{end}",
                        ),
                    ),
                    start=start,
                    end=end,
                )
            )
        index += 1
    return result


def without_markdown_tables(text: str) -> str:
    spans = extract_markdown_tables(text)
    excluded = {line for span in spans for line in range(span.start, span.end)}
    return "\n".join(line for index, line in enumerate(text.splitlines()) if index not in excluded)
