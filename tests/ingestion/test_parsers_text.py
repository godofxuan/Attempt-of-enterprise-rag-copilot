from pathlib import Path

import pytest

from app.domain.documents import DocumentParseError
from app.ingestion.parsers import build_default_registry


ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "data" / "v2" / "fixtures" / "smoke" / "documents"


@pytest.fixture
def registry():
    return build_default_registry()


def test_markdown_parser_preserves_heading_path_and_line_locator(registry) -> None:
    result = registry.parse(SMOKE / "auth_hr_remote_2025.md")

    assert result.parser_name == "markdown"
    assert result.headings == [
        "远程办公制度 2025.1（已废止）",
        "版本信息",
        "制度要求",
    ]
    assert result.sections[0].path == [
        "远程办公制度 2025.1（已废止）",
        "版本信息",
    ]
    assert result.sections[0].locator.kind == "line"
    assert result.sections[0].locator.start == 4
    assert "版本号：2025.1" in result.text


def test_text_parser_returns_one_general_section(registry) -> None:
    result = registry.parse(SMOKE / "support_0002.txt")

    assert result.parser_name == "text"
    assert result.headings == []
    assert len(result.sections) == 1
    assert result.sections[0].heading == "General"
    assert result.sections[0].locator.start == 1
    assert "50000 元" in result.text


def test_html_parser_extracts_headings_paragraphs_and_table(registry, tmp_path: Path) -> None:
    path = tmp_path / "policy.html"
    path.write_text(
        "<!doctype html><html><body><h1>Policy</h1>"
        "<h2>Rules</h2><p>Approval is required.</p>"
        "<table><tr><th>Level</th><th>Limit</th></tr>"
        "<tr><td>P1</td><td>15 minutes</td></tr></table></body></html>",
        encoding="utf-8",
    )

    result = registry.parse(path)

    assert result.headings == ["Policy", "Rules"]
    assert result.sections[-1].path == ["Policy", "Rules"]
    assert "Approval is required." in result.text
    assert result.tables[0].headers == ["Level", "Limit"]
    assert result.tables[0].rows == [["P1", "15 minutes"]]


def test_csv_parser_preserves_headers_rows_and_row_locator(registry) -> None:
    result = registry.parse(SMOKE / "support_0004.csv")

    table = result.tables[0]
    assert table.headers == ["title", "section", "fact_id", "text"]
    assert len(table.rows) == 2
    assert table.locator.kind == "row"
    assert table.locator.start == 2
    assert "30 分钟" in result.text


def test_jsonl_parser_preserves_union_headers_and_line_locator(registry) -> None:
    result = registry.parse(SMOKE / "support_0005.jsonl")

    table = result.tables[0]
    assert set(table.headers) == {"fact_id", "section", "text", "title"}
    assert len(table.rows) == 2
    assert table.locator.kind == "line"
    assert table.locator.start == 1
    assert "200000 元" in result.text


def test_unknown_extension_returns_structured_error(registry, tmp_path: Path) -> None:
    path = tmp_path / "policy.xml"
    path.write_text("<policy />", encoding="utf-8")

    with pytest.raises(DocumentParseError) as captured:
        registry.parse(path)

    assert captured.value.to_dict()["code"] == "unsupported_format"
    assert captured.value.to_dict()["path"].endswith("policy.xml")


def test_invalid_utf8_returns_decode_error(registry, tmp_path: Path) -> None:
    path = tmp_path / "broken.txt"
    path.write_bytes(b"\xff\xfe\x00")

    with pytest.raises(DocumentParseError) as captured:
        registry.parse(path)

    assert captured.value.code == "decode_error"
    assert captured.value.parser == "text"


def test_malformed_jsonl_reports_exact_line(registry, tmp_path: Path) -> None:
    path = tmp_path / "broken.jsonl"
    path.write_text('{"text":"ok"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(DocumentParseError) as captured:
        registry.parse(path)

    assert captured.value.code == "malformed_jsonl"
    assert "line 2" in captured.value.message


def test_csv_rejects_empty_header(registry, tmp_path: Path) -> None:
    path = tmp_path / "broken.csv"
    path.write_text("name,,value\nitem,x,1\n", encoding="utf-8")

    with pytest.raises(DocumentParseError) as captured:
        registry.parse(path)

    assert captured.value.code == "invalid_csv_header"


def test_empty_text_document_is_rejected(registry, tmp_path: Path) -> None:
    path = tmp_path / "empty.txt"
    path.write_text(" \n\n", encoding="utf-8")

    with pytest.raises(DocumentParseError) as captured:
        registry.parse(path)

    assert captured.value.code == "empty_document"


def test_text_parser_accepts_immutable_bytes_without_a_file_path(registry) -> None:
    source = SMOKE / "support_0002.txt"
    result = registry.parse_bytes(source.read_bytes(), suffix=".txt")

    assert result.parser_name == "text"
    assert result.source_location == "[redacted].txt"
    assert result.text == registry.parse(source).text
