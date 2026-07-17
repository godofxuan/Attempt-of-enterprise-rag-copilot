import csv
import io
import json
from pathlib import Path

from app.corpus.generator import generate_document_specs, load_facts, load_profile
from app.corpus.renderers import extension_for, render_document


ROOT = Path(__file__).resolve().parents[2]
FACTS_PATH = ROOT / "data" / "v2" / "facts" / "company_facts_v1.json"
PROFILE_PATH = ROOT / "data" / "v2" / "config" / "demo.json"


def documents_by_format():
    documents = generate_document_specs(
        load_facts(FACTS_PATH),
        load_profile(PROFILE_PATH),
    )
    return {
        format_name: next(doc for doc in documents if doc.format == format_name)
        for format_name in ("md", "txt", "html", "csv", "jsonl")
    }


def test_renderers_are_deterministic_and_end_with_newline() -> None:
    for document in documents_by_format().values():
        first = render_document(document)
        second = render_document(document)

        assert first == second
        assert first.endswith("\n")
        assert document.title in first


def test_each_renderer_emits_its_declared_structure() -> None:
    documents = documents_by_format()

    assert render_document(documents["md"]).startswith("# ")
    assert "\n\n" in render_document(documents["txt"])
    assert render_document(documents["html"]).startswith("<!doctype html>")

    csv_rows = list(csv.DictReader(io.StringIO(render_document(documents["csv"]))))
    assert csv_rows
    assert set(csv_rows[0]) == {"title", "section", "fact_id", "text"}

    jsonl_rows = [
        json.loads(line)
        for line in render_document(documents["jsonl"]).splitlines()
    ]
    assert jsonl_rows
    assert set(jsonl_rows[0]) == {"fact_id", "section", "text", "title"}


def test_extension_mapping_is_explicit() -> None:
    assert extension_for("md") == ".md"
    assert extension_for("txt") == ".txt"
    assert extension_for("html") == ".html"
    assert extension_for("csv") == ".csv"
    assert extension_for("jsonl") == ".jsonl"
