import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.corpus.artifacts import load_smoke_manifest
from app.corpus.schemas import SmokeFixtureManifest
from app.domain.documents import (
    DocumentParseError,
    ParseResult,
    ParseWarning,
    SourceLocator,
)
from app.ingestion.normalize import ingest_corpus
from app.ingestion.parsers import ParserRegistry, build_default_registry


ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "data" / "v2" / "fixtures" / "smoke"
FIXED_TIME = datetime(2026, 7, 16, 8, 30, tzinfo=timezone.utc)


def copy_smoke(tmp_path: Path) -> Path:
    target = tmp_path / "smoke"
    shutil.copytree(SMOKE, target)
    return target


def write_manifest(root: Path, manifest: SmokeFixtureManifest) -> None:
    payload = manifest.model_dump(mode="json")
    (root / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_ingest_smoke_manifest_preserves_governance_and_parser_metadata() -> None:
    records = ingest_corpus(
        SMOKE,
        registry=build_default_registry(),
        ingested_at=FIXED_TIME,
    )

    assert len(records) == 5
    by_id = {record.doc_id: record for record in records}
    markdown = by_id["auth_hr_remote_2025"]
    assert markdown.title == "远程办公制度 2025.1（已废止）"
    assert markdown.source_path == "documents/auth_hr_remote_2025.md"
    assert markdown.department == "hr"
    assert markdown.filed_department == "hr"
    assert markdown.tenant_id == "starbridge-cn"
    assert markdown.acl_groups == ["all_employees"]
    assert markdown.document_version.status == "retired"
    assert markdown.authority_level == 100
    assert markdown.parser_name == "markdown"
    assert markdown.ingested_at == FIXED_TIME
    assert markdown.fact_ids == [
        "hr_remote_2025_days",
        "hr_remote_2025_notice",
    ]

    support = by_id["support_0002"]
    assert support.document_version.supersedes_version_id == "procurement_vendor@2025"
    assert support.document_version.supersedes_doc_id is None
    assert support.duplicate_of is None

    csv_record = by_id["support_0004"]
    assert csv_record.title == "生产发布制度 2026.1 服务工单"
    assert csv_record.tables[0].headers == ["title", "section", "fact_id", "text"]


def test_ingest_rejects_manifest_checksum_mismatch(tmp_path: Path) -> None:
    corpus = copy_smoke(tmp_path)
    manifest = load_smoke_manifest(corpus / "manifest.json")
    manifest.documents[0].sha256 = "0" * 64
    write_manifest(corpus, manifest)

    with pytest.raises(DocumentParseError) as captured:
        ingest_corpus(corpus, registry=build_default_registry())

    assert captured.value.code == "checksum_mismatch"


def test_ingest_rejects_missing_manifest_document(tmp_path: Path) -> None:
    corpus = copy_smoke(tmp_path)
    manifest = load_smoke_manifest(corpus / "manifest.json")
    (corpus / manifest.documents[0].path).unlink()

    with pytest.raises(DocumentParseError) as captured:
        ingest_corpus(corpus, registry=build_default_registry())

    assert captured.value.code == "file_not_found"


def test_ingest_rejects_manifest_path_traversal(tmp_path: Path) -> None:
    corpus = copy_smoke(tmp_path)
    manifest = load_smoke_manifest(corpus / "manifest.json")
    manifest.documents[0].path = "../outside.md"
    write_manifest(corpus, manifest)

    with pytest.raises(DocumentParseError) as captured:
        ingest_corpus(corpus, registry=build_default_registry())

    assert captured.value.code == "unsafe_source_path"


class EmptyWarningParser:
    name = "empty-test"
    version = "1"
    suffixes = (".txt",)

    def parse(self, path: Path) -> ParseResult:
        return ParseResult(
            text="",
            sections=[],
            headings=[],
            tables=[],
            metadata={},
            source_location=path.name,
            parse_warnings=[
                ParseWarning(
                    code="empty_page",
                    message="No extractable content.",
                    locator=SourceLocator(kind="document", start=1, end=1),
                )
            ],
            parser_name=self.name,
            parser_version=self.version,
        )


def test_ingest_rejects_parser_result_with_no_indexable_content(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    documents = corpus / "documents"
    documents.mkdir(parents=True)
    source = documents / "empty.txt"
    source.write_text("placeholder", encoding="utf-8")
    base = load_smoke_manifest(SMOKE / "manifest.json")
    entry = base.documents[1].model_copy(
        update={
            "doc_id": "empty_doc",
            "path": "documents/empty.txt",
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "byte_count": len(source.read_bytes()),
        },
        deep=True,
    )
    manifest = base.model_copy(update={"documents": [entry]}, deep=True)
    write_manifest(corpus, manifest)
    registry = ParserRegistry()
    registry.register(EmptyWarningParser())

    with pytest.raises(DocumentParseError) as captured:
        ingest_corpus(corpus, registry=registry, ingested_at=FIXED_TIME)

    assert captured.value.code == "empty_document"
