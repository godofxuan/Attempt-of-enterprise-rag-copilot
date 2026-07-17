from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.documents import (
    ChunkRecord,
    DocumentParseError,
    DocumentRecord,
    DocumentVersion,
    ParseResult,
    ParseWarning,
    ParsedSection,
    SourceLocator,
)


def locator() -> SourceLocator:
    return SourceLocator(kind="line", start=1, end=2, label="lines 1-2")


def section() -> ParsedSection:
    return ParsedSection(
        heading="Rules",
        level=2,
        path=["Policy", "Rules"],
        text="Employees must file requests within two days.",
        locator=locator(),
    )


def version() -> DocumentVersion:
    return DocumentVersion(
        version_id="policy@2026",
        version="2026.1",
        status="active",
        effective_from=date(2026, 1, 1),
        authority_level=100,
    )


def document_record(**updates) -> DocumentRecord:
    values = {
        "doc_id": "auth_policy_2026",
        "title": "Policy",
        "source_type": "policy",
        "source_path": "documents/auth_policy_2026.md",
        "format": "md",
        "department": "hr",
        "filed_department": "hr",
        "project_id": None,
        "policy_id": "policy",
        "region": "cn",
        "tenant_id": "tenant-cn",
        "acl_groups": ["all_employees"],
        "document_version": version(),
        "authority_level": 100,
        "checksum": "a" * 64,
        "normalized_text_hash": "b" * 64,
        "ingested_at": datetime(2026, 7, 16, tzinfo=timezone.utc),
        "parser_name": "markdown",
        "parser_version": "1",
        "text": "Employees must file requests within two days.",
        "sections": [section()],
        "tables": [],
        "parse_warnings": [],
        "fact_ids": ["policy_2026_deadline"],
        "variant": "authoritative",
        "duplicate_of": None,
    }
    values.update(updates)
    return DocumentRecord(**values)


def test_parse_result_rejects_empty_text_without_warning() -> None:
    with pytest.raises(ValidationError, match="parsed content is empty"):
        ParseResult(
            text="",
            sections=[],
            headings=[],
            tables=[],
            metadata={},
            source_location="empty.txt",
            parse_warnings=[],
            parser_name="text",
            parser_version="1",
        )


def test_parse_result_allows_a_structured_empty_page_warning() -> None:
    result = ParseResult(
        text="",
        sections=[],
        headings=[],
        tables=[],
        metadata={},
        source_location="page-2.pdf",
        parse_warnings=[
            ParseWarning(
                code="empty_page",
                message="Page 2 has no extractable text.",
                severity="warning",
                locator=SourceLocator(kind="page", start=2, end=2),
            )
        ],
        parser_name="pdf",
        parser_version="1",
    )

    assert result.parse_warnings[0].code == "empty_page"


def test_document_record_requires_timezone_aware_ingested_at() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        document_record(ingested_at=datetime(2026, 7, 16))


def test_document_version_rejects_invalid_interval() -> None:
    with pytest.raises(ValidationError, match="effective_to must be later"):
        DocumentVersion(
            version_id="policy@2025",
            version="2025.1",
            status="retired",
            effective_from=date(2025, 1, 1),
            effective_to=date(2025, 1, 1),
            authority_level=100,
        )


def test_chunk_record_requires_parent_for_child_kind() -> None:
    with pytest.raises(ValidationError, match="child chunk requires parent_chunk_id"):
        ChunkRecord(
            chunk_id="chunk-1",
            doc_id="auth_policy_2026",
            parent_chunk_id=None,
            kind="child",
            indexable=True,
            text="Policy evidence",
            section_path=["Policy", "Rules"],
            locator=locator(),
            source_path="documents/auth_policy_2026.md",
            format="md",
            source_type="policy",
            policy_id="policy",
            department="hr",
            filed_department="hr",
            tenant_id="tenant-cn",
            region="cn",
            acl_groups=["all_employees"],
            version_id="policy@2026",
            version="2026.1",
            status="active",
            effective_from=date(2026, 1, 1),
            effective_to=None,
            supersedes_doc_id=None,
            authority_level=100,
            fact_ids=["fact-1"],
            variant="authoritative",
            checksum="c" * 64,
            text_hash="d" * 64,
        )


def test_document_parse_error_serializes_code_parser_and_path() -> None:
    error = DocumentParseError(
        code="malformed_jsonl",
        path=Path("broken.jsonl"),
        parser="jsonl",
        message="line 3 is invalid JSON",
    )

    assert error.to_dict() == {
        "code": "malformed_jsonl",
        "path": "broken.jsonl",
        "parser": "jsonl",
        "message": "line 3 is invalid JSON",
    }
