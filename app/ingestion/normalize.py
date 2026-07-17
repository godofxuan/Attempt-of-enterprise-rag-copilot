from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.corpus.schemas import (
    CorpusManifest,
    ManifestDocument,
    SmokeFixtureManifest,
)
from app.domain.documents import (
    DocumentParseError,
    DocumentRecord,
    DocumentVersion,
    ParseResult,
)
from app.ingestion.parsers import ParserRegistry, build_default_registry


SourceManifest = CorpusManifest | SmokeFixtureManifest


def _error(code: str, path: Path, message: str) -> DocumentParseError:
    return DocumentParseError(
        code=code,
        path=path,
        parser="normalizer",
        message=message,
    )


def load_source_manifest(path: Path) -> SourceManifest:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        schema_version = payload.get("schema_version")
        if schema_version == "enterprise_corpus_manifest_v1":
            return CorpusManifest.model_validate(payload)
        if schema_version == "enterprise_smoke_fixture_v1":
            return SmokeFixtureManifest.model_validate(payload)
        raise ValueError(f"unsupported manifest schema {schema_version!r}")
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise _error("invalid_manifest", Path(path), str(exc)) from exc


def _confined_source_path(root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute():
        raise _error(
            "unsafe_source_path",
            relative,
            "manifest source path must be relative",
        )
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise _error(
            "unsafe_source_path",
            relative,
            "manifest source path escapes corpus root",
        ) from exc
    return resolved


def _normalized_text_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _infer_title(result: ParseResult, path: Path) -> str:
    if result.headings:
        return result.headings[0]
    for table in result.tables:
        header_map = {header.casefold(): index for index, header in enumerate(table.headers)}
        title_index = header_map.get("title")
        if title_index is not None:
            for row in table.rows:
                if row[title_index].strip():
                    return row[title_index].strip()
    for line in result.text.splitlines():
        if line.strip():
            return line.strip()
    return path.stem


def normalize_document(
    entry: ManifestDocument,
    source_path: Path,
    result: ParseResult,
    *,
    ingested_at: datetime,
    supersedes_doc_id: str | None = None,
) -> DocumentRecord:
    if not result.text.strip() and not result.tables:
        raise _error(
            "empty_document",
            source_path,
            "parsed document has no indexable text or tables",
        )
    metadata = entry.metadata
    return DocumentRecord(
        doc_id=entry.doc_id,
        title=_infer_title(result, source_path),
        source_type=entry.source_type,
        source_path=Path(entry.path).as_posix(),
        format=entry.format,
        department=metadata.actual_department,
        filed_department=metadata.filed_department,
        project_id=None,
        policy_id=metadata.policy_id,
        region=metadata.region,
        tenant_id=metadata.tenant,
        acl_groups=list(metadata.acl_groups),
        document_version=DocumentVersion(
            version_id=metadata.version_id,
            version=metadata.version,
            status=metadata.status,
            effective_from=metadata.effective_from,
            effective_to=metadata.effective_to,
            supersedes_version_id=metadata.supersedes,
            supersedes_doc_id=supersedes_doc_id,
            authority_level=metadata.authority,
        ),
        authority_level=metadata.authority,
        checksum=entry.sha256,
        normalized_text_hash=_normalized_text_hash(result.text),
        ingested_at=ingested_at,
        parser_name=result.parser_name,
        parser_version=result.parser_version,
        text=result.text,
        sections=result.sections,
        tables=result.tables,
        parse_warnings=result.parse_warnings,
        fact_ids=list(entry.fact_ids),
        variant=entry.variant,
        duplicate_of=metadata.duplicate_of,
    )


def ingest_corpus(
    root: Path,
    *,
    registry: ParserRegistry | None = None,
    ingested_at: datetime | None = None,
) -> list[DocumentRecord]:
    root = Path(root)
    manifest = load_source_manifest(root / "manifest.json")
    parser_registry = registry or build_default_registry()
    ingestion_time = ingested_at or datetime.now(timezone.utc)
    authoritative_by_version = {
        entry.metadata.version_id: entry.doc_id
        for entry in manifest.documents
        if entry.variant == "authoritative"
    }

    records: list[DocumentRecord] = []
    for entry in manifest.documents:
        source_path = _confined_source_path(root, entry.path)
        if not source_path.is_file():
            raise _error("file_not_found", source_path, "manifest document is missing")
        content = source_path.read_bytes()
        checksum = hashlib.sha256(content).hexdigest()
        if checksum != entry.sha256:
            raise _error(
                "checksum_mismatch",
                source_path,
                f"expected {entry.sha256}, got {checksum}",
            )
        if len(content) != entry.byte_count:
            raise _error(
                "byte_count_mismatch",
                source_path,
                f"expected {entry.byte_count} bytes, got {len(content)}",
            )
        result = parser_registry.parse(source_path)
        records.append(
            normalize_document(
                entry,
                source_path,
                result,
                ingested_at=ingestion_time,
                supersedes_doc_id=authoritative_by_version.get(
                    entry.metadata.supersedes
                ),
            )
        )
    return records
