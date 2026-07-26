from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.domain.documents import DocumentVersion
from app.ingestion.email_parser import EMAIL_PARSER_NAME, EMAIL_PARSER_VERSION
from app.lifecycle.materializer import ProductionRevisionContentMaterializer
from app.ingestion.file_validation import admit_source_event_asset
from app.ingestion.revision_catalog import (
    DocumentProjection,
    PersistentRevisionCatalog,
    RevisionMaterializationV2,
)
from app.ingestion.quarantine import IngestedAsset
from app.security.identity import Principal
from app.ingestion.source_events import SourceEvent


NOW = datetime(2026, 7, 27, 2, 0, tzinfo=timezone.utc)
EMAIL_FIXTURES = (
    Path(__file__).parents[1] / "fixtures" / "ingestion" / "eml"
)


def _email_projection() -> DocumentProjection:
    return DocumentProjection(
        source_type="mailbox",
        source_path="mailbox:policy/attachment",
        format="eml",
        department="People",
        filed_department="People",
        project_id=None,
        policy_id=None,
        document_version=DocumentVersion(
            version_id="mail-v1",
            version="1",
            status="active",
            effective_from=NOW.date(),
            authority_level=70,
        ),
        authority_level=70,
        variant="authoritative",
    )


def _stage_email(
    tmp_path: Path,
) -> tuple[SourceEvent, Principal, Path, IngestedAsset]:
    content = (EMAIL_FIXTURES / "mixed_attachment.eml").read_bytes()
    projection = _email_projection()
    event = SourceEvent(
        event_id="evt-email-materialization",
        operation="UPSERT",
        tenant_id="tenant-a",
        region="ap-east",
        source_system="mailbox",
        source_key="policy/attachment",
        occurred_at=NOW,
        content_relpath="mail/attachment.eml",
        declared_media_type="message/rfc822",
        content_sha256=hashlib.sha256(content).hexdigest(),
        actor_pseudonym="actor-ops",
        acl_groups=("group-employees",),
        metadata={
            "document_projection_sha256": projection.canonical_sha256(),
        },
    )
    principal = Principal(
        subject="ops-user",
        tenant_id="tenant-a",
        region="ap-east",
        groups=["group-employees"],
        roles=["rag.operator"],
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        key_id="test-key",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    input_root = (tmp_path / "input").absolute()
    source = input_root / "mail" / "attachment.eml"
    source.parent.mkdir(parents=True)
    source.write_bytes(content)
    asset_root = (tmp_path / "assets").absolute()
    receipt = admit_source_event_asset(
        event=event,
        principal=principal,
        source_root=input_root,
        storage_root=asset_root,
    )
    return event, principal, asset_root, receipt


def _asset_store_snapshot(
    asset_root: Path,
) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(asset_root).as_posix(): (
            path.read_bytes(),
            path.stat().st_mtime_ns,
        )
        for path in asset_root.rglob("*")
        if path.is_file()
    }


def _implementation_sha256(path: Path) -> str:
    content = path.read_bytes()
    digest = hashlib.sha256()
    digest.update(len(path.name).to_bytes(4, "big"))
    digest.update(path.name.encode("ascii"))
    digest.update(len(content).to_bytes(8, "big"))
    digest.update(content)
    return digest.hexdigest()


def test_v2_materialization_projection_survives_catalog_restart(
    tmp_path: Path,
) -> None:
    content_sha256 = hashlib.sha256(b"policy").hexdigest()
    projection = DocumentProjection(
        source_type="policy",
        source_path="sharepoint:policy/leave",
        format="markdown",
        department="People",
        filed_department="People",
        project_id="people-platform",
        policy_id=None,
        document_version=DocumentVersion(
            version_id="leave-v1",
            version="1",
            status="active",
            effective_from=NOW.date(),
            authority_level=80,
        ),
        authority_level=80,
        fact_ids=("fact-leave-days",),
        variant="authoritative",
    )
    event = SourceEvent(
        event_id="evt-v2-materialization",
        operation="UPSERT",
        tenant_id="tenant-a",
        region="ap-east",
        source_system="sharepoint",
        source_key="policy/leave",
        occurred_at=NOW,
        content_relpath="policies/leave.md",
        declared_media_type="text/markdown",
        content_sha256=content_sha256,
        actor_pseudonym="actor-ops",
        acl_groups=("group-employees",),
        metadata={
            "document_projection_sha256": projection.canonical_sha256(),
        },
    )
    root = (tmp_path / "catalog").absolute()
    catalog = PersistentRevisionCatalog(root)
    accepted = catalog.apply(
        event,
        materialization=RevisionMaterializationV2(
            document_id="doc-leave",
            asset_id=f"asset_{'1' * 32}",
            parent_event_id=event.event_id,
            content_sha256=content_sha256,
            normalized_sha256=content_sha256,
            parser_name="markdown",
            parser_version="1",
            normalizer_version="1",
            document_projection=projection,
        ),
    )

    restarted = PersistentRevisionCatalog(root).snapshot()
    persisted = next(
        revision
        for revision in restarted.revisions
        if revision.revision_id == accepted.revision.revision_id
    )

    assert isinstance(persisted.materialization, RevisionMaterializationV2)
    assert persisted.materialization.document_projection == projection
    assert (
        persisted.materialization.document_projection.canonical_sha256()
        == event.metadata["document_projection_sha256"]
    )


