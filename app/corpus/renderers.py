import csv
import io
import json
from html import escape

from app.corpus.schemas import DocumentFormat, DocumentSpec


_EXTENSIONS: dict[DocumentFormat, str] = {
    "md": ".md",
    "txt": ".txt",
    "html": ".html",
    "csv": ".csv",
    "jsonl": ".jsonl",
}


def extension_for(document_format: DocumentFormat) -> str:
    return _EXTENSIONS[document_format]


def _rows(document: DocumentSpec):
    for section in document.sections:
        for index, line in enumerate(section.lines):
            fact_id = section.fact_ids[index] if index < len(section.fact_ids) else ""
            yield {
                "title": document.title,
                "section": section.heading,
                "fact_id": fact_id,
                "text": line,
            }


def _render_markdown(document: DocumentSpec) -> str:
    blocks = [f"# {document.title}"]
    for section in document.sections:
        blocks.append(f"## {section.heading}\n" + "\n".join(section.lines))
    return "\n\n".join(blocks) + "\n"


def _render_text(document: DocumentSpec) -> str:
    blocks = [document.title]
    for section in document.sections:
        blocks.append(f"{section.heading}\n" + "\n".join(section.lines))
    return "\n\n".join(blocks) + "\n"


def _render_html(document: DocumentSpec) -> str:
    parts = [
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<body>",
        "<article>",
        f"<h1>{escape(document.title)}</h1>",
    ]
    for section in document.sections:
        parts.append(f"<section><h2>{escape(section.heading)}</h2>")
        parts.extend(f"<p>{escape(line)}</p>" for line in section.lines)
        parts.append("</section>")
    parts.extend(["</article>", "</body>", "</html>"])
    return "\n".join(parts) + "\n"


def _render_csv(document: DocumentSpec) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=["title", "section", "fact_id", "text"],
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(_rows(document))
    return buffer.getvalue()


def _render_jsonl(document: DocumentSpec) -> str:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for row in _rows(document)
    )


def render_document(document: DocumentSpec) -> str:
    renderers = {
        "md": _render_markdown,
        "txt": _render_text,
        "html": _render_html,
        "csv": _render_csv,
        "jsonl": _render_jsonl,
    }
    return renderers[document.format](document)
