from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.documents import (
    DocumentRecord,
    DocumentVersion,
    ParsedSection,
    ParsedTable,
    SourceLocator,
)
from app.ingestion.chunking import ChunkerConfig, chunk_document


def document_record(*, doc_id: str = "policy-1", suffix: str = "") -> DocumentRecord:
    sections = [
        ParsedSection(
            heading="Alpha",
            level=2,
            path=["Policy", "Alpha"],
            text="ABCDEFGHIJ" + suffix,
            locator=SourceLocator(kind="line", start=3, end=4),
        ),
        ParsedSection(
            heading="Beta",
            level=2,
            path=["Policy", "Beta"],
            text="KLMNOPQRST",
            locator=SourceLocator(kind="line", start=7, end=8),
        ),
    ]
    return DocumentRecord(
        doc_id=doc_id,
        title="Policy",
        source_type="policy",
        source_path=f"documents/{doc_id}.md",
        format="md",
        department="hr",
        filed_department="hr",
        project_id=None,
        policy_id="policy",
        region="cn",
        tenant_id="tenant-cn",
        acl_groups=["all_employees"],
        document_version=DocumentVersion(
            version_id="policy@2026",
            version="2026.1",
            status="active",
            effective_from=date(2026, 1, 1),
            authority_level=100,
        ),
        authority_level=100,
        checksum="a" * 64,
        normalized_text_hash="b" * 64,
        ingested_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
        parser_name="markdown",
        parser_version="1",
        text="ABCDEFGHIJKLMNOP" + suffix,
        sections=sections,
        tables=[
            ParsedTable(
                table_id="limits",
                headers=["Level", "Limit"],
                rows=[["L1", "100"], ["L2", "200"], ["L3", "300"]],
                locator=SourceLocator(kind="row", start=2, end=4),
            )
        ],
        parse_warnings=[],
        fact_ids=["fact-1"],
        variant="authoritative",
        duplicate_of=None,
    )


def test_fixed_mode_reproduces_configured_windows_and_overlap() -> None:
    chunks = chunk_document(
        document_record(),
        ChunkerConfig(mode="fixed", chunk_size=8, overlap=2),
    )

    assert [chunk.text for chunk in chunks] == [
        "ABCDEFGH",
        "GHIJKLMN",
        "MNOP",
    ]
    assert all(chunk.kind == "fixed" and chunk.indexable for chunk in chunks)
    assert chunks[0].locator.kind == "character"


def test_heading_mode_never_crosses_section_boundary() -> None:
    chunks = chunk_document(
        document_record(),
        ChunkerConfig(mode="heading", chunk_size=6, overlap=2),
    )

    assert [chunk.text for chunk in chunks] == [
        "ABCDEF",
        "EFGHIJ",
        "KLMNOP",
        "OPQRST",
    ]
    assert [chunk.section_path for chunk in chunks] == [
        ["Policy", "Alpha"],
        ["Policy", "Alpha"],
        ["Policy", "Beta"],
        ["Policy", "Beta"],
    ]
    assert not any("JK" in chunk.text for chunk in chunks)


def test_parent_child_creates_non_indexable_parents_and_linked_children() -> None:
    chunks = chunk_document(
        document_record(),
        ChunkerConfig(
            mode="parent_child",
            parent_size=10,
            child_size=4,
            overlap=1,
            table_rows_per_chunk=2,
        ),
    )

    parents = [chunk for chunk in chunks if chunk.kind == "parent"]
    children = [chunk for chunk in chunks if chunk.kind == "child"]
    parent_ids = {chunk.chunk_id for chunk in parents}
    assert len(parents) == 2
    assert len(children) == 6
    assert all(not parent.indexable for parent in parents)
    assert all(child.indexable for child in children)
    assert all(child.parent_chunk_id in parent_ids for child in children)


def test_parent_child_table_chunks_repeat_headers_and_keep_row_range() -> None:
    chunks = chunk_document(
        document_record(),
        ChunkerConfig(
            mode="parent_child",
            parent_size=10,
            child_size=4,
            overlap=1,
            table_rows_per_chunk=2,
        ),
    )

    table_chunks = [chunk for chunk in chunks if chunk.kind == "table"]
    assert [chunk.text for chunk in table_chunks] == [
        "Level | Limit\nL1 | 100\nL2 | 200",
        "Level | Limit\nL3 | 300",
    ]
    assert [(chunk.locator.start, chunk.locator.end) for chunk in table_chunks] == [
        (2, 3),
        (4, 4),
    ]


def test_chunk_ids_are_stable_and_change_with_affected_text() -> None:
    config = ChunkerConfig(mode="heading", chunk_size=6, overlap=2)
    first = chunk_document(document_record(), config)
    second = chunk_document(document_record(), config)
    changed = chunk_document(document_record(suffix="X"), config)

    assert [chunk.chunk_id for chunk in first] == [
        chunk.chunk_id for chunk in second
    ]
    assert [chunk.chunk_id for chunk in first] != [
        chunk.chunk_id for chunk in changed
    ]


def test_chunk_ids_are_unique_across_documents() -> None:
    config = ChunkerConfig(mode="heading", chunk_size=6, overlap=2)
    chunks = [
        *chunk_document(document_record(doc_id="policy-1"), config),
        *chunk_document(document_record(doc_id="policy-2"), config),
    ]

    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)


def test_chunks_preserve_document_governance_metadata() -> None:
    chunk = chunk_document(
        document_record(),
        ChunkerConfig(mode="heading", chunk_size=20, overlap=2),
    )[0]

    assert chunk.source_type == "policy"
    assert chunk.policy_id == "policy"
    assert chunk.department == "hr"
    assert chunk.filed_department == "hr"
    assert chunk.fact_ids == ["fact-1"]
    assert chunk.variant == "authoritative"
    assert chunk.version_id == "policy@2026"
    assert chunk.effective_from == date(2026, 1, 1)


@pytest.mark.parametrize(
    "values",
    [
        {"mode": "fixed", "chunk_size": 8, "overlap": 8},
        {
            "mode": "parent_child",
            "parent_size": 10,
            "child_size": 4,
            "overlap": 4,
        },
        {
            "mode": "parent_child",
            "parent_size": 4,
            "child_size": 8,
            "overlap": 1,
        },
    ],
)
def test_invalid_chunker_config_is_rejected(values) -> None:
    with pytest.raises(ValidationError):
        ChunkerConfig(**values)
