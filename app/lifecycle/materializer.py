from __future__ import annotations

import hashlib
import sys
from pathlib import Path, PurePosixPath

import pydantic

from app.domain.documents import DocumentRecord, ParseResult
from app.indexing.computation_cache import (
    ComponentFingerprint,
    NormalizedContentArtifact,
    ParsedContentArtifact,
)
from app.ingestion.email_parser import (
    EMAIL_PARSER_NAME,
    EmailParseError,
    parse_staged_email,
    parse_staged_email_body_read_only,
)
from app.ingestion.parsers import ParserRegistry, build_default_registry
from app.ingestion.quarantine import IngestedAsset, SecureAssetStore
from app.ingestion.revision_catalog import (
    DocumentProjection,
    DocumentRevision,
    RevisionCatalogSnapshot,
    RevisionMaterializationV2,
)
from app.ingestion.source_events import SourceEvent
from app.security.identity import Principal


NORMALIZER_VERSION = "1"
_PARSER_MODULES = {
    "docx": ("parsers.py", "parsers_docx.py"),
    "pdf": ("parsers.py", "parsers_pdf.py"),
    EMAIL_PARSER_NAME: ("email_parser.py",),
}


def _implementation_sha256(*module_names: str) -> str:
    root = Path(__file__).resolve().parents[1] / "ingestion"
    digest = hashlib.sha256()
    for module_name in sorted(module_names):
        content = (root / module_name).read_bytes()
        digest.update(len(module_name).to_bytes(4, "big"))
        digest.update(module_name.encode("ascii"))
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _document_id(event: SourceEvent) -> str:
    identity = "\0".join(
        (event.tenant_id, event.source_system, event.source_key)
    ).encode("utf-8")
    return f"doc_{hashlib.sha256(identity).hexdigest()}"


def _title(parsed: ParsedContentArtifact, fallback: str) -> str:
    if parsed.headings:
        candidate = parsed.headings[0].strip()
        if candidate:
            return candidate[:1024]
    metadata = dict(parsed.metadata)
    candidate = metadata.get("title", "").strip()
    if candidate:
        return candidate[:1024]
    for line in parsed.text.splitlines():
        candidate = line.strip()
        if candidate:
            return candidate[:1024]
    return fallback[:1024]


