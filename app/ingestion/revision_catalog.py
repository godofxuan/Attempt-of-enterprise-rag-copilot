from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.domain.documents import DocumentVersion
from app.ingestion.path_security import absolute_path_has_redirect, stat_is_redirect
from app.ingestion.source_events import (
    SourceEvent,
    SourceEventApplication,
    SourceEventLedger,
    SourceEventLedgerSnapshot,
    SourceEventReceipt,
)
from app.security.private_fs import (
    PrivatePathError,
    capture_private_directory_identity,
    harden_private_directory,
    hold_private_directory,
    private_directory_identity_is_current,
    private_directory_permissions_are_secure,
    replace_private_file,
    sync_directory as sync_private_directory,
)


_CATALOG_FILE = "catalog.json"
_ANCHOR_FILE = "catalog.anchor.json"
_LOCK_FILE = ".catalog.lock"
_TEMP_PATTERN = re.compile(
    r"^\.(?:catalog\.json|catalog\.anchor\.json)\.tmp-[0-9a-f]{16}$"
)
_DEFAULT_MAX_CATALOG_BYTES = 64 * 1024 * 1024
_LOCK_POLL_SECONDS = 0.02


class RevisionCatalogModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


def _has_control_character(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


class RevisionMaterialization(RevisionCatalogModel):
    schema_version: Literal["revision_materialization_v1"] = (
        "revision_materialization_v1"
    )
    document_id: str = Field(min_length=1, max_length=256)
    asset_id: str = Field(pattern=r"^asset_[0-9a-f]{32}$")
    parent_event_id: str = Field(min_length=1, max_length=128)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_name: str = Field(min_length=1, max_length=128)
    parser_version: str = Field(min_length=1, max_length=64)
    normalizer_version: str = Field(min_length=1, max_length=64)

    @field_validator(
        "document_id",
        "asset_id",
        "parent_event_id",
        "parser_name",
        "parser_version",
        "normalizer_version",
    )
    @classmethod
    def validate_printable_identifiers(cls, value: str) -> str:
        if _has_control_character(value):
            raise ValueError(
                "revision materialization identifiers must be printable"
            )
        return value


class DocumentProjection(RevisionCatalogModel):
    schema_version: Literal["document_projection_v1"] = "document_projection_v1"
    source_type: str = Field(min_length=1, max_length=128)
    source_path: str = Field(min_length=1, max_length=512)
    format: str = Field(min_length=1, max_length=64)
    department: str = Field(min_length=1, max_length=128)
    filed_department: str = Field(min_length=1, max_length=128)
    project_id: str | None = Field(default=None, max_length=128)
    policy_id: str | None = Field(default=None, max_length=128)
    document_version: DocumentVersion
    authority_level: int = Field(ge=1, le=100)
    fact_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=1000)
    variant: str = Field(min_length=1, max_length=64)
    duplicate_of: str | None = Field(default=None, max_length=256)

    @field_validator(
        "source_type",
        "source_path",
        "format",
        "department",
        "filed_department",
        "project_id",
        "policy_id",
        "variant",
        "duplicate_of",
    )
    @classmethod
    def validate_printable_projection_values(
        cls,
        value: str | None,
    ) -> str | None:
        if value is not None and _has_control_character(value):
            raise ValueError("document projection values must be printable")
        return value

    @field_validator("fact_ids")
    @classmethod
    def validate_fact_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if (
            values != tuple(sorted(values))
            or len(values) != len(set(values))
            or any(
                not value
                or len(value) > 256
                or _has_control_character(value)
                for value in values
            )
        ):
            raise ValueError("document projection fact IDs must be canonical")
        return values

    @model_validator(mode="after")
    def validate_authority(self) -> DocumentProjection:
        if self.authority_level != self.document_version.authority_level:
            raise ValueError(
                "document projection authority must match its version"
            )
        return self

    def canonical_sha256(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class RevisionMaterializationV2(RevisionCatalogModel):
    schema_version: Literal["revision_materialization_v2"] = (
        "revision_materialization_v2"
    )
    document_id: str = Field(min_length=1, max_length=256)
    asset_id: str = Field(pattern=r"^asset_[0-9a-f]{32}$")
    parent_event_id: str = Field(min_length=1, max_length=128)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_name: str = Field(min_length=1, max_length=128)
    parser_version: str = Field(min_length=1, max_length=64)
    normalizer_version: str = Field(min_length=1, max_length=64)
    document_projection: DocumentProjection

    @field_validator(
        "document_id",
        "asset_id",
        "parent_event_id",
        "parser_name",
        "parser_version",
        "normalizer_version",
    )
    @classmethod
    def validate_printable_identifiers(cls, value: str) -> str:
        if _has_control_character(value):
            raise ValueError(
                "revision materialization identifiers must be printable"
            )
        return value


RevisionMaterializationRecord = RevisionMaterialization | RevisionMaterializationV2


def _validate_revision_materialization(
    materialization: RevisionMaterializationRecord,
) -> RevisionMaterializationRecord:
    if isinstance(materialization, RevisionMaterializationV2):
        return RevisionMaterializationV2.model_validate(
            materialization.model_dump(mode="json")
        )
    return RevisionMaterialization.model_validate(
        materialization.model_dump(mode="json")
    )


class DocumentRevision(RevisionCatalogModel):
    schema_version: Literal["document_revision_v1"] = "document_revision_v1"
    revision_id: str = Field(pattern=r"^rev_[0-9a-f]{64}$")
    previous_revision_id: str | None = Field(
        default=None,
        pattern=r"^rev_[0-9a-f]{64}$",
    )
    event_id: str = Field(min_length=1, max_length=128)
    event_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    operation: Literal["UPSERT", "DELETE"]
    source_system: str = Field(min_length=1, max_length=128)
    source_key: str = Field(min_length=1, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=128)
    region: str = Field(min_length=1, max_length=64)
    acl_groups: tuple[str, ...] = Field(min_length=1, max_length=100)
    actor_pseudonym: str = Field(min_length=1, max_length=128)
    occurred_at: datetime
    declared_media_type: str | None = Field(default=None, max_length=128)
    content_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    materialization: RevisionMaterializationRecord | None = None
    deleted: bool

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("revision occurred_at must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator(
        "event_id",
        "source_system",
        "source_key",
        "tenant_id",
        "region",
        "actor_pseudonym",
    )
    @classmethod
    def validate_printable_identifiers(cls, value: str) -> str:
        if _has_control_character(value):
            raise ValueError("revision identifiers must be printable")
        return value

    @field_validator("acl_groups")
    @classmethod
    def validate_acl_groups(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if (
            not values
            or len(values) != len(set(values))
            or values != tuple(sorted(values))
            or any(
                not value
                or len(value) > 128
                or _has_control_character(value)
                for value in values
            )
        ):
            raise ValueError(
                "revision ACL groups must be non-empty, unique, and canonical"
            )
        return values

    @model_validator(mode="after")
    def validate_revision_shape(self) -> DocumentRevision:
        if self.revision_id != f"rev_{self.event_payload_sha256}":
            raise ValueError("revision ID must bind the event payload SHA-256")
        if self.previous_revision_id == self.revision_id:
            raise ValueError("revision cannot reference itself")
        if self.deleted != (self.operation == "DELETE"):
            raise ValueError("revision deleted state must match operation")
        if self.operation == "UPSERT":
            if (
                self.content_sha256 is None
                or self.declared_media_type is None
                or self.materialization is None
            ):
                raise ValueError(
                    "UPSERT revision requires content, media type, and "
                    "materialization"
                )
            if self.materialization.content_sha256 != self.content_sha256:
                raise ValueError(
                    "revision materialization content hash does not match"
                )
        elif (
            self.content_sha256 is not None
            or self.declared_media_type is not None
            or self.materialization is not None
        ):
            raise ValueError("DELETE tombstone must not retain content fields")
        return self


class RevisionCatalogSnapshot(RevisionCatalogModel):
    schema_version: Literal["revision_catalog_snapshot_v1"] = (
        "revision_catalog_snapshot_v1"
    )
    ledger: SourceEventLedgerSnapshot = Field(
        default_factory=SourceEventLedgerSnapshot
    )
    revisions: tuple[DocumentRevision, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_catalog_state(self) -> RevisionCatalogSnapshot:
        revision_ids = [revision.revision_id for revision in self.revisions]
        if len(revision_ids) != len(set(revision_ids)):
            raise ValueError("catalog revision IDs must be unique")
        if revision_ids != sorted(revision_ids):
            raise ValueError("catalog revisions must use canonical revision-ID order")

        receipts_by_revision = {
            receipt.resulting_revision_id: receipt
            for receipt in self.ledger.receipts
        }
        revisions_by_id = {
            revision.revision_id: revision for revision in self.revisions
        }
        if set(receipts_by_revision) != set(revisions_by_id):
            raise ValueError(
                "catalog must contain exactly one revision per event receipt"
            )

        for revision_id, receipt in receipts_by_revision.items():
            revision = revisions_by_id[revision_id]
            if (
                revision.event_id != receipt.event_id
                or revision.event_payload_sha256 != receipt.payload_sha256
                or revision.operation != receipt.operation
                or revision.source_system != receipt.source_system
                or revision.source_key != receipt.source_key
                or revision.tenant_id != receipt.tenant_id
                or revision.region != receipt.region
                or revision.actor_pseudonym != receipt.actor_pseudonym
                or revision.occurred_at != receipt.occurred_at
                or revision.previous_revision_id
                != receipt.previous_revision_id
                or revision.deleted != receipt.deleted
            ):
                raise ValueError("catalog revision does not match its event receipt")
            if revision.previous_revision_id is None:
                if revision.operation != "UPSERT":
                    raise ValueError(
                        "catalog source lineage root must be an UPSERT revision"
                    )
            else:
                previous = revisions_by_id.get(revision.previous_revision_id)
                if previous is None or (
                    previous.source_system,
                    previous.source_key,
                    previous.tenant_id,
                ) != (
                    revision.source_system,
                    revision.source_key,
                    revision.tenant_id,
                ):
                    raise ValueError(
                        "catalog revision previous link is not in its source lineage"
                    )
                if revision.deleted:
                    if previous.deleted:
                        raise ValueError(
                            "catalog DELETE must follow a live revision"
                        )
                    if (
                        revision.region != previous.region
                        or revision.acl_groups != previous.acl_groups
                    ):
                        raise ValueError(
                            "catalog tombstone must inherit previous governance"
                        )

        for head in self.ledger.source_heads:
            revision = revisions_by_id.get(head.current_revision_id)
            if revision is None or (
                revision.source_system,
                revision.source_key,
                revision.tenant_id,
                revision.region,
                revision.acl_groups,
                revision.deleted,
            ) != (
                head.source_system,
                head.source_key,
                head.tenant_id,
                head.region,
                head.acl_groups,
                head.deleted,
            ):
                raise ValueError(
                    "catalog source head does not match its current revision"
                )
        return self


def empty_revision_catalog_snapshot() -> RevisionCatalogSnapshot:
    return RevisionCatalogSnapshot()


def canonical_revision_catalog_bytes(snapshot: RevisionCatalogSnapshot) -> bytes:
    validated = RevisionCatalogSnapshot.model_validate(
        snapshot.model_dump(mode="json")
    )
    return json.dumps(
        validated.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def revision_catalog_sha256(snapshot: RevisionCatalogSnapshot) -> str:
    return hashlib.sha256(canonical_revision_catalog_bytes(snapshot)).hexdigest()


class RevisionCatalogEnvelope(RevisionCatalogModel):
    schema_version: Literal["revision_catalog_file_v1"] = (
        "revision_catalog_file_v1"
    )
    generation: int = Field(ge=1)
    previous_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot: RevisionCatalogSnapshot

    @model_validator(mode="after")
    def validate_snapshot_checksum(self) -> RevisionCatalogEnvelope:
        if self.generation != len(self.snapshot.ledger.receipts):
            raise ValueError(
                "catalog generation must match the accepted event count"
            )
        if revision_catalog_sha256(self.snapshot) != self.snapshot_sha256:
            raise ValueError("catalog snapshot checksum mismatch")
        return self


def canonical_revision_catalog_envelope_bytes(
    envelope: RevisionCatalogEnvelope,
) -> bytes:
    validated = RevisionCatalogEnvelope.model_validate(
        envelope.model_dump(mode="json")
    )
    return json.dumps(
        validated.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


class RevisionCatalogAnchor(RevisionCatalogModel):
    schema_version: Literal["revision_catalog_anchor_v1"] = (
        "revision_catalog_anchor_v1"
    )
    generation: int = Field(ge=1)
    previous_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def canonical_revision_catalog_anchor_bytes(
    anchor: RevisionCatalogAnchor,
) -> bytes:
    validated = RevisionCatalogAnchor.model_validate(
        anchor.model_dump(mode="json")
    )
    return json.dumps(
        validated.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


class CatalogApplication(RevisionCatalogModel):
    status: Literal["APPLIED", "REPLAYED"]
    receipt: SourceEventReceipt
    revision: DocumentRevision
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CatalogTransition(RevisionCatalogModel):
    application: CatalogApplication
    snapshot: RevisionCatalogSnapshot


class CatalogConflict(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class CatalogStorageError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def apply_revision_catalog_snapshot(
    base: RevisionCatalogSnapshot,
    event: SourceEvent,
    *,
    materialization: RevisionMaterializationRecord | None = None,
) -> CatalogTransition:
    validated_base = RevisionCatalogSnapshot.model_validate(
        base.model_dump(mode="json")
    )
    validated_event = SourceEvent.model_validate(
        event.model_dump(mode="json")
    )
    validated_materialization = (
        None
        if materialization is None
        else _validate_revision_materialization(materialization)
    )
    _validate_materialization_request(
        validated_event,
        validated_materialization,
    )

    ledger = SourceEventLedger.from_snapshot(validated_base.ledger)
    source_application = ledger.apply(validated_event)
    existing = {
        revision.revision_id: revision
        for revision in validated_base.revisions
    }.get(source_application.receipt.resulting_revision_id)

    if source_application.status == "REPLAYED":
        if existing is None:
            raise CatalogStorageError(
                "catalog_integrity_failed",
                "A replayed event has no persisted revision.",
            )
        if (
            validated_materialization is not None
            and existing.materialization != validated_materialization
        ):
            raise CatalogConflict(
                "revision_materialization_conflict",
                "The accepted event has different materialization provenance.",
            )
        return CatalogTransition(
            application=CatalogApplication(
                status="REPLAYED",
                receipt=source_application.receipt,
                revision=existing,
                catalog_sha256=revision_catalog_sha256(validated_base),
            ),
            snapshot=validated_base,
        )

    if validated_event.operation == "UPSERT" and validated_materialization is None:
        raise CatalogConflict(
            "materialization_required",
            "A new UPSERT requires materialization provenance.",
        )
    revision = _build_revision(
        event=validated_event,
        application=source_application,
        ledger=ledger,
        materialization=validated_materialization,
    )
    target = RevisionCatalogSnapshot(
        ledger=ledger.snapshot(),
        revisions=tuple(
            sorted(
                (*validated_base.revisions, revision),
                key=lambda item: item.revision_id,
            )
        ),
    )
    return CatalogTransition(
        application=CatalogApplication(
            status="APPLIED",
            receipt=source_application.receipt,
            revision=revision,
            catalog_sha256=revision_catalog_sha256(target),
        ),
        snapshot=target,
    )


class PersistentRevisionCatalog:
    def __init__(
        self,
        root: Path,
        *,
        max_catalog_bytes: int = _DEFAULT_MAX_CATALOG_BYTES,
        lock_timeout_seconds: float = 10.0,
    ) -> None:
        self.root = Path(root)
        if not self.root.is_absolute():
            raise CatalogStorageError(
                "catalog_root_invalid",
                "The revision catalog root must be absolute.",
            )
        if max_catalog_bytes < 128:
            raise ValueError("max_catalog_bytes must be at least 128")
        if lock_timeout_seconds <= 0:
            raise ValueError("lock_timeout_seconds must be positive")
        self.max_catalog_bytes = max_catalog_bytes
        self.lock_timeout_seconds = lock_timeout_seconds

    @property
    def catalog_path(self) -> Path:
        return self.root / _CATALOG_FILE

    @property
    def anchor_path(self) -> Path:
        return self.root / _ANCHOR_FILE

    def snapshot(self) -> RevisionCatalogSnapshot:
        with self._locked() as directory_descriptor:
            return self._load_snapshot_unlocked(directory_descriptor)

    def snapshot_read_only(self) -> RevisionCatalogSnapshot:
        return load_revision_catalog_snapshot_read_only(
            self.root,
            max_catalog_bytes=self.max_catalog_bytes,
        )

    def apply(
        self,
        event: SourceEvent,
        *,
        materialization: RevisionMaterializationRecord | None = None,
    ) -> CatalogApplication:
        validated_event = SourceEvent.model_validate(
            event.model_dump(mode="json")
        )
        validated_materialization = (
            None
            if materialization is None
            else _validate_revision_materialization(materialization)
        )
        _validate_materialization_request(
            validated_event,
            validated_materialization,
        )
        with self._locked() as directory_descriptor:
            base = self._load_snapshot_unlocked(directory_descriptor)
            transition = apply_revision_catalog_snapshot(
                base,
                validated_event,
                materialization=validated_materialization,
            )
            if transition.application.status == "REPLAYED":
                return transition.application
            self._publish_snapshot_unlocked(
                transition.snapshot,
                previous_snapshot_sha256=revision_catalog_sha256(base),
                directory_descriptor=directory_descriptor,
            )
            return transition.application

    @contextmanager
    def _locked(self) -> Iterator[int | None]:
        root_identity = self._prepare_root()
        lock_path = self.root / _LOCK_FILE
        descriptor: int | None = None
        locked = False
        try:
            with hold_private_directory(self.root) as held:
                held_identity = capture_private_directory_identity(
                    self.root,
                    held,
                )
                descriptor = _open_safe_lock_file(lock_path)
                _lock_descriptor(
                    descriptor,
                    timeout_seconds=self.lock_timeout_seconds,
                )
                locked = True
                self._assert_root_identity(root_identity)
                _assert_open_file_is_current(lock_path, descriptor)
                self._cleanup_orphan_temps_unlocked()
                yield held.descriptor
                if not private_directory_identity_is_current(
                    self.root,
                    held,
                    held_identity,
                ):
                    raise CatalogStorageError(
                        "catalog_root_changed",
                        "The revision catalog root changed during the transaction.",
                    )
                self._assert_root_identity(root_identity)
        except (CatalogConflict, CatalogStorageError):
            raise
        except PrivatePathError as exc:
            raise CatalogStorageError(
                "catalog_root_unsafe",
                "The revision catalog private directory is unsafe.",
            ) from exc
        except OSError as exc:
            raise CatalogStorageError(
                "catalog_lock_failed",
                "The revision catalog lock failed safely.",
            ) from exc
        finally:
            if descriptor is not None:
                if locked:
                    try:
                        _unlock_descriptor(descriptor)
                    except OSError:
                        pass
                os.close(descriptor)

    def _prepare_root(self) -> tuple[int, int]:
        try:
            existing = self.root
            while _lstat_optional(existing) is None and existing != existing.parent:
                existing = existing.parent
            if absolute_path_has_redirect(existing):
                raise CatalogStorageError(
                    "catalog_root_redirect",
                    "The revision catalog root is redirected.",
                )
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            metadata = self.root.lstat()
            if (
                absolute_path_has_redirect(self.root)
                or stat_is_redirect(metadata)
                or not stat.S_ISDIR(metadata.st_mode)
            ):
                raise CatalogStorageError(
                    "catalog_root_redirect",
                    "The revision catalog root is redirected.",
                )
            if not private_directory_permissions_are_secure(self.root):
                harden_private_directory(self.root)
            if not private_directory_permissions_are_secure(self.root):
                raise CatalogStorageError(
                    "catalog_root_permissions_unsafe",
                    "The revision catalog root permissions are unsafe.",
                )
            return metadata.st_dev, metadata.st_ino
        except CatalogStorageError:
            raise
        except PrivatePathError as exc:
            raise CatalogStorageError(
                "catalog_file_unsafe",
                "The revision catalog contains an unsafe filesystem entry.",
            ) from exc
        except OSError as exc:
            raise CatalogStorageError(
                "catalog_root_invalid",
                "The revision catalog root is unavailable.",
            ) from exc

    def _assert_root_identity(self, expected: tuple[int, int]) -> None:
        try:
            metadata = self.root.lstat()
            current = (metadata.st_dev, metadata.st_ino)
            redirected = (
                stat_is_redirect(metadata)
                or not stat.S_ISDIR(metadata.st_mode)
                or absolute_path_has_redirect(self.root)
            )
        except OSError as exc:
            raise CatalogStorageError(
                "catalog_root_changed",
                "The revision catalog root changed during the transaction.",
            ) from exc
        if redirected or current != expected:
            raise CatalogStorageError(
                "catalog_root_changed",
                "The revision catalog root changed during the transaction.",
            )

    def _cleanup_orphan_temps_unlocked(self) -> None:
        try:
            entries = list(self.root.iterdir())
        except OSError as exc:
            raise CatalogStorageError(
                "catalog_recovery_failed",
                "Catalog recovery could not enumerate managed files.",
            ) from exc
        for entry in entries:
            if _TEMP_PATTERN.fullmatch(entry.name) is None:
                continue
            try:
                metadata = entry.lstat()
                if (
                    stat_is_redirect(metadata)
                    or not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_nlink != 1
                ):
                    raise CatalogStorageError(
                        "catalog_temp_unsafe",
                        "A managed catalog temporary file is unsafe.",
                    )
                entry.unlink()
            except CatalogStorageError:
                raise
            except OSError as exc:
                raise CatalogStorageError(
                    "catalog_recovery_failed",
                    "Catalog recovery could not remove an owned temporary file.",
                ) from exc

    def _load_snapshot_unlocked(
        self,
        directory_descriptor: int | None,
    ) -> RevisionCatalogSnapshot:
        path = self.catalog_path
        if _lstat_optional(path) is None:
            if _lstat_optional(self.anchor_path) is not None:
                raise CatalogStorageError(
                    "catalog_missing",
                    "The initialized revision catalog is missing.",
                )
            return empty_revision_catalog_snapshot()
        raw = _read_safe_regular_file(
            path,
            byte_limit=self.max_catalog_bytes,
        )
        try:
            envelope = RevisionCatalogEnvelope.model_validate_json(raw)
        except ValidationError as exc:
            message = str(exc)
            if "checksum mismatch" in message:
                code = "catalog_integrity_failed"
            elif "schema_version" in message:
                code = "catalog_schema_unsupported"
            else:
                code = "catalog_invalid"
            raise CatalogStorageError(
                code,
                "The revision catalog failed strict validation.",
            ) from exc
        canonical = canonical_revision_catalog_envelope_bytes(envelope)
        if raw != canonical:
            raise CatalogStorageError(
                "catalog_noncanonical",
                "The revision catalog is not in canonical form.",
            )
        self._reconcile_anchor_unlocked(
            envelope,
            directory_descriptor=directory_descriptor,
        )
        return envelope.snapshot

    def _load_anchor_unlocked(self) -> RevisionCatalogAnchor | None:
        path = self.anchor_path
        if _lstat_optional(path) is None:
            return None
        raw = _read_safe_regular_file(
            path,
            byte_limit=min(self.max_catalog_bytes, 64 * 1024),
        )
        try:
            anchor = RevisionCatalogAnchor.model_validate_json(raw)
        except ValidationError as exc:
            raise CatalogStorageError(
                "catalog_anchor_invalid",
                "The revision catalog anchor failed strict validation.",
            ) from exc
        if raw != canonical_revision_catalog_anchor_bytes(anchor):
            raise CatalogStorageError(
                "catalog_anchor_noncanonical",
                "The revision catalog anchor is not canonical.",
            )
        return anchor

    def _reconcile_anchor_unlocked(
        self,
        envelope: RevisionCatalogEnvelope,
        *,
        directory_descriptor: int | None,
    ) -> None:
        anchor = self._load_anchor_unlocked()
        if anchor is None:
            empty_sha256 = revision_catalog_sha256(
                empty_revision_catalog_snapshot()
            )
            if (
                envelope.generation != 1
                or envelope.previous_snapshot_sha256 != empty_sha256
            ):
                raise CatalogStorageError(
                    "catalog_anchor_missing",
                    "A non-initial revision catalog has no recovery anchor.",
                )
            self._publish_anchor_unlocked(
                RevisionCatalogAnchor(
                    generation=envelope.generation,
                    previous_snapshot_sha256=(
                        envelope.previous_snapshot_sha256
                    ),
                    snapshot_sha256=envelope.snapshot_sha256,
                ),
                directory_descriptor=directory_descriptor,
            )
            return
        if (
            envelope.generation == anchor.generation
            and envelope.previous_snapshot_sha256
            == anchor.previous_snapshot_sha256
            and envelope.snapshot_sha256 == anchor.snapshot_sha256
        ):
            return
        if (
            envelope.generation == anchor.generation + 1
            and envelope.previous_snapshot_sha256 == anchor.snapshot_sha256
        ):
            self._publish_anchor_unlocked(
                RevisionCatalogAnchor(
                    generation=envelope.generation,
                    previous_snapshot_sha256=(
                        envelope.previous_snapshot_sha256
                    ),
                    snapshot_sha256=envelope.snapshot_sha256,
                ),
                directory_descriptor=directory_descriptor,
            )
            return
        if envelope.generation <= anchor.generation:
            raise CatalogStorageError(
                "catalog_rollback_detected",
                "The revision catalog is older than or diverges from its anchor.",
            )
        raise CatalogStorageError(
            "catalog_anchor_inconsistent",
            "The revision catalog does not extend its recovery anchor.",
        )

    def _publish_snapshot_unlocked(
        self,
        snapshot: RevisionCatalogSnapshot,
        *,
        previous_snapshot_sha256: str,
        directory_descriptor: int | None,
    ) -> None:
        envelope = RevisionCatalogEnvelope(
            generation=len(snapshot.ledger.receipts),
            previous_snapshot_sha256=previous_snapshot_sha256,
            snapshot_sha256=revision_catalog_sha256(snapshot),
            snapshot=snapshot,
        )
        payload = canonical_revision_catalog_envelope_bytes(envelope)
        if len(payload) > self.max_catalog_bytes:
            raise CatalogStorageError(
                "catalog_too_large",
                "The revision catalog exceeds its configured byte limit.",
            )
        target = self.catalog_path
        if _lstat_optional(target) is not None:
            _validate_safe_regular_path(target)
        temporary = self.root / (
            f".catalog.json.tmp-{secrets.token_hex(8)}"
        )
        descriptor: int | None = None
        replaced = False
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.close(descriptor)
            descriptor = None
            _validate_safe_regular_path(temporary)
            _replace_catalog_file(temporary, target)
            replaced = True
            _sync_directory(self.root, directory_descriptor)
            if _read_safe_regular_file(
                target,
                byte_limit=self.max_catalog_bytes,
            ) != payload:
                raise CatalogStorageError(
                    "catalog_publish_verification_failed",
                    "The published revision catalog did not verify.",
                )
            self._publish_anchor_unlocked(
                RevisionCatalogAnchor(
                    generation=envelope.generation,
                    previous_snapshot_sha256=(
                        envelope.previous_snapshot_sha256
                    ),
                    snapshot_sha256=envelope.snapshot_sha256,
                ),
                directory_descriptor=directory_descriptor,
            )
        except CatalogStorageError as exc:
            if replaced:
                raise CatalogStorageError(
                    "catalog_commit_outcome_unknown",
                    "Catalog replacement completed, but commit verification "
                    "did not finish; retry the same event ID.",
                ) from exc
            raise
        except OSError as exc:
            code = (
                "catalog_commit_outcome_unknown"
                if replaced
                else "catalog_publish_failed"
            )
            message = (
                "Catalog replacement completed, but durable commit "
                "confirmation is unknown; retry the same event ID."
                if replaced
                else "The revision catalog could not be published atomically."
            )
            raise CatalogStorageError(
                code,
                message,
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if _lstat_optional(temporary) is not None:
                try:
                    _validate_safe_regular_path(temporary)
                    temporary.unlink()
                except (CatalogStorageError, OSError):
                    pass

    def _publish_anchor_unlocked(
        self,
        anchor: RevisionCatalogAnchor,
        *,
        directory_descriptor: int | None,
    ) -> None:
        payload = canonical_revision_catalog_anchor_bytes(anchor)
        target = self.anchor_path
        if _lstat_optional(target) is not None:
            _validate_safe_regular_path(target)
        temporary = self.root / (
            f".catalog.anchor.json.tmp-{secrets.token_hex(8)}"
        )
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.close(descriptor)
            descriptor = None
            _validate_safe_regular_path(temporary)
            _replace_catalog_file(temporary, target)
            _sync_directory(self.root, directory_descriptor)
            if _read_safe_regular_file(
                target,
                byte_limit=64 * 1024,
            ) != payload:
                raise CatalogStorageError(
                    "catalog_anchor_publish_failed",
                    "The revision catalog anchor did not verify.",
                )
        except CatalogStorageError:
            raise
        except OSError as exc:
            raise CatalogStorageError(
                "catalog_anchor_publish_failed",
                "The revision catalog anchor could not be published.",
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if _lstat_optional(temporary) is not None:
                try:
                    _validate_safe_regular_path(temporary)
                    temporary.unlink()
                except (CatalogStorageError, OSError):
                    pass


def _validate_materialization_request(
    event: SourceEvent,
    materialization: RevisionMaterializationRecord | None,
) -> None:
    if event.operation == "DELETE":
        if materialization is not None:
            raise CatalogConflict(
                "delete_materialization_forbidden",
                "DELETE must not include materialization provenance.",
            )
        return
    if (
        materialization is not None
        and (
            materialization.parent_event_id != event.event_id
            or materialization.content_sha256 != event.content_sha256
        )
    ):
        raise CatalogConflict(
            "materialization_event_mismatch",
            "Materialization identity or content does not match the event.",
        )
    if isinstance(materialization, RevisionMaterializationV2):
        projection_sha256 = materialization.document_projection.canonical_sha256()
        if event.metadata.get("document_projection_sha256") != projection_sha256:
            raise CatalogConflict(
                "document_projection_mismatch",
                "The document projection does not match the source event.",
            )


def _build_revision(
    *,
    event: SourceEvent,
    application: SourceEventApplication,
    ledger: SourceEventLedger,
    materialization: RevisionMaterializationRecord | None,
) -> DocumentRevision:
    head = next(
        head
        for head in ledger.snapshot().source_heads
        if (head.source_system, head.source_key)
        == (event.source_system, event.source_key)
    )
    return DocumentRevision(
        revision_id=application.receipt.resulting_revision_id,
        previous_revision_id=application.receipt.previous_revision_id,
        event_id=event.event_id,
        event_payload_sha256=application.receipt.payload_sha256,
        operation=event.operation,
        source_system=event.source_system,
        source_key=event.source_key,
        tenant_id=event.tenant_id,
        region=head.region,
        acl_groups=head.acl_groups,
        actor_pseudonym=event.actor_pseudonym,
        occurred_at=event.occurred_at,
        declared_media_type=(
            event.declared_media_type if event.operation == "UPSERT" else None
        ),
        content_sha256=(
            event.content_sha256 if event.operation == "UPSERT" else None
        ),
        materialization=materialization,
        deleted=event.operation == "DELETE",
    )


def _validate_safe_regular_path(path: Path) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise CatalogStorageError(
            "catalog_file_unsafe",
            "The revision catalog file is unavailable.",
        ) from exc
    if (
        stat_is_redirect(metadata)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise CatalogStorageError(
            "catalog_file_unsafe",
            "The revision catalog file is not a private regular file.",
        )
    return metadata


def _lstat_optional(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _read_safe_regular_file(path: Path, *, byte_limit: int) -> bytes:
    expected = _validate_safe_regular_path(path)
    if expected.st_size > byte_limit:
        raise CatalogStorageError(
            "catalog_too_large",
            "The revision catalog exceeds its configured byte limit.",
        )
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        actual = os.fstat(descriptor)
        current = path.lstat()
        if (
            not stat.S_ISREG(actual.st_mode)
            or actual.st_nlink != 1
            or stat_is_redirect(current)
            or not os.path.samestat(expected, actual)
            or not os.path.samestat(actual, current)
        ):
            raise CatalogStorageError(
                "catalog_file_unsafe",
                "The revision catalog changed while opening.",
            )
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(byte_limit + 1)
        after = os.fstat(descriptor)
        if (
            not os.path.samestat(actual, after)
            or actual.st_size != after.st_size
            or getattr(actual, "st_mtime_ns", None)
            != getattr(after, "st_mtime_ns", None)
        ):
            raise CatalogStorageError(
                "catalog_file_unsafe",
                "The revision catalog changed while reading.",
            )
        if len(payload) > byte_limit:
            raise CatalogStorageError(
                "catalog_too_large",
                "The revision catalog exceeds its configured byte limit.",
            )
        return payload
    except CatalogStorageError:
        raise
    except OSError as exc:
        raise CatalogStorageError(
            "catalog_read_failed",
            "The revision catalog could not be read safely.",
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def load_revision_catalog_snapshot_read_only(
    root: Path,
    *,
    max_catalog_bytes: int = _DEFAULT_MAX_CATALOG_BYTES,
) -> RevisionCatalogSnapshot:
    candidate = Path(root)
    if not candidate.is_absolute():
        raise CatalogStorageError(
            "catalog_root_invalid",
            "The revision catalog root must be absolute.",
        )
    if max_catalog_bytes < 128:
        raise ValueError("max_catalog_bytes must be at least 128")
    metadata = _lstat_optional(candidate)
    if metadata is None:
        return empty_revision_catalog_snapshot()
    try:
        if (
            stat_is_redirect(metadata)
            or not stat.S_ISDIR(metadata.st_mode)
            or absolute_path_has_redirect(candidate)
        ):
            raise CatalogStorageError(
                "catalog_root_redirect",
                "The revision catalog root is redirected.",
            )
    except OSError as exc:
        raise CatalogStorageError(
            "catalog_root_invalid",
            "The revision catalog root is unavailable.",
        ) from exc

    catalog_path = candidate / _CATALOG_FILE
    anchor_path = candidate / _ANCHOR_FILE
    if _lstat_optional(catalog_path) is None:
        if _lstat_optional(anchor_path) is not None:
            raise CatalogStorageError(
                "catalog_missing",
                "The initialized revision catalog is missing.",
            )
        return empty_revision_catalog_snapshot()
    raw = _read_safe_regular_file(
        catalog_path,
        byte_limit=max_catalog_bytes,
    )
    try:
        envelope = RevisionCatalogEnvelope.model_validate_json(raw)
    except ValidationError as exc:
        message = str(exc)
        if "checksum mismatch" in message:
            code = "catalog_integrity_failed"
        elif "schema_version" in message:
            code = "catalog_schema_unsupported"
        else:
            code = "catalog_invalid"
        raise CatalogStorageError(
            code,
            "The revision catalog failed strict validation.",
        ) from exc
    if raw != canonical_revision_catalog_envelope_bytes(envelope):
        raise CatalogStorageError(
            "catalog_noncanonical",
            "The revision catalog is not in canonical form.",
        )

    if _lstat_optional(anchor_path) is None:
        raise CatalogStorageError(
            "catalog_anchor_recovery_required",
            "The revision catalog requires authenticated recovery.",
        )
    anchor_raw = _read_safe_regular_file(
        anchor_path,
        byte_limit=min(max_catalog_bytes, 64 * 1024),
    )
    try:
        anchor = RevisionCatalogAnchor.model_validate_json(anchor_raw)
    except ValidationError as exc:
        raise CatalogStorageError(
            "catalog_anchor_invalid",
            "The revision catalog anchor failed strict validation.",
        ) from exc
    if anchor_raw != canonical_revision_catalog_anchor_bytes(anchor):
        raise CatalogStorageError(
            "catalog_anchor_noncanonical",
            "The revision catalog anchor is not canonical.",
        )
    if (
        envelope.generation != anchor.generation
        or envelope.previous_snapshot_sha256
        != anchor.previous_snapshot_sha256
        or envelope.snapshot_sha256 != anchor.snapshot_sha256
    ):
        raise CatalogStorageError(
            "catalog_anchor_recovery_required",
            "The revision catalog requires authenticated recovery.",
        )
    return envelope.snapshot


def _open_safe_lock_file(path: Path) -> int:
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        metadata = os.fstat(descriptor)
        current = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat_is_redirect(current)
            or not os.path.samestat(metadata, current)
        ):
            raise CatalogStorageError(
                "catalog_lock_unsafe",
                "The revision catalog lock is unsafe.",
            )
        if metadata.st_size == 0:
            os.write(descriptor, b"\x00")
            os.fsync(descriptor)
        return descriptor
    except CatalogStorageError:
        if "descriptor" in locals():
            os.close(descriptor)
        raise
    except OSError as exc:
        if "descriptor" in locals():
            os.close(descriptor)
        raise CatalogStorageError(
            "catalog_lock_failed",
            "The revision catalog lock could not be opened safely.",
        ) from exc


def _assert_open_file_is_current(path: Path, descriptor: int) -> None:
    try:
        actual = os.fstat(descriptor)
        current = path.lstat()
    except OSError as exc:
        raise CatalogStorageError(
            "catalog_lock_unsafe",
            "The revision catalog lock changed while held.",
        ) from exc
    if (
        not stat.S_ISREG(actual.st_mode)
        or actual.st_nlink != 1
        or stat_is_redirect(current)
        or not os.path.samestat(actual, current)
    ):
        raise CatalogStorageError(
            "catalog_lock_unsafe",
            "The revision catalog lock changed while held.",
        )


def _lock_descriptor(descriptor: int, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(
                    descriptor,
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
            return
        except (BlockingIOError, OSError):
            if time.monotonic() >= deadline:
                raise CatalogStorageError(
                    "catalog_lock_timeout",
                    "The revision catalog lock timed out.",
                ) from None
            time.sleep(_LOCK_POLL_SECONDS)


def _unlock_descriptor(descriptor: int) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


def _replace_catalog_file(source: Path, target: Path) -> None:
    replace_private_file(source, target)


def _sync_directory(
    path: Path,
    directory_descriptor: int | None = None,
) -> None:
    if directory_descriptor is not None:
        sync_private_directory(directory_descriptor)
        return
    if os.name == "nt":
        return
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "CatalogApplication",
    "CatalogTransition",
    "CatalogConflict",
    "CatalogStorageError",
    "DocumentProjection",
    "DocumentRevision",
    "PersistentRevisionCatalog",
    "RevisionCatalogAnchor",
    "RevisionCatalogEnvelope",
    "RevisionCatalogSnapshot",
    "RevisionMaterialization",
    "RevisionMaterializationRecord",
    "RevisionMaterializationV2",
    "apply_revision_catalog_snapshot",
    "canonical_revision_catalog_bytes",
    "canonical_revision_catalog_anchor_bytes",
    "canonical_revision_catalog_envelope_bytes",
    "empty_revision_catalog_snapshot",
    "load_revision_catalog_snapshot_read_only",
    "revision_catalog_sha256",
]
