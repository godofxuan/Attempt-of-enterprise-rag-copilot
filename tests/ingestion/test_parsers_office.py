from pathlib import Path

import pytest

from app.domain.documents import DocumentParseError
from app.ingestion.parsers import build_default_registry


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "ingestion"


@pytest.fixture
def registry():
    return build_default_registry()


def test_pdf_parser_preserves_page_locator_and_blank_page_warning(registry) -> None:
    result = registry.parse(FIXTURES / "sample_policy.pdf")

    assert result.parser_name == "pdf"
    assert "Incident response requires a 15 minute acknowledgement." in result.text
    assert result.sections[0].locator.kind == "page"
    assert result.sections[0].locator.start == 1
    assert any(warning.code == "empty_page" for warning in result.parse_warnings)


def test_all_empty_pdf_is_rejected(registry) -> None:
    with pytest.raises(DocumentParseError) as captured:
        registry.parse(FIXTURES / "empty_page.pdf")

    assert captured.value.code == "empty_document"
    assert "no extractable text" in captured.value.message


def test_docx_parser_preserves_document_order_headings_and_tables(registry) -> None:
    result = registry.parse(FIXTURES / "sample_policy.docx")

    assert result.parser_name == "docx"
    assert result.headings == ["Travel Policy", "Approval Rules"]
    assert [section.heading for section in result.sections] == [
        "Travel Policy",
        "Approval Rules",
    ]
    assert result.sections[1].locator.kind == "paragraph"
    assert "Manager approval is required." in result.sections[1].text
    assert result.tables[0].headers == ["Level", "Limit"]
    assert result.tables[0].rows == [["Manager", "5000"]]


@pytest.mark.parametrize(
    ("suffix", "payload", "expected_parser"),
    [
        (".pdf", b"not a pdf", "pdf"),
        (".docx", b"not a zip package", "docx"),
    ],
)
def test_malformed_office_file_returns_structured_error(
    registry,
    tmp_path: Path,
    suffix: str,
    payload: bytes,
    expected_parser: str,
) -> None:
    path = tmp_path / f"broken{suffix}"
    path.write_bytes(payload)

    with pytest.raises(DocumentParseError) as captured:
        registry.parse(path)

    assert captured.value.code == "parser_failure"
    assert captured.value.parser == expected_parser


@pytest.mark.parametrize(
    ("fixture_name", "suffix", "expected_parser"),
    [
        ("sample_policy.pdf", ".pdf", "pdf"),
        ("sample_policy.docx", ".docx", "docx"),
    ],
)
def test_office_parsers_accept_immutable_bytes(
    registry,
    fixture_name: str,
    suffix: str,
    expected_parser: str,
) -> None:
    content = (FIXTURES / fixture_name).read_bytes()
    result = registry.parse_bytes(content, suffix=suffix)

    assert result.parser_name == expected_parser
    assert result.source_location == f"[redacted]{suffix}"