class ProductionRevisionContentMaterializer:
    def __init__(
        self,
        *,
        asset_root: Path,
        parser_registry: ParserRegistry | None = None,
        max_asset_bytes: int = 128 * 1024 * 1024,
    ) -> None:
        root = Path(asset_root)
        if not root.is_absolute():
            raise ValueError("asset_root must be absolute")
        if max_asset_bytes < 1:
            raise ValueError("max_asset_bytes must be positive")
        self.asset_root = root
        self.parser_registry = parser_registry or build_default_registry()
        self.max_asset_bytes = max_asset_bytes
        self._prepared: dict[str, ParsedContentArtifact] = {}

    def prepare(
        self,
        *,
        event: SourceEvent,
        receipt: IngestedAsset,
        document_projection: DocumentProjection,
        principal: Principal,
    ) -> RevisionMaterializationV2:
        if (
            event.operation != "UPSERT"
            or receipt.status != "STAGED"
            or receipt.parent_event_id != event.event_id
            or receipt.content_sha256 != event.content_sha256
            or receipt.verified_media_type != event.declared_media_type
            or event.metadata.get("document_projection_sha256")
            != document_projection.canonical_sha256()
        ):
            raise ValueError("accepted asset does not match the source event")
        parsed_result = self._parse_receipt_for_acceptance(
            event=event,
            receipt=receipt,
            principal=principal,
        )
        parsed = ParsedContentArtifact.from_parse_result(parsed_result)
        normalized = self._normalize(parsed, fallback=event.source_key)
        self._prepared[receipt.asset_id] = parsed
        return RevisionMaterializationV2(
            document_id=_document_id(event),
            asset_id=receipt.asset_id,
            parent_event_id=event.event_id,
            content_sha256=event.content_sha256,
            normalized_sha256=normalized.normalized_sha256,
            parser_name=parsed_result.parser_name,
            parser_version=parsed_result.parser_version,
            normalizer_version=NORMALIZER_VERSION,
            document_projection=document_projection,
        )

    def parser_fingerprint(
        self,
        revision: DocumentRevision,
    ) -> ComponentFingerprint:
        materialization = revision.materialization
        if materialization is None:
            raise ValueError("revision is not materialized")
        modules = _PARSER_MODULES.get(
            materialization.parser_name,
            ("parsers.py",),
        )
        return ComponentFingerprint(
            name=materialization.parser_name,
            semantic_version=materialization.parser_version,
            implementation_sha256=_implementation_sha256(*modules),
            dependency_versions=tuple(
                sorted(
                    (
                        f"pydantic={pydantic.__version__}",
                        f"python={sys.version_info.major}.{sys.version_info.minor}",
                    )
                )
            ),
        )

    def parse_content(
        self,
        revision: DocumentRevision,
    ) -> ParsedContentArtifact:
        materialization = revision.materialization
        if materialization is None:
            raise ValueError("revision is not materialized")
        prepared = self._prepared.get(materialization.asset_id)
        if prepared is not None:
            return prepared
        store = SecureAssetStore(self.asset_root)
        receipt = store.load_staged_receipt(materialization.asset_id)
        if (
            receipt.parent_event_id != revision.event_id
            or receipt.content_sha256 != revision.content_sha256
            or receipt.verified_media_type != revision.declared_media_type
        ):
            raise ValueError("staged asset does not match the revision")
        result = self._parse_receipt(receipt)
        if (
            result.parser_name != materialization.parser_name
            or result.parser_version != materialization.parser_version
        ):
            raise ValueError("parser identity changed after event acceptance")
        return ParsedContentArtifact.from_parse_result(result)

    def normalize_content(
        self,
        revision: DocumentRevision,
        parsed: ParsedContentArtifact,
    ) -> NormalizedContentArtifact:
        return self._normalize(parsed, fallback=revision.source_key)

    def materialize_document(
        self,
        revision: DocumentRevision,
        normalized: NormalizedContentArtifact,
    ) -> DocumentRecord:
        materialization = revision.materialization
        if not isinstance(materialization, RevisionMaterializationV2):
            raise ValueError(
                "production materialization requires revision_materialization_v2"
            )
        projection = materialization.document_projection
        if revision.content_sha256 is None:
            raise ValueError("live revision has no content hash")
        return DocumentRecord(
            doc_id=materialization.document_id,
            title=normalized.title,
            source_type=projection.source_type,
            source_path=projection.source_path,
            format=projection.format,
            department=projection.department,
            filed_department=projection.filed_department,
            project_id=projection.project_id,
            policy_id=projection.policy_id,
            region=revision.region,
            tenant_id=revision.tenant_id,
            acl_groups=list(revision.acl_groups),
            document_version=projection.document_version.model_copy(deep=True),
            authority_level=projection.authority_level,
            checksum=revision.content_sha256,
            normalized_text_hash=normalized.normalized_sha256,
            ingested_at=revision.occurred_at,
            parser_name=materialization.parser_name,
            parser_version=materialization.parser_version,
            text=normalized.text,
            sections=list(normalized.sections),
            tables=list(normalized.tables),
            parse_warnings=list(normalized.parse_warnings),
            fact_ids=list(projection.fact_ids),
            variant=projection.variant,
            duplicate_of=projection.duplicate_of,
        )

    def validate_catalog_files(self, catalog: RevisionCatalogSnapshot) -> None:
        store = SecureAssetStore(self.asset_root)
        revisions = {
            revision.revision_id: revision
            for revision in catalog.revisions
        }
        for head in catalog.ledger.source_heads:
            if head.deleted:
                continue
            revision = revisions[head.current_revision_id]
            materialization = revision.materialization
            if materialization is None or revision.content_sha256 is None:
                raise ValueError("live revision is not materialized")
            receipt = store.load_staged_receipt(materialization.asset_id)
            if (
                receipt.parent_event_id != revision.event_id
                or receipt.content_sha256 != revision.content_sha256
                or receipt.verified_media_type != revision.declared_media_type
            ):
                raise ValueError("staged asset does not match the catalog")
            store.read_staged(receipt, byte_limit=self.max_asset_bytes)

    def _parse_receipt_for_acceptance(
        self,
        *,
        event: SourceEvent,
        receipt: IngestedAsset,
        principal: Principal,
    ) -> ParseResult:
        if receipt.stored_relpath is None:
            raise ValueError("staged receipt has no payload path")
        suffix = PurePosixPath(receipt.stored_relpath).suffix.casefold()
        if suffix != ".eml":
            return self._parse_receipt(receipt)

        outcome = parse_staged_email(
            event=event,
            principal=principal,
            receipt=receipt,
            storage_root=self.asset_root,
            parser_registry=self.parser_registry,
        )
        if outcome.status != "PARSED" or outcome.message is None:
            raise EmailParseError(
                "source_quarantined",
                "The staged email was quarantined.",
            )
        return outcome.message.body

    def _parse_receipt(self, receipt: IngestedAsset) -> ParseResult:
        if receipt.stored_relpath is None:
            raise ValueError("staged receipt has no payload path")
        suffix = PurePosixPath(receipt.stored_relpath).suffix.casefold()
        if suffix == ".eml":
            return parse_staged_email_body_read_only(
                receipt=receipt,
                storage_root=self.asset_root,
            )
        content = SecureAssetStore(self.asset_root).read_staged(
            receipt,
            byte_limit=self.max_asset_bytes,
        )
        return self.parser_registry.parse_bytes(content, suffix=suffix)

    @staticmethod
    def _normalize(
        parsed: ParsedContentArtifact,
        *,
        fallback: str,
    ) -> NormalizedContentArtifact:
        text = parsed.text.strip()
        return NormalizedContentArtifact(
            title=_title(parsed, fallback),
            text=text,
            sections=parsed.sections,
            tables=parsed.tables,
            parse_warnings=parsed.parse_warnings,
            normalized_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )


__all__ = [
    "NORMALIZER_VERSION",
    "ProductionRevisionContentMaterializer",
]