def test_materializer_rebuilds_document_from_catalog_and_asset_after_restart(
    tmp_path: Path,
) -> None:
    content = b"# Leave\nEmployees receive ten days of annual leave.\n"
    content_sha256 = hashlib.sha256(content).hexdigest()
    projection = DocumentProjection(
        source_type="policy",
        source_path="sharepoint:policy/leave",
        format="markdown",
        department="People",
        filed_department="People",
        project_id=None,
        policy_id=None,
        document_version=DocumentVersion(
            version_id="leave-v1",
            version="1",
            status="active",
            effective_from=NOW.date(),
            authority_level=80,
        ),
        authority_level=80,
        variant="authoritative",
    )
    event = SourceEvent(
        event_id="evt-restart-materialization",
        operation="UPSERT",
        tenant_id="tenant-a",
        region="ap-east",
        source_system="sharepoint",
        source_key="policy/leave",
        occurred_at=NOW,
        content_relpath="policies/leave.md",
        declared_media_type="text/markdown",
        content_sha256=content_sha256,
        actor_pseudonym="actor-ops",
        acl_groups=("group-employees",),
        metadata={
            "document_projection_sha256": projection.canonical_sha256(),
        },
    )
    principal = Principal(
        subject="ops-user",
        tenant_id="tenant-a",
        region="ap-east",
        groups=["group-employees"],
        roles=["rag.operator"],
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        key_id="test-key",
        issued_at=NOW,
        expires_at=NOW.replace(hour=3),
    )
    input_root = (tmp_path / "input").absolute()
    source = input_root / "policies" / "leave.md"
    source.parent.mkdir(parents=True)
    source.write_bytes(content)
    asset_root = (tmp_path / "assets").absolute()
    receipt = admit_source_event_asset(
        event=event,
        principal=principal,
        source_root=input_root,
        storage_root=asset_root,
    )
    first_process = ProductionRevisionContentMaterializer(asset_root=asset_root)
    materialization = first_process.prepare(
        event=event,
        receipt=receipt,
        document_projection=projection,
        principal=principal,
    )
    catalog_root = (tmp_path / "catalog").absolute()
    accepted = PersistentRevisionCatalog(catalog_root).apply(
        event,
        materialization=materialization,
    )

    restarted = ProductionRevisionContentMaterializer(asset_root=asset_root)
    parsed = restarted.parse_content(accepted.revision)
    normalized = restarted.normalize_content(accepted.revision, parsed)
    document = restarted.materialize_document(
        accepted.revision,
        normalized,
    )

    assert document.doc_id == materialization.document_id
    assert document.title == "Leave"
    assert document.department == "People"
    assert document.text == "Leave\nEmployees receive ten days of annual leave."
    assert document.checksum == content_sha256


def test_email_prepare_uses_g4_and_publishes_each_attachment_once(
    tmp_path: Path,
) -> None:
    event, principal, asset_root, receipt = _stage_email(tmp_path)
    projection = _email_projection()
    materializer = ProductionRevisionContentMaterializer(
        asset_root=asset_root
    )

    materialization = materializer.prepare(
        event=event,
        receipt=receipt,
        document_projection=projection,
        principal=principal,
    )
    accepted = PersistentRevisionCatalog(
        (tmp_path / "catalog").absolute()
    ).apply(event, materialization=materialization)
    parsed = materializer.parse_content(accepted.revision)

    assert materialization.parser_name == EMAIL_PARSER_NAME
    assert materialization.parser_version == EMAIL_PARSER_VERSION
    assert parsed.text == "The attached note is fictional."
    assert len(tuple((asset_root / "staged").glob("*/receipt.json"))) == 2


def test_email_restart_reparses_root_without_mutating_child_assets(
    tmp_path: Path,
) -> None:
    event, principal, asset_root, receipt = _stage_email(tmp_path)
    first_process = ProductionRevisionContentMaterializer(
        asset_root=asset_root
    )
    materialization = first_process.prepare(
        event=event,
        receipt=receipt,
        document_projection=_email_projection(),
        principal=principal,
    )
    accepted = PersistentRevisionCatalog(
        (tmp_path / "catalog").absolute()
    ).apply(event, materialization=materialization)
    expected = first_process.parse_content(accepted.revision)
    before = _asset_store_snapshot(asset_root)

    restarted = ProductionRevisionContentMaterializer(
        asset_root=asset_root
    )
    actual = restarted.parse_content(accepted.revision)

    assert actual == expected
    assert _asset_store_snapshot(asset_root) == before


def test_email_parser_fingerprint_binds_the_g4_implementation(
    tmp_path: Path,
) -> None:
    event, principal, asset_root, receipt = _stage_email(tmp_path)
    materializer = ProductionRevisionContentMaterializer(
        asset_root=asset_root
    )
    materialization = materializer.prepare(
        event=event,
        receipt=receipt,
        document_projection=_email_projection(),
        principal=principal,
    )
    accepted = PersistentRevisionCatalog(
        (tmp_path / "catalog").absolute()
    ).apply(event, materialization=materialization)

    fingerprint = materializer.parser_fingerprint(accepted.revision)

    assert fingerprint.name == EMAIL_PARSER_NAME
    assert fingerprint.semantic_version == EMAIL_PARSER_VERSION
    assert fingerprint.implementation_sha256 == _implementation_sha256(
        Path(__file__).parents[2] / "app" / "ingestion" / "email_parser.py"
    )
