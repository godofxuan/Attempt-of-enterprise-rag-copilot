from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DocumentStatus = Literal["active", "retired"]
ChunkKind = Literal["fixed", "section", "parent", "child", "table"]
LocatorKind = Literal[
    "document",
    "character",
    "line",
    "page",
    "paragraph",
    "row",
    "cell",
]
WarningSeverity = Literal["info", "warning", "error"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceLocator(StrictModel):
    kind: LocatorKind
    start: int = Field(ge=1)
    end: int | None = Field(default=None, ge=1)
    label: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> SourceLocator:
        if self.end is not None and self.end < self.start:
            raise ValueError("locator end must not be earlier than start")
        return self


class ParseWarning(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: WarningSeverity = "warning"
    locator: SourceLocator | None = None


class ParsedSection(StrictModel):
    heading: str = Field(min_length=1)
    level: int = Field(ge=0, le=6)
    path: list[str] = Field(min_length=1)
    text: str
    locator: SourceLocator


class ParsedTable(StrictModel):
    table_id: str = Field(min_length=1)
    headers: list[str] = Field(min_length=1)
    rows: list[list[str]] = Field(default_factory=list)
    locator: SourceLocator
    caption: str | None = None

    @model_validator(mode="after")
    def validate_row_widths(self) -> ParsedTable:
        expected = len(self.headers)
        if any(len(row) != expected for row in self.rows):
            raise ValueError("table rows must match header width")
        return self


class ParseResult(StrictModel):
    text: str
    sections: list[ParsedSection] = Field(default_factory=list)
    headings: list[str] = Field(default_factory=list)
    tables: list[ParsedTable] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    source_location: str = Field(min_length=1)
    parse_warnings: list[ParseWarning] = Field(default_factory=list)
    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_content(self) -> ParseResult:
        has_content = bool(self.text.strip()) or bool(self.tables)
        if not has_content and not self.parse_warnings:
            raise ValueError("parsed content is empty")
        return self


class DocumentVersion(StrictModel):
    version_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: DocumentStatus
    effective_from: date
    effective_to: date | None = None
    supersedes_version_id: str | None = None
    supersedes_doc_id: str | None = None
    authority_level: int = Field(ge=1, le=100)

    @model_validator(mode="after")
    def validate_interval(self) -> DocumentVersion:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be later than effective_from")
        if self.status == "active" and self.effective_to is not None:
            raise ValueError("active version must not define effective_to")
        if self.status == "retired" and self.effective_to is None:
            raise ValueError("retired version must define effective_to")
        return self


class DocumentRecord(StrictModel):
    doc_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    format: str = Field(min_length=1)
    department: str = Field(min_length=1)
    filed_department: str = Field(min_length=1)
    project_id: str | None = None
    policy_id: str | None = None
    region: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    acl_groups: list[str] = Field(min_length=1)
    document_version: DocumentVersion
    authority_level: int = Field(ge=1, le=100)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    ingested_at: datetime
    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    text: str
    sections: list[ParsedSection] = Field(default_factory=list)
    tables: list[ParsedTable] = Field(default_factory=list)
    parse_warnings: list[ParseWarning] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)
    variant: str = Field(min_length=1)
    duplicate_of: str | None = None

    @model_validator(mode="after")
    def validate_record(self) -> DocumentRecord:
        if self.ingested_at.tzinfo is None or self.ingested_at.utcoffset() is None:
            raise ValueError("ingested_at must be timezone-aware")
        if not self.text.strip() and not self.tables:
            raise ValueError("document content is empty")
        if len(self.acl_groups) != len(set(self.acl_groups)):
            raise ValueError("acl_groups must be unique")
        if len(self.fact_ids) != len(set(self.fact_ids)):
            raise ValueError("fact_ids must be unique")
        if self.authority_level != self.document_version.authority_level:
            raise ValueError("document and version authority levels must match")
        return self


class ChunkRecord(StrictModel):
    chunk_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    parent_chunk_id: str | None = None
    kind: ChunkKind
    indexable: bool
    text: str = Field(min_length=1)
    section_path: list[str] = Field(min_length=1)
    locator: SourceLocator
    source_path: str = Field(min_length=1)
    format: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    policy_id: str | None = None
    department: str = Field(min_length=1)
    filed_department: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    region: str = Field(min_length=1)
    acl_groups: list[str] = Field(min_length=1)
    version_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: DocumentStatus
    effective_from: date
    effective_to: date | None = None
    supersedes_doc_id: str | None = None
    authority_level: int = Field(ge=1, le=100)
    fact_ids: list[str] = Field(default_factory=list)
    variant: str = Field(min_length=1)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_relationship(self) -> ChunkRecord:
        if self.kind == "child" and self.parent_chunk_id is None:
            raise ValueError("child chunk requires parent_chunk_id")
        if self.kind == "parent" and self.indexable:
            raise ValueError("parent chunks must not be indexable")
        if len(self.acl_groups) != len(set(self.acl_groups)):
            raise ValueError("acl_groups must be unique")
        if len(self.fact_ids) != len(set(self.fact_ids)):
            raise ValueError("fact_ids must be unique")
        return self


class DocumentParseError(Exception):
    def __init__(
        self,
        *,
        code: str,
        path: Path,
        parser: str,
        message: str,
    ) -> None:
        self.code = code
        self.path = Path(path)
        self.parser = parser
        self.message = message
        super().__init__(f"{code}: {message} ({self.path})")

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "path": str(self.path),
            "parser": self.parser,
            "message": self.message,
        }
