import pytest

from app.domain.documents import ParseWarning
from app.ingestion.chunking import ChunkerConfig, chunk_document
from tests.ingestion.test_document_quality_v1 import parsed_record


def test_incomplete_pdf_blocks_structural_publication(document_factory):
    record = document_factory(
        parse_warnings=[ParseWarning(code="empty_page", message="No extractable text")]
    )
    with pytest.raises(ValueError, match="document_quality_review_required"):
        chunk_document(record, ChunkerConfig(mode="structure"))


def test_quality_report_is_bound_to_source_and_chunk_layout(document_factory):
    from app.ingestion.document_quality import assess_document_quality

    _, record = parsed_record(document_factory, b"City,CNY/night\nShanghai,550\n", "travel.csv")
    config = ChunkerConfig(mode="structure")
    chunks = chunk_document(record, config)
    report = assess_document_quality(record, chunks, config)
    assert report.decision == "ACCEPT"
    assert report.source_sha256 == record.checksum
    assert report.table_rows == report.covered_table_rows == 1
    assert report.chunk_ids == [chunk.chunk_id for chunk in chunks]


def test_missing_table_rows_are_detected_without_gold(document_factory):
    from app.ingestion.document_quality import assess_document_quality

    _, record = parsed_record(document_factory, b"City,CNY/night\nShanghai,550\n", "travel.csv")
    report = assess_document_quality(record, [], ChunkerConfig(mode="structure"))
    assert report.decision == "REJECT"
    assert "missing_table_rows" in report.reason_codes


def test_clean_no_table_document_remains_usable(document_factory):
    chunks = chunk_document(
        document_factory(text="Ordinary policy."), ChunkerConfig(mode="structure")
    )
    assert chunks[0].text == "Ordinary policy."


def test_numeric_suffix_is_not_row_coverage(document_factory):
    from app.ingestion.document_quality import assess_document_quality

    _, record = parsed_record(document_factory, b"City,CNY/night\nShanghai,550\n", "travel.csv")
    config = ChunkerConfig(mode="structure")
    chunks = chunk_document(record, config)
    changed = [
        chunk.model_copy(update={"text": chunk.text.replace("550", "5500")}) for chunk in chunks
    ]
    assert assess_document_quality(record, changed, config).decision == "REJECT"


@pytest.mark.parametrize(
    "field,value",
    [
        ("policy_id", "other"),
        ("region", "other"),
        ("authority_level", 1),
        ("source_path", "other.csv"),
    ],
)
def test_quality_binding_rejects_changed_governance(document_factory, field, value):
    from app.ingestion.document_quality import assess_document_quality

    _, record = parsed_record(document_factory, b"City,CNY/night\nShanghai,550\n", "travel.csv")
    config = ChunkerConfig(mode="structure")
    chunks = chunk_document(record, config)
    changed = [chunk.model_copy(update={field: value}) for chunk in chunks]
    assert (
        "source_binding_mismatch" in assess_document_quality(record, changed, config).reason_codes
    )


def test_pdf_table_row_offsets_never_become_fictitious_pages(document_factory):
    from app.domain.documents import SourceLocator

    _, record = parsed_record(
        document_factory, b"City,CNY/night\nShanghai,550\nBeijing,600\n", "travel.csv"
    )
    record.tables[0].locator = SourceLocator(kind="page", start=7, end=7)
    chunks = chunk_document(record, ChunkerConfig(mode="structure", table_rows_per_chunk=1))
    assert all(
        chunk.locator.start == 7 and chunk.locator.end == 7
        for chunk in chunks
        if chunk.kind == "table"
    )


def test_multiline_cells_fail_closed_in_finite_table_representation(document_factory):
    _, record = parsed_record(document_factory, b'City,Amount\n"Shang\nhai",550\n', "travel.csv")
    with pytest.raises(ValueError, match="multiline_table_cell"):
        chunk_document(record, ChunkerConfig(mode="structure"))
