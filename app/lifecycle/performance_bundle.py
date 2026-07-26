from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Literal, Mapping, Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.domain.documents import DocumentRecord
from app.domain.queries import QueryFilters, SearchRequest, UserContext
from app.filesystem import atomic_directory_move
from app.indexing.computation_cache import (
    ComponentFingerprint,
    NormalizedContentArtifact,
    ParsedContentArtifact,
)
from app.ingestion.path_security import (
    absolute_path_has_redirect,
    stat_is_redirect,
)
from app.ingestion.revision_catalog import (
    DocumentProjection,
    DocumentRevision,
    RevisionCatalogSnapshot,
    RevisionMaterializationV2,
    canonical_revision_catalog_bytes,
    empty_revision_catalog_snapshot,
    revision_catalog_sha256,
)
from app.ingestion.source_events import SourceEvent, SourceEventLedger


_EXPECTED_FILES = frozenset(
    {
        "base_catalog.json",
        "base_documents.json",
        "change_descriptor.json",
        "query_descriptor.json",
        "target_catalog.json",
        "target_documents.json",
    }
)
_MANIFEST_FILE = "manifest.json"
_MAX_MANIFEST_BYTES = 256 * 1024
_MAX_DESCRIPTOR_BYTES = 16 * 1024 * 1024
_MAX_PAYLOAD_BYTES = 512 * 1024 * 1024
_GENERATOR_VERSION = "1"
_PIPELINE_VERSION = "g10-deterministic-lifecycle-v1"
_SOURCE_SYSTEM = "g10-performance-fixture"
_ACTOR = "g10-fixture-generator"
_TARGET_ACL_CANDIDATES = (
    "benchmark-auditors",
    "benchmark-reviewers",
    "benchmark-observers",
)
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class PerformanceBundleError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class PerformanceBundleModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class PerformanceBundleFile(PerformanceBundleModel):
    path: str = Field(min_length=1, max_length=128)
    byte_count: int = Field(ge=1, le=_MAX_PAYLOAD_BYTES)
    sha256: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or len(path.parts) != 1
            or path.as_posix() != value
            or value in {".", "..", _MANIFEST_FILE}
        ):
            raise ValueError("bundle file path must be a canonical file name")
        return value


class PerformanceBundleCounts(PerformanceBundleModel):
    base_document_count: int = Field(ge=1)
    target_live_document_count: int = Field(ge=1)
    base_event_count: int = Field(ge=1)
    target_event_count: int = Field(ge=1)
    content_update_count: int = Field(ge=0)
    acl_only_count: int = Field(ge=0)
    delete_count: int = Field(ge=0)
    unchanged_count: int = Field(ge=0)
    query_count: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_arithmetic(self) -> PerformanceBundleCounts:
        changed = (
            self.content_update_count
            + self.acl_only_count
            + self.delete_count
        )
        if changed + self.unchanged_count != self.base_document_count:
            raise ValueError("change categories must cover the base corpus")
        if (
            self.target_live_document_count
            != self.base_document_count - self.delete_count
            or self.base_event_count != self.base_document_count
            or self.target_event_count
            != self.base_event_count + changed
        ):
            raise ValueError("bundle counts are arithmetically inconsistent")
        return self


class PerformancePipelineIdentity(PerformanceBundleModel):
    pipeline_id: Literal["g10-deterministic-lifecycle-v1"] = _PIPELINE_VERSION
    parser: ComponentFingerprint
    normalizer_name: Literal["identity-normalizer"] = "identity-normalizer"
    normalizer_version: Literal["1"] = "1"
    chunker_name: Literal["fixed"] = "fixed"
    chunk_size: Literal[500] = 500
    chunk_overlap: Literal[80] = 80
    embedding_backend: Literal["deterministic"] = "deterministic"
    embedding_model: Literal["deterministic-shake256"] = (
        "deterministic-shake256"
    )
    embedding_dimension: Literal[128] = 128
    source_event_schema: Literal["source_event_v1"] = "source_event_v1"
    revision_materialization_schema: Literal["revision_materialization_v2"] = (
        "revision_materialization_v2"
    )
    revision_catalog_schema: Literal["revision_catalog_snapshot_v1"] = (
        "revision_catalog_snapshot_v1"
    )


class PerformanceGeneratorIdentity(PerformanceBundleModel):
    name: Literal["app.lifecycle.performance_bundle"] = (
        "app.lifecycle.performance_bundle"
    )
    semantic_version: Literal["1"] = _GENERATOR_VERSION
    implementation_sha256: str = Field(pattern=_SHA256_PATTERN)


class PerformanceBundleManifest(PerformanceBundleModel):
    schema_version: Literal["performance_bundle_manifest_v1"] = (
        "performance_bundle_manifest_v1"
    )
    generator: PerformanceGeneratorIdentity
    pipeline: PerformancePipelineIdentity
    counts: PerformanceBundleCounts
    files: tuple[PerformanceBundleFile, ...] = Field(min_length=6, max_length=6)

    @field_validator("files")
    @classmethod
    def validate_files(
        cls,
        values: tuple[PerformanceBundleFile, ...],
    ) -> tuple[PerformanceBundleFile, ...]:
        paths = [value.path for value in values]
        if paths != sorted(paths) or set(paths) != _EXPECTED_FILES:
            raise ValueError("manifest must bind the exact canonical bundle files")
        return values


class PerformanceRevisionPayload(PerformanceBundleModel):
    source_system: str = Field(min_length=1, max_length=128)
    source_key: str = Field(min_length=1, max_length=256)
    revision_id: str = Field(pattern=r"^rev_[0-9a-f]{64}$")
    document: DocumentRecord
    parsed: ParsedContentArtifact
    normalized: NormalizedContentArtifact

    @model_validator(mode="after")
    def validate_artifacts(self) -> PerformanceRevisionPayload:
        if (
            self.parsed.text != self.document.text
            or self.parsed.sections != tuple(self.document.sections)
            or self.parsed.tables != tuple(self.document.tables)
            or self.parsed.parse_warnings
            != tuple(self.document.parse_warnings)
            or self.normalized.title != self.document.title
            or self.normalized.text != self.document.text
            or self.normalized.sections != tuple(self.document.sections)
            or self.normalized.tables != tuple(self.document.tables)
            or self.normalized.parse_warnings
            != tuple(self.document.parse_warnings)
            or self.normalized.normalized_sha256
            != self.document.normalized_text_hash
        ):
            raise ValueError("document, parsed, and normalized payloads disagree")
        return self


class PerformanceDocumentPayload(PerformanceBundleModel):
    schema_version: Literal["performance_document_payload_v1"] = (
        "performance_document_payload_v1"
    )
    role: Literal["base", "target"]
    entries: tuple[PerformanceRevisionPayload, ...] = Field(min_length=1)

    @field_validator("entries")
    @classmethod
    def validate_entries(
        cls,
        values: tuple[PerformanceRevisionPayload, ...],
    ) -> tuple[PerformanceRevisionPayload, ...]:
        identities = [
            (value.source_system, value.source_key) for value in values
        ]
        if identities != sorted(identities) or len(identities) != len(
            set(identities)
        ):
            raise ValueError("document payload entries must use canonical identity order")
        revision_ids = [value.revision_id for value in values]
        document_ids = [value.document.doc_id for value in values]
        if (
            len(revision_ids) != len(set(revision_ids))
            or len(document_ids) != len(set(document_ids))
        ):
            raise ValueError("document payload identities must be unique")
        return values


class PerformanceChangeCategories(PerformanceBundleModel):
    content_updates: tuple[str, ...] = ()
    acl_only_updates: tuple[str, ...] = ()
    deletes: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()

    @field_validator(
        "content_updates",
        "acl_only_updates",
        "deletes",
        "unchanged",
    )
    @classmethod
    def validate_category(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        if values != tuple(sorted(values)) or len(values) != len(set(values)):
            raise ValueError("change category values must be unique and sorted")
        return values

    @model_validator(mode="after")
    def validate_disjoint(self) -> PerformanceChangeCategories:
        combined = (
            *self.content_updates,
            *self.acl_only_updates,
            *self.deletes,
            *self.unchanged,
        )
        if len(combined) != len(set(combined)):
            raise ValueError("change categories must not overlap")
        return self


class PerformanceDeletionOracle(PerformanceBundleModel):
    source_key: str = Field(min_length=1, max_length=256)
    base_doc_id: str = Field(min_length=1, max_length=256)
    base_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{64}$")


class PerformanceChangeDescriptor(PerformanceBundleModel):
    schema_version: Literal["performance_change_descriptor_v1"] = (
        "performance_change_descriptor_v1"
    )
    base_catalog_sha256: str = Field(pattern=_SHA256_PATTERN)
    target_catalog_sha256: str = Field(pattern=_SHA256_PATTERN)
    base_events: tuple[SourceEvent, ...] = Field(min_length=1)
    change_events: tuple[SourceEvent, ...] = ()
    categories: PerformanceChangeCategories
    deletion_oracles: tuple[PerformanceDeletionOracle, ...] = ()

    @field_validator("base_events", "change_events")
    @classmethod
    def validate_event_order(
        cls,
        values: tuple[SourceEvent, ...],
    ) -> tuple[SourceEvent, ...]:
        identities = [
            (value.source_system, value.source_key) for value in values
        ]
        event_ids = [value.event_id for value in values]
        if (
            identities != sorted(identities)
            or len(identities) != len(set(identities))
            or len(event_ids) != len(set(event_ids))
        ):
            raise ValueError("descriptor events must use canonical source order")
        return values

    @field_validator("deletion_oracles")
    @classmethod
    def validate_deletion_oracles(
        cls,
        values: tuple[PerformanceDeletionOracle, ...],
    ) -> tuple[PerformanceDeletionOracle, ...]:
        source_keys = [value.source_key for value in values]
        if (
            source_keys != sorted(source_keys)
            or len(source_keys) != len(set(source_keys))
        ):
            raise ValueError("deletion oracles must use unique canonical order")
        return values

    @model_validator(mode="after")
    def validate_oracle_coverage(self) -> PerformanceChangeDescriptor:
        if tuple(value.source_key for value in self.deletion_oracles) != (
            self.categories.deletes
        ):
            raise ValueError(
                "deletion oracles must cover the exact delete category"
            )
        return self


class PerformanceQueryCase(PerformanceBundleModel):
    query_id: str = Field(min_length=1, max_length=128)
    category: Literal["unchanged", "content_update", "acl_only", "delete"]
    expectation: Literal[
        "live_hit",
        "absent_from_target",
        "denied_by_acl",
    ]
    denial_dimension: Literal[
        "none",
        "removed_group",
        "tenant",
        "region",
    ] = "none"
    expected_doc_id: str = Field(min_length=1, max_length=256)
    expected_source_key: str = Field(min_length=1, max_length=256)
    request: SearchRequest

    @model_validator(mode="after")
    def validate_expectation(self) -> PerformanceQueryCase:
        if self.category == "delete":
            valid = (
                self.expectation == "absent_from_target"
                and self.denial_dimension == "none"
            )
        elif self.category == "acl_only":
            valid = (
                self.expectation == "live_hit"
                and self.denial_dimension == "none"
            ) or (
                self.expectation == "denied_by_acl"
                and self.denial_dimension != "none"
            )
        else:
            valid = (
                self.expectation == "live_hit"
                and self.denial_dimension == "none"
            )
        if not valid:
            raise ValueError("query expectation does not match its category")
        return self


class PerformanceQueryDescriptor(PerformanceBundleModel):
    schema_version: Literal["performance_query_descriptor_v1"] = (
        "performance_query_descriptor_v1"
    )
    cases: tuple[PerformanceQueryCase, ...] = Field(min_length=1)

    @field_validator("cases")
    @classmethod
    def validate_cases(
        cls,
        values: tuple[PerformanceQueryCase, ...],
    ) -> tuple[PerformanceQueryCase, ...]:
        query_ids = [value.query_id for value in values]
        if query_ids != sorted(query_ids) or len(query_ids) != len(set(query_ids)):
            raise ValueError("query cases must use unique canonical order")
        return values


def _canonical_json_bytes(model: BaseModel) -> bytes:
    return json.dumps(
        model.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_performance_bundle_manifest_bytes(
    manifest: PerformanceBundleManifest,
) -> bytes:
    validated = PerformanceBundleManifest.model_validate(
        manifest.model_dump(mode="json")
    )
    return _canonical_json_bytes(validated)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _implementation_sha256() -> str:
    return _sha256(Path(__file__).read_bytes())


def _parser_fingerprint() -> ComponentFingerprint:
    return ComponentFingerprint(
        name="g10-payload-reader",
        semantic_version="1",
        implementation_sha256=_implementation_sha256(),
        dependency_versions=("format=performance_bundle_v1",),
    )


def _source_key(document: DocumentRecord) -> str:
    identity = "\0".join(
        (
            document.tenant_id,
            document.region,
            document.source_path,
            document.doc_id,
        )
    ).encode("utf-8")
    return f"document/{_sha256(identity)}"


def _retrieval_oracle_token(source_key: str) -> str:
    return f"g10oracle{_sha256(source_key.encode('ascii'))}"


def _stable_selection_key(document: DocumentRecord) -> tuple[str, str]:
    source_key = _source_key(document)
    return (_sha256(source_key.encode("ascii")), source_key)


def _projection(document: DocumentRecord) -> DocumentProjection:
    return DocumentProjection(
        source_type=document.source_type,
        source_path=document.source_path,
        format=document.format,
        department=document.department,
        filed_department=document.filed_department,
        project_id=document.project_id,
        policy_id=document.policy_id,
        document_version=document.document_version,
        authority_level=document.authority_level,
        fact_ids=tuple(document.fact_ids),
        variant=document.variant,
        duplicate_of=document.duplicate_of,
    )


def _event_id(kind: str, source_key: str) -> str:
    return f"g10-{kind}-{_sha256(source_key.encode('ascii'))}"


def _asset_id(event_id: str) -> str:
    return f"asset_{_sha256(event_id.encode('ascii'))[:32]}"


def _source_event(
    *,
    kind: Literal["base", "content", "acl", "delete"],
    document: DocumentRecord,
    source_key: str,
    expected_revision_id: str | None,
) -> SourceEvent:
    if kind == "delete":
        return SourceEvent(
            event_id=_event_id(kind, source_key),
            operation="DELETE",
            tenant_id=document.tenant_id,
            region=document.region,
            source_system=_SOURCE_SYSTEM,
            source_key=source_key,
            expected_revision_id=expected_revision_id,
            occurred_at=document.ingested_at + timedelta(seconds=1),
            actor_pseudonym=_ACTOR,
        )
    projection = _projection(document)
    return SourceEvent(
        event_id=_event_id(kind, source_key),
        operation="UPSERT",
        tenant_id=document.tenant_id,
        region=document.region,
        source_system=_SOURCE_SYSTEM,
        source_key=source_key,
        expected_revision_id=expected_revision_id,
        occurred_at=(
            document.ingested_at
            if kind == "base"
            else document.ingested_at
        ),
        content_relpath=(
            "base_documents.json" if kind == "base" else "target_documents.json"
        ),
        declared_media_type="application/json",
        content_sha256=document.checksum,
        actor_pseudonym=_ACTOR,
        acl_groups=tuple(document.acl_groups),
        metadata={
            "document_projection_sha256": projection.canonical_sha256(),
        },
    )


def _materialization(
    event: SourceEvent,
    document: DocumentRecord,
) -> RevisionMaterializationV2:
    return RevisionMaterializationV2(
        document_id=document.doc_id,
        asset_id=_asset_id(event.event_id),
        parent_event_id=event.event_id,
        content_sha256=document.checksum,
        normalized_sha256=document.normalized_text_hash,
        parser_name=document.parser_name,
        parser_version=document.parser_version,
        normalizer_version="1",
        document_projection=_projection(document),
    )


def _apply_catalog_batch_linear(
    base: RevisionCatalogSnapshot,
    events: Sequence[
        tuple[SourceEvent, RevisionMaterializationV2 | None]
    ],
) -> RevisionCatalogSnapshot:
    validated_base = RevisionCatalogSnapshot.model_validate(
        base.model_dump(mode="json")
    )
    ledger = SourceEventLedger.from_snapshot(validated_base.ledger)
    revisions = {
        revision.revision_id: revision
        for revision in validated_base.revisions
    }
    for raw_event, raw_materialization in events:
        event = SourceEvent.model_validate(raw_event.model_dump(mode="json"))
        materialization = (
            None
            if raw_materialization is None
            else RevisionMaterializationV2.model_validate(
                raw_materialization.model_dump(mode="json")
            )
        )
        if event.operation == "DELETE":
            if materialization is not None:
                raise ValueError("DELETE must not include materialization")
        elif (
            materialization is None
            or materialization.parent_event_id != event.event_id
            or materialization.content_sha256 != event.content_sha256
            or event.metadata.get("document_projection_sha256")
            != materialization.document_projection.canonical_sha256()
        ):
            raise ValueError("UPSERT materialization does not match its event")

        application = ledger.apply(event)
        if application.status != "APPLIED":
            raise ValueError("performance bundle events must not replay")
        receipt = application.receipt
        previous = (
            None
            if receipt.previous_revision_id is None
            else revisions.get(receipt.previous_revision_id)
        )
        if receipt.previous_revision_id is not None and previous is None:
            raise ValueError("event previous revision is unavailable")
        if event.operation == "DELETE":
            if previous is None or previous.deleted:
                raise ValueError("DELETE must follow a live revision")
            region = previous.region
            acl_groups = previous.acl_groups
        else:
            region = event.region
            acl_groups = event.acl_groups
        revision = DocumentRevision(
            revision_id=receipt.resulting_revision_id,
            previous_revision_id=receipt.previous_revision_id,
            event_id=event.event_id,
            event_payload_sha256=receipt.payload_sha256,
            operation=event.operation,
            source_system=event.source_system,
            source_key=event.source_key,
            tenant_id=event.tenant_id,
            region=region,
            acl_groups=acl_groups,
            actor_pseudonym=event.actor_pseudonym,
            occurred_at=event.occurred_at,
            declared_media_type=(
                event.declared_media_type
                if event.operation == "UPSERT"
                else None
            ),
            content_sha256=(
                event.content_sha256
                if event.operation == "UPSERT"
                else None
            ),
            materialization=materialization,
            deleted=event.operation == "DELETE",
        )
        if revision.revision_id in revisions:
            raise ValueError("performance bundle revision IDs must be unique")
        revisions[revision.revision_id] = revision
    return RevisionCatalogSnapshot(
        ledger=ledger.snapshot(),
        revisions=tuple(
            revisions[revision_id] for revision_id in sorted(revisions)
        ),
    )


def _payload_entry(
    *,
    revision: DocumentRevision,
    document: DocumentRecord,
) -> PerformanceRevisionPayload:
    return PerformanceRevisionPayload(
        source_system=revision.source_system,
        source_key=revision.source_key,
        revision_id=revision.revision_id,
        document=document,
        parsed=ParsedContentArtifact(
            text=document.text,
            sections=tuple(document.sections),
            headings=tuple(section.heading for section in document.sections),
            tables=tuple(document.tables),
            parse_warnings=tuple(document.parse_warnings),
        ),
        normalized=NormalizedContentArtifact(
            title=document.title,
            text=document.text,
            sections=tuple(document.sections),
            tables=tuple(document.tables),
            parse_warnings=tuple(document.parse_warnings),
            normalized_sha256=document.normalized_text_hash,
        ),
    )


def _validate_input_documents(
    documents: Sequence[DocumentRecord],
) -> list[DocumentRecord]:
    validated = []
    for document in documents:
        strict = DocumentRecord.model_validate(
            document.model_dump(mode="json")
        )
        source_key = _source_key(strict)
        normalized_text = (
            f"{strict.text.strip()}\n\n"
            f"{_retrieval_oracle_token(source_key)}"
        )
        normalized_sha256 = _sha256(normalized_text.encode("utf-8"))
        validated.append(
            strict.model_copy(
                update={
                    "acl_groups": sorted(strict.acl_groups),
                    "fact_ids": sorted(strict.fact_ids),
                    "text": normalized_text,
                    "checksum": normalized_sha256,
                    "normalized_text_hash": normalized_sha256,
                },
                deep=True,
            )
        )
    if not validated:
        raise ValueError("performance bundle requires at least one document")
    identities = [
        (document.tenant_id, document.doc_id) for document in validated
    ]
    source_keys = [_source_key(document) for document in validated]
    if (
        len(identities) != len(set(identities))
        or len(source_keys) != len(set(source_keys))
    ):
        raise ValueError("performance bundle document identities must be unique")
    return sorted(validated, key=_stable_selection_key)


def _content_update(
    document: DocumentRecord,
    source_key: str,
) -> DocumentRecord:
    marker = f"g10-content-update-{_sha256(source_key.encode('ascii'))[:12]}"
    text = f"{document.text.rstrip()}\n\n{marker}"
    digest = _sha256(text.encode("utf-8"))
    version = document.document_version.model_copy(
        update={
            "version_id": f"{document.document_version.version_id}-g10-content",
            "version": f"{document.document_version.version}.g10-content",
        }
    )
    return document.model_copy(
        update={
            "text": text,
            "checksum": digest,
            "normalized_text_hash": digest,
            "document_version": version,
            "ingested_at": document.ingested_at + timedelta(seconds=1),
        },
        deep=True,
    )


def _acl_update(document: DocumentRecord) -> DocumentRecord:
    groups = set(document.acl_groups)
    removed = sorted(groups)[0] if groups else None
    if removed is None:
        raise ValueError("ACL-only fixture requires an existing group")
    addition = next(
        (candidate for candidate in _TARGET_ACL_CANDIDATES if candidate not in groups),
        None,
    )
    if addition is None:
        raise ValueError("document ACL exhausts deterministic fixture groups")
    groups.remove(removed)
    groups.add(addition)
    return document.model_copy(
        update={
            "acl_groups": sorted(groups),
            "ingested_at": document.ingested_at + timedelta(seconds=1),
        },
        deep=True,
    )


def _query_cases(
    *,
    categories: PerformanceChangeCategories,
    base_entries: Mapping[str, PerformanceRevisionPayload],
    target_entries: Mapping[str, PerformanceRevisionPayload],
) -> tuple[PerformanceQueryCase, ...]:
    selected = (
        ("acl_only", categories.acl_only_updates[:2]),
        ("content_update", categories.content_updates[:2]),
        ("delete", categories.deletes[:1]),
        ("unchanged", categories.unchanged[:2]),
    )
    cases: list[PerformanceQueryCase] = []
    for category, source_keys in selected:
        for source_key in source_keys:
            entry = (
                base_entries[source_key]
                if category == "delete"
                else target_entries[source_key]
            )
            document = entry.document
            query_id = f"query-{category}-{_sha256(source_key.encode('ascii'))[:12]}"
            oracle_token = _retrieval_oracle_token(source_key)
            cases.append(
                PerformanceQueryCase(
                    query_id=query_id,
                    category=category,
                    expectation=(
                        "absent_from_target"
                        if category == "delete"
                        else "live_hit"
                    ),
                    expected_doc_id=document.doc_id,
                    expected_source_key=source_key,
                    denial_dimension="none",
                    request=SearchRequest(
                        request_id=query_id,
                        query=f"{document.title} {oracle_token}",
                        purpose="deterministic lifecycle equivalence check",
                        user=UserContext(
                            user_id="g10-query-user",
                            tenant_id=document.tenant_id,
                            region=document.region,
                            groups=list(document.acl_groups),
                            roles=[],
                        ),
                        filters=QueryFilters(
                            departments=[document.department],
                            policy_ids=(
                                [document.policy_id]
                                if document.policy_id is not None
                                else []
                            ),
                            statuses=[document.document_version.status],
                            temporal_scope="all",
                            authoritative_only=False,
                            min_authority=1,
                        ),
                        top_k=5,
                        candidate_k=20,
                        mode="bm25",
                        include_parent=False,
                        max_chunks_per_doc=2,
                        timeout_ms=5000,
                    ),
                )
            )
            if category == "acl_only":
                base_document = base_entries[source_key].document
                removed_groups = sorted(
                    set(base_document.acl_groups)
                    - set(document.acl_groups)
                )
                if len(removed_groups) != 1:
                    raise ValueError(
                        "ACL-only query requires one removed group"
                    )
                denial_users = {
                    "removed_group": UserContext(
                        user_id="g10-query-denied-removed-group",
                        tenant_id=document.tenant_id,
                        region=document.region,
                        groups=removed_groups,
                        roles=[],
                    ),
                    "tenant": UserContext(
                        user_id="g10-query-denied-tenant",
                        tenant_id="g10-unauthorized-tenant",
                        region=document.region,
                        groups=list(document.acl_groups),
                        roles=[],
                    ),
                    "region": UserContext(
                        user_id="g10-query-denied-region",
                        tenant_id=document.tenant_id,
                        region="g10-unauthorized-region",
                        groups=list(document.acl_groups),
                        roles=[],
                    ),
                }
                for denial_dimension, denial_user in denial_users.items():
                    denied_query_id = (
                        f"{query_id}-denied-{denial_dimension}"
                    )
                    cases.append(
                        PerformanceQueryCase(
                            query_id=denied_query_id,
                            category=category,
                            expectation="denied_by_acl",
                            denial_dimension=denial_dimension,
                            expected_doc_id=document.doc_id,
                            expected_source_key=source_key,
                            request=SearchRequest(
                                request_id=denied_query_id,
                                query=(
                                    f"{document.title} {oracle_token}"
                                ),
                                purpose=(
                                    "deterministic lifecycle ACL denial check"
                                ),
                                user=denial_user,
                                filters=QueryFilters(
                                    departments=[document.department],
                                    policy_ids=(
                                        [document.policy_id]
                                        if document.policy_id is not None
                                        else []
                                    ),
                                    statuses=[
                                        document.document_version.status
                                    ],
                                    temporal_scope="all",
                                    authoritative_only=False,
                                    min_authority=1,
                                ),
                                top_k=5,
                                candidate_k=20,
                                mode="bm25",
                                include_parent=False,
                                max_chunks_per_doc=2,
                                timeout_ms=5000,
                            ),
                        )
                    )
    return tuple(sorted(cases, key=lambda value: value.query_id))


def _serialize_bundle(
    documents: Sequence[DocumentRecord],
    *,
    content_update_count: int,
    acl_only_count: int,
    delete_count: int,
) -> tuple[dict[str, bytes], PerformanceBundleManifest]:
    if min(content_update_count, acl_only_count, delete_count) < 0:
        raise ValueError("performance bundle category counts must be non-negative")
    ordered = _validate_input_documents(documents)
    changed_count = content_update_count + acl_only_count + delete_count
    if changed_count >= len(ordered):
        raise ValueError(
            "performance bundle requires at least one unchanged live document"
        )

    content_documents = ordered[:content_update_count]
    acl_documents = ordered[
        content_update_count : content_update_count + acl_only_count
    ]
    delete_documents = ordered[
        content_update_count
        + acl_only_count : content_update_count
        + acl_only_count
        + delete_count
    ]
    unchanged_documents = ordered[changed_count:]
    content_keys = tuple(sorted(_source_key(value) for value in content_documents))
    acl_keys = tuple(sorted(_source_key(value) for value in acl_documents))
    delete_keys = tuple(sorted(_source_key(value) for value in delete_documents))
    unchanged_keys = tuple(sorted(_source_key(value) for value in unchanged_documents))
    categories = PerformanceChangeCategories(
        content_updates=content_keys,
        acl_only_updates=acl_keys,
        deletes=delete_keys,
        unchanged=unchanged_keys,
    )

    base_events: list[SourceEvent] = []
    base_documents = {_source_key(document): document for document in ordered}
    base_batch: list[
        tuple[SourceEvent, RevisionMaterializationV2 | None]
    ] = []
    for source_key in sorted(base_documents):
        document = base_documents[source_key]
        event = _source_event(
            kind="base",
            document=document,
            source_key=source_key,
            expected_revision_id=None,
        )
        base_events.append(event)
        base_batch.append((event, _materialization(event, document)))
    base_catalog = _apply_catalog_batch_linear(
        empty_revision_catalog_snapshot(),
        base_batch,
    )
    base_revisions_by_event = {
        revision.event_id: revision for revision in base_catalog.revisions
    }
    base_entries: dict[str, PerformanceRevisionPayload] = {}
    for event in base_events:
        source_key = event.source_key
        base_entries[source_key] = _payload_entry(
            revision=base_revisions_by_event[event.event_id],
            document=base_documents[source_key],
        )

    base_heads = {
        head.source_key: head for head in base_catalog.ledger.source_heads
    }
    change_events: list[SourceEvent] = []
    target_documents = dict(base_documents)
    change_batch: list[
        tuple[SourceEvent, RevisionMaterializationV2 | None]
    ] = []

    for source_key in categories.content_updates:
        document = _content_update(base_documents[source_key], source_key)
        event = _source_event(
            kind="content",
            document=document,
            source_key=source_key,
            expected_revision_id=base_heads[source_key].current_revision_id,
        )
        change_events.append(event)
        change_batch.append((event, _materialization(event, document)))
        target_documents[source_key] = document

    for source_key in categories.acl_only_updates:
        document = _acl_update(base_documents[source_key])
        event = _source_event(
            kind="acl",
            document=document,
            source_key=source_key,
            expected_revision_id=base_heads[source_key].current_revision_id,
        )
        change_events.append(event)
        change_batch.append((event, _materialization(event, document)))
        target_documents[source_key] = document

    for source_key in categories.deletes:
        document = base_documents[source_key]
        event = _source_event(
            kind="delete",
            document=document,
            source_key=source_key,
            expected_revision_id=base_heads[source_key].current_revision_id,
        )
        change_events.append(event)
        change_batch.append((event, None))
        del target_documents[source_key]

    change_batch.sort(
        key=lambda value: (value[0].source_system, value[0].source_key)
    )
    target_catalog = _apply_catalog_batch_linear(base_catalog, change_batch)
    target_heads = {
        head.source_key: head for head in target_catalog.ledger.source_heads
    }
    target_revisions = {
        revision.revision_id: revision
        for revision in target_catalog.revisions
    }
    target_entries = {
        source_key: _payload_entry(
            revision=target_revisions[
                target_heads[source_key].current_revision_id
            ],
            document=document,
        )
        for source_key, document in target_documents.items()
    }

    base_payload = PerformanceDocumentPayload(
        role="base",
        entries=tuple(base_entries[key] for key in sorted(base_entries)),
    )
    target_payload = PerformanceDocumentPayload(
        role="target",
        entries=tuple(target_entries[key] for key in sorted(target_entries)),
    )
    change_descriptor = PerformanceChangeDescriptor(
        base_catalog_sha256=revision_catalog_sha256(base_catalog),
        target_catalog_sha256=revision_catalog_sha256(target_catalog),
        base_events=tuple(
            sorted(base_events, key=lambda value: (value.source_system, value.source_key))
        ),
        change_events=tuple(
            sorted(
                change_events,
                key=lambda value: (value.source_system, value.source_key),
            )
        ),
        categories=categories,
        deletion_oracles=tuple(
            PerformanceDeletionOracle(
                source_key=source_key,
                base_doc_id=base_entries[source_key].document.doc_id,
                base_revision_id=base_entries[source_key].revision_id,
            )
            for source_key in categories.deletes
        ),
    )
    query_descriptor = PerformanceQueryDescriptor(
        cases=_query_cases(
            categories=categories,
            base_entries=base_entries,
            target_entries=target_entries,
        )
    )
    payloads = {
        "base_catalog.json": canonical_revision_catalog_bytes(base_catalog),
        "base_documents.json": _canonical_json_bytes(base_payload),
        "change_descriptor.json": _canonical_json_bytes(change_descriptor),
        "query_descriptor.json": _canonical_json_bytes(query_descriptor),
        "target_catalog.json": canonical_revision_catalog_bytes(target_catalog),
        "target_documents.json": _canonical_json_bytes(target_payload),
    }
    counts = PerformanceBundleCounts(
        base_document_count=len(base_entries),
        target_live_document_count=len(target_entries),
        base_event_count=len(base_catalog.ledger.receipts),
        target_event_count=len(target_catalog.ledger.receipts),
        content_update_count=len(categories.content_updates),
        acl_only_count=len(categories.acl_only_updates),
        delete_count=len(categories.deletes),
        unchanged_count=len(categories.unchanged),
        query_count=len(query_descriptor.cases),
    )
    manifest = PerformanceBundleManifest(
        generator=PerformanceGeneratorIdentity(
            implementation_sha256=_implementation_sha256()
        ),
        pipeline=PerformancePipelineIdentity(parser=_parser_fingerprint()),
        counts=counts,
        files=tuple(
            PerformanceBundleFile(
                path=path,
                byte_count=len(content),
                sha256=_sha256(content),
            )
            for path, content in sorted(payloads.items())
        ),
    )
    return payloads, manifest


def _write_file(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_CREAT
        | os.O_EXCL
        | os.O_WRONLY
        | getattr(os, "O_BINARY", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _prepare_destination(target: Path) -> None:
    if target.exists():
        metadata = target.lstat()
        if (
            stat_is_redirect(metadata)
            or not stat.S_ISDIR(metadata.st_mode)
            or any(target.iterdir())
        ):
            raise PerformanceBundleError(
                "bundle_target_exists",
                "The performance bundle target already exists and is non-empty.",
            )
        target.rmdir()


def generate_performance_bundle(
    documents: Sequence[DocumentRecord],
    target: Path,
    *,
    content_update_count: int = 31,
    acl_only_count: int = 20,
    delete_count: int = 10,
) -> LoadedPerformanceBundle:
    target = Path(target)
    if not target.is_absolute():
        raise ValueError("performance bundle target must be absolute")
    if absolute_path_has_redirect(target.parent):
        raise PerformanceBundleError(
            "bundle_target_unsafe",
            "The performance bundle target path contains a redirect.",
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    if absolute_path_has_redirect(target.parent):
        raise PerformanceBundleError(
            "bundle_target_unsafe",
            "The performance bundle target path contains a redirect.",
        )
    _prepare_destination(target)
    payloads, manifest = _serialize_bundle(
        documents,
        content_update_count=content_update_count,
        acl_only_count=acl_only_count,
        delete_count=delete_count,
    )
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{target.name}.staging-",
            dir=target.parent,
        )
    )
    published = False
    try:
        for path, content in sorted(payloads.items()):
            _write_file(stage / path, content)
        _write_file(
            stage / _MANIFEST_FILE,
            canonical_performance_bundle_manifest_bytes(manifest),
        )
        atomic_directory_move(stage, target)
        published = True
    except FileExistsError as exc:
        raise PerformanceBundleError(
            "bundle_target_exists",
            "The performance bundle target appeared during publication.",
        ) from exc
    except PerformanceBundleError:
        raise
    except OSError as exc:
        raise PerformanceBundleError(
            "bundle_publish_failed",
            "The performance bundle could not be published atomically.",
        ) from exc
    finally:
        if not published and stage.exists():
            shutil.rmtree(stage)
    return load_performance_bundle(target)


def _safe_root(root: Path) -> Path:
    try:
        if not root.is_absolute() or absolute_path_has_redirect(root):
            raise PerformanceBundleError(
                "bundle_root_unsafe",
                "The performance bundle root path contains a redirect.",
            )
        metadata = root.lstat()
        if stat_is_redirect(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise PerformanceBundleError(
                "bundle_root_unsafe",
                "The performance bundle root is not a regular directory.",
            )
        return root.resolve(strict=True)
    except PerformanceBundleError:
        raise
    except OSError as exc:
        raise PerformanceBundleError(
            "bundle_root_unavailable",
            "The performance bundle root is unavailable.",
        ) from exc


def _read_regular_file(path: Path, *, byte_limit: int) -> bytes:
    descriptor: int | None = None
    try:
        expected = path.lstat()
        if stat_is_redirect(expected):
            raise PerformanceBundleError(
                "bundle_file_unsafe",
                "A performance bundle file is a redirect.",
            )
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        current = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or current.st_nlink != 1
            or not os.path.samestat(expected, opened)
            or not os.path.samestat(opened, current)
            or opened.st_size > byte_limit
        ):
            raise PerformanceBundleError(
                "bundle_file_unsafe",
                "A performance bundle file is not a bounded regular file.",
            )
        chunks: list[bytes] = []
        remaining = byte_limit + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(content) > byte_limit
            or len(content) != opened.st_size
            or not os.path.samestat(opened, after)
            or opened.st_size != after.st_size
            or getattr(opened, "st_mtime_ns", None)
            != getattr(after, "st_mtime_ns", None)
        ):
            raise PerformanceBundleError(
                "bundle_file_changed",
                "A performance bundle file changed while being read.",
            )
        return content
    except PerformanceBundleError:
        raise
    except OSError as exc:
        raise PerformanceBundleError(
            "bundle_file_unavailable",
            "A performance bundle file is unavailable.",
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _parse_canonical(
    raw: bytes,
    model_type: type[PerformanceBundleModel],
    *,
    code: str,
) -> PerformanceBundleModel:
    try:
        model = model_type.model_validate_json(raw)
    except Exception as exc:
        raise PerformanceBundleError(
            code,
            "A performance bundle JSON file failed strict schema validation.",
        ) from exc
    if raw != _canonical_json_bytes(model):
        raise PerformanceBundleError(
            "bundle_json_noncanonical",
            "A performance bundle JSON file is not canonical.",
        )
    return model


@dataclass(frozen=True)
class LoadedPerformanceBundle:
    root: Path
    manifest: PerformanceBundleManifest
    manifest_sha256: str
    base_documents: PerformanceDocumentPayload
    target_documents: PerformanceDocumentPayload
    base_catalog: RevisionCatalogSnapshot
    target_catalog: RevisionCatalogSnapshot
    change_descriptor: PerformanceChangeDescriptor
    query_descriptor: PerformanceQueryDescriptor


class PerformanceBundleRevisionContentMaterializer:
    def __init__(
        self,
        bundle: LoadedPerformanceBundle,
        *,
        role: Literal["base", "target"],
    ) -> None:
        self._bundle = bundle
        self._role = role
        payload = (
            bundle.base_documents
            if role == "base"
            else bundle.target_documents
        )
        catalog = (
            bundle.base_catalog
            if role == "base"
            else bundle.target_catalog
        )
        self._entries = {
            entry.revision_id: entry for entry in payload.entries
        }
        self._revisions = {
            revision.revision_id: revision
            for revision in catalog.revisions
        }

    def _entry(
        self,
        revision: DocumentRevision,
    ) -> PerformanceRevisionPayload:
        validated = DocumentRevision.model_validate(
            revision.model_dump(mode="json")
        )
        persisted = self._revisions.get(validated.revision_id)
        entry = self._entries.get(validated.revision_id)
        if persisted != validated or entry is None or validated.deleted:
            raise ValueError(
                f"revision is not a live {self._role} bundle payload"
            )
        return entry

    def parser_fingerprint(
        self,
        revision: DocumentRevision,
    ) -> ComponentFingerprint:
        self._entry(revision)
        materialization = revision.materialization
        if materialization is None:
            raise ValueError("live bundle revision is not materialized")
        template = self._bundle.manifest.pipeline.parser
        return template.model_copy(
            update={
                "name": materialization.parser_name,
                "semantic_version": materialization.parser_version,
            },
            deep=True,
        )

    def parse_content(
        self,
        revision: DocumentRevision,
    ) -> ParsedContentArtifact:
        return self._entry(revision).parsed.model_copy(deep=True)

    def normalize_content(
        self,
        revision: DocumentRevision,
        parsed: ParsedContentArtifact,
    ) -> NormalizedContentArtifact:
        entry = self._entry(revision)
        validated = ParsedContentArtifact.model_validate(
            parsed.model_dump(mode="json")
        )
        if validated != entry.parsed:
            raise ValueError("parsed artifact does not match the bundle revision")
        return entry.normalized.model_copy(deep=True)

    def materialize_document(
        self,
        revision: DocumentRevision,
        normalized: NormalizedContentArtifact,
    ) -> DocumentRecord:
        entry = self._entry(revision)
        validated = NormalizedContentArtifact.model_validate(
            normalized.model_dump(mode="json")
        )
        if validated != entry.normalized:
            raise ValueError(
                "normalized artifact does not match the bundle revision"
            )
        return entry.document.model_copy(deep=True)


def _live_revisions(
    catalog: RevisionCatalogSnapshot,
) -> dict[str, DocumentRevision]:
    revisions = {
        revision.revision_id: revision for revision in catalog.revisions
    }
    return {
        head.source_key: revisions[head.current_revision_id]
        for head in catalog.ledger.source_heads
        if not head.deleted
    }


def _payload_entries(
    payload: PerformanceDocumentPayload,
) -> dict[str, PerformanceRevisionPayload]:
    return {entry.source_key: entry for entry in payload.entries}


def _validate_payload_catalog_binding(
    payload: PerformanceDocumentPayload,
    catalog: RevisionCatalogSnapshot,
) -> None:
    entries = _payload_entries(payload)
    live = _live_revisions(catalog)
    if set(entries) != set(live):
        raise PerformanceBundleError(
            "bundle_payload_catalog_mismatch",
            "Document payloads do not cover the exact live catalog heads.",
        )
    for source_key, revision in live.items():
        entry = entries[source_key]
        materialization = revision.materialization
        document = entry.document
        if (
            not isinstance(materialization, RevisionMaterializationV2)
            or entry.source_system != revision.source_system
            or entry.revision_id != revision.revision_id
            or document.doc_id != materialization.document_id
            or document.tenant_id != revision.tenant_id
            or document.region != revision.region
            or tuple(document.acl_groups) != revision.acl_groups
            or document.ingested_at != revision.occurred_at
            or document.checksum != revision.content_sha256
            or document.normalized_text_hash
            != materialization.normalized_sha256
            or document.parser_name != materialization.parser_name
            or document.parser_version != materialization.parser_version
            or _projection(document) != materialization.document_projection
            or materialization.parent_event_id != revision.event_id
            or materialization.content_sha256 != revision.content_sha256
        ):
            raise PerformanceBundleError(
                "bundle_payload_catalog_mismatch",
                "A document payload does not match its governed revision.",
            )


def _replay_catalogs(
    *,
    base_catalog: RevisionCatalogSnapshot,
    target_catalog: RevisionCatalogSnapshot,
    base_entries: Mapping[str, PerformanceRevisionPayload],
    target_entries: Mapping[str, PerformanceRevisionPayload],
    descriptor: PerformanceChangeDescriptor,
) -> None:
    try:
        base_revisions = {
            revision.revision_id: revision
            for revision in base_catalog.revisions
        }
        base_batch: list[
            tuple[SourceEvent, RevisionMaterializationV2 | None]
        ] = []
        for event in descriptor.base_events:
            entry = base_entries.get(event.source_key)
            if entry is None:
                raise ValueError("base event has no document payload")
            materialization = base_revisions[entry.revision_id].materialization
            if not isinstance(materialization, RevisionMaterializationV2):
                raise ValueError("base event materialization is not v2")
            base_batch.append((event, materialization))
        replayed_base = _apply_catalog_batch_linear(
            empty_revision_catalog_snapshot(),
            base_batch,
        )
        if replayed_base != base_catalog:
            raise ValueError("base catalog replay differs")

        target_revisions = {
            revision.revision_id: revision
            for revision in target_catalog.revisions
        }
        change_batch: list[
            tuple[SourceEvent, RevisionMaterializationV2 | None]
        ] = []
        for event in descriptor.change_events:
            materialization = None
            if event.operation == "UPSERT":
                entry = target_entries.get(event.source_key)
                if entry is None:
                    raise ValueError("target UPSERT has no document payload")
                candidate = target_revisions[entry.revision_id].materialization
                if not isinstance(candidate, RevisionMaterializationV2):
                    raise ValueError("target event materialization is not v2")
                materialization = candidate
            change_batch.append((event, materialization))
        replayed_target = _apply_catalog_batch_linear(
            replayed_base,
            change_batch,
        )
        if replayed_target != target_catalog:
            raise ValueError("target catalog replay differs")
    except Exception as exc:
        raise PerformanceBundleError(
            "bundle_event_replay_invalid",
            "Canonical SourceEvents do not reproduce the bound catalogs.",
        ) from exc


def _validate_change_semantics(
    *,
    base_entries: Mapping[str, PerformanceRevisionPayload],
    target_entries: Mapping[str, PerformanceRevisionPayload],
    target_catalog: RevisionCatalogSnapshot,
    descriptor: PerformanceChangeDescriptor,
    queries: PerformanceQueryDescriptor,
) -> None:
    categories = descriptor.categories
    all_sources = {
        *categories.content_updates,
        *categories.acl_only_updates,
        *categories.deletes,
        *categories.unchanged,
    }
    changed_sources = {
        *categories.content_updates,
        *categories.acl_only_updates,
        *categories.deletes,
    }
    event_sources = {event.source_key for event in descriptor.change_events}
    if set(base_entries) != all_sources or event_sources != changed_sources:
        raise PerformanceBundleError(
            "bundle_category_mismatch",
            "Change categories do not cover the exact event source sets.",
        )

    target_heads = {
        head.source_key: head for head in target_catalog.ledger.source_heads
    }
    for source_key in categories.content_updates:
        base = base_entries[source_key]
        target = target_entries.get(source_key)
        if (
            target is None
            or target.document.checksum == base.document.checksum
            or target.normalized == base.normalized
        ):
            raise PerformanceBundleError(
                "bundle_category_mismatch",
                "A content update does not change its content payload.",
            )
    for source_key in categories.acl_only_updates:
        base = base_entries[source_key]
        target = target_entries.get(source_key)
        if (
            target is None
            or target.document.acl_groups == base.document.acl_groups
            or target.document.checksum != base.document.checksum
            or target.parsed != base.parsed
            or target.normalized != base.normalized
        ):
            raise PerformanceBundleError(
                "bundle_category_mismatch",
                "An ACL-only update changes content or preserves its old ACL.",
            )
    for source_key in categories.deletes:
        if (
            source_key in target_entries
            or source_key not in target_heads
            or not target_heads[source_key].deleted
        ):
            raise PerformanceBundleError(
                "bundle_category_mismatch",
                "A delete category does not resolve to an exact tombstone.",
            )
    for oracle in descriptor.deletion_oracles:
        base = base_entries.get(oracle.source_key)
        if (
            base is None
            or oracle.base_doc_id != base.document.doc_id
            or oracle.base_revision_id != base.revision_id
        ):
            raise PerformanceBundleError(
                "bundle_deletion_oracle_invalid",
                "A deletion oracle does not bind the exact base payload.",
            )
    for source_key in categories.unchanged:
        if target_entries.get(source_key) != base_entries[source_key]:
            raise PerformanceBundleError(
                "bundle_category_mismatch",
                "An unchanged source differs between base and target payloads.",
            )

    category_sources = {
        "content_update": set(categories.content_updates),
        "acl_only": set(categories.acl_only_updates),
        "delete": set(categories.deletes),
        "unchanged": set(categories.unchanged),
    }
    for case in queries.cases:
        entry = (
            base_entries.get(case.expected_source_key)
            if case.category == "delete"
            else target_entries.get(case.expected_source_key)
        )
        if entry is None:
            raise PerformanceBundleError(
                "bundle_query_binding_invalid",
                "A fixed query has no bound document payload.",
            )
        oracle_token = _retrieval_oracle_token(case.expected_source_key)
        user = case.request.user
        if case.denial_dimension == "none":
            user_binding_valid = (
                user.tenant_id == entry.document.tenant_id
                and user.region == entry.document.region
                and user.groups == entry.document.acl_groups
            )
        elif case.denial_dimension == "removed_group":
            base_entry = base_entries.get(case.expected_source_key)
            user_binding_valid = (
                base_entry is not None
                and user.tenant_id == entry.document.tenant_id
                and user.region == entry.document.region
                and not set(user.groups).intersection(
                    entry.document.acl_groups
                )
                and set(user.groups)
                == (
                    set(base_entry.document.acl_groups)
                    - set(entry.document.acl_groups)
                )
            )
        elif case.denial_dimension == "tenant":
            user_binding_valid = (
                user.tenant_id != entry.document.tenant_id
                and user.region == entry.document.region
                and user.groups == entry.document.acl_groups
            )
        else:
            user_binding_valid = (
                user.tenant_id == entry.document.tenant_id
                and user.region != entry.document.region
                and user.groups == entry.document.acl_groups
            )
        if (
            case.expected_source_key not in category_sources[case.category]
            or case.expected_doc_id != entry.document.doc_id
            or case.request.mode != "bm25"
            or oracle_token not in case.request.query.split()
            or oracle_token not in entry.document.text.split()
            or not user_binding_valid
            or case.request.filters.departments
            != [entry.document.department]
            or case.request.filters.policy_ids
            != (
                [entry.document.policy_id]
                if entry.document.policy_id is not None
                else []
            )
            or case.request.filters.statuses
            != [entry.document.document_version.status]
            or case.request.filters.temporal_scope != "all"
            or (
                case.category == "delete"
                and case.expected_source_key in target_entries
            )
        ):
            raise PerformanceBundleError(
                "bundle_query_binding_invalid",
                "A fixed query is not bound to its declared live category.",
            )


def load_performance_bundle(root: Path) -> LoadedPerformanceBundle:
    resolved = _safe_root(Path(root))
    manifest_raw = _read_regular_file(
        resolved / _MANIFEST_FILE,
        byte_limit=_MAX_MANIFEST_BYTES,
    )
    manifest = _parse_canonical(
        manifest_raw,
        PerformanceBundleManifest,
        code="bundle_manifest_invalid",
    )
    assert isinstance(manifest, PerformanceBundleManifest)
    expected_generator = PerformanceGeneratorIdentity(
        implementation_sha256=_implementation_sha256()
    )
    expected_pipeline = PerformancePipelineIdentity(
        parser=_parser_fingerprint()
    )
    if (
        manifest.generator != expected_generator
        or manifest.pipeline != expected_pipeline
    ):
        raise PerformanceBundleError(
            "bundle_identity_mismatch",
            "The performance bundle generator or pipeline identity is not current.",
        )
    observed_names = {
        entry.name
        for entry in resolved.iterdir()
    }
    expected_names = {*_EXPECTED_FILES, _MANIFEST_FILE}
    if observed_names != expected_names:
        raise PerformanceBundleError(
            "bundle_file_set_invalid",
            "The performance bundle has missing or extra entries.",
        )

    raw_files: dict[str, bytes] = {}
    for item in manifest.files:
        limit = (
            _MAX_PAYLOAD_BYTES
            if item.path.endswith("documents.json")
            else _MAX_DESCRIPTOR_BYTES
        )
        raw = _read_regular_file(resolved / item.path, byte_limit=limit)
        if len(raw) != item.byte_count or _sha256(raw) != item.sha256:
            raise PerformanceBundleError(
                "bundle_file_integrity_failed",
                "A performance bundle file does not match its manifest.",
            )
        raw_files[item.path] = raw

    base_documents = _parse_canonical(
        raw_files["base_documents.json"],
        PerformanceDocumentPayload,
        code="bundle_base_documents_invalid",
    )
    target_documents = _parse_canonical(
        raw_files["target_documents.json"],
        PerformanceDocumentPayload,
        code="bundle_target_documents_invalid",
    )
    change_descriptor = _parse_canonical(
        raw_files["change_descriptor.json"],
        PerformanceChangeDescriptor,
        code="bundle_change_descriptor_invalid",
    )
    query_descriptor = _parse_canonical(
        raw_files["query_descriptor.json"],
        PerformanceQueryDescriptor,
        code="bundle_query_descriptor_invalid",
    )
    assert isinstance(base_documents, PerformanceDocumentPayload)
    assert isinstance(target_documents, PerformanceDocumentPayload)
    assert isinstance(change_descriptor, PerformanceChangeDescriptor)
    assert isinstance(query_descriptor, PerformanceQueryDescriptor)
    try:
        base_catalog = RevisionCatalogSnapshot.model_validate_json(
            raw_files["base_catalog.json"]
        )
        target_catalog = RevisionCatalogSnapshot.model_validate_json(
            raw_files["target_catalog.json"]
        )
    except Exception as exc:
        raise PerformanceBundleError(
            "bundle_catalog_invalid",
            "A performance bundle catalog failed strict validation.",
        ) from exc
    if (
        raw_files["base_catalog.json"]
        != canonical_revision_catalog_bytes(base_catalog)
        or raw_files["target_catalog.json"]
        != canonical_revision_catalog_bytes(target_catalog)
    ):
        raise PerformanceBundleError(
            "bundle_json_noncanonical",
            "A performance bundle catalog is not canonical.",
        )
    if base_documents.role != "base" or target_documents.role != "target":
        raise PerformanceBundleError(
            "bundle_payload_role_invalid",
            "A performance bundle document payload has the wrong role.",
        )
    if (
        change_descriptor.base_catalog_sha256
        != revision_catalog_sha256(base_catalog)
        or change_descriptor.target_catalog_sha256
        != revision_catalog_sha256(target_catalog)
    ):
        raise PerformanceBundleError(
            "bundle_catalog_binding_invalid",
            "The change descriptor does not bind the exact catalogs.",
        )
    counts = manifest.counts
    categories = change_descriptor.categories
    observed_counts = (
        len(base_documents.entries),
        len(target_documents.entries),
        len(base_catalog.ledger.receipts),
        len(target_catalog.ledger.receipts),
        len(categories.content_updates),
        len(categories.acl_only_updates),
        len(categories.deletes),
        len(categories.unchanged),
        len(query_descriptor.cases),
    )
    expected_counts = (
        counts.base_document_count,
        counts.target_live_document_count,
        counts.base_event_count,
        counts.target_event_count,
        counts.content_update_count,
        counts.acl_only_count,
        counts.delete_count,
        counts.unchanged_count,
        counts.query_count,
    )
    if observed_counts != expected_counts:
        raise PerformanceBundleError(
            "bundle_count_mismatch",
            "The performance bundle counts do not match its payloads.",
        )
    _validate_payload_catalog_binding(base_documents, base_catalog)
    _validate_payload_catalog_binding(target_documents, target_catalog)
    base_entries = _payload_entries(base_documents)
    target_entries = _payload_entries(target_documents)
    _replay_catalogs(
        base_catalog=base_catalog,
        target_catalog=target_catalog,
        base_entries=base_entries,
        target_entries=target_entries,
        descriptor=change_descriptor,
    )
    _validate_change_semantics(
        base_entries=base_entries,
        target_entries=target_entries,
        target_catalog=target_catalog,
        descriptor=change_descriptor,
        queries=query_descriptor,
    )
    return LoadedPerformanceBundle(
        root=resolved,
        manifest=manifest,
        manifest_sha256=_sha256(manifest_raw),
        base_documents=base_documents,
        target_documents=target_documents,
        base_catalog=base_catalog,
        target_catalog=target_catalog,
        change_descriptor=change_descriptor,
        query_descriptor=query_descriptor,
    )


__all__ = [
    "LoadedPerformanceBundle",
    "PerformanceBundleError",
    "PerformanceBundleManifest",
    "PerformanceBundleRevisionContentMaterializer",
    "PerformanceChangeDescriptor",
    "PerformanceDocumentPayload",
    "PerformanceQueryDescriptor",
    "canonical_performance_bundle_manifest_bytes",
    "generate_performance_bundle",
    "load_performance_bundle",
]
