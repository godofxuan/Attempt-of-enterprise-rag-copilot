from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MetadataScalar = str | int | float | bool | None
SourceOperation = Literal["UPSERT", "DELETE"]
SourceEventConflictCode = Literal[
    "event_payload_conflict",
    "expected_revision_conflict",
    "source_already_deleted",
    "source_not_found",
    "source_region_conflict",
    "source_tenant_conflict",
]
MEDIA_TYPE_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/"
    r"[a-z0-9][a-z0-9!#$&^_.+-]{0,63}$"
)
PROTECTED_METADATA_KEYS = frozenset(
    {
        "acl",
        "aclgroups",
        "actor",
        "actorpseudonym",
        "contentsha256",
        "contentrelpath",
        "declaredmediatype",
        "eventid",
        "expectedrevision",
        "expectedrevisionid",
        "occurredat",
        "operation",
        "region",
        "revision",
        "revisionid",
        "schemaversion",
        "sourcekey",
        "sourcesystem",
        "tenant",
        "tenantid",
    }
)


class SourceEventModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


def _has_control_character(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


class SourceEvent(SourceEventModel):
    schema_version: Literal["source_event_v1"] = "source_event_v1"
    event_id: str = Field(min_length=1, max_length=128)
    operation: SourceOperation
    tenant_id: str = Field(min_length=1, max_length=128)
    region: str = Field(min_length=1, max_length=64)
    source_system: str = Field(min_length=1, max_length=128)
    source_key: str = Field(min_length=1, max_length=256)
    expected_revision_id: str | None = Field(
        default=None,
        pattern=r"^rev_[0-9a-f]{64}$",
    )
    occurred_at: datetime
    content_relpath: str | None = Field(default=None, max_length=512)
    declared_media_type: str | None = Field(default=None, max_length=128)
    content_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    actor_pseudonym: str = Field(min_length=1, max_length=128)
    acl_groups: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    metadata: dict[str, MetadataScalar] = Field(default_factory=dict, max_length=64)

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("declared_media_type")
    @classmethod
    def normalize_media_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.lower()
        if MEDIA_TYPE_PATTERN.fullmatch(normalized) is None:
            raise ValueError("declared_media_type must use type/subtype form")
        return normalized

    @field_validator(
        "event_id",
        "tenant_id",
        "region",
        "source_system",
        "source_key",
        "actor_pseudonym",
        "expected_revision_id",
    )
    @classmethod
    def validate_printable_identifiers(cls, value: str | None) -> str | None:
        if value is not None and _has_control_character(value):
            raise ValueError("event identifiers must not contain control characters")
        return value

    @field_validator("content_relpath")
    @classmethod
    def validate_content_relpath(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = value.split("/")
        if (
            "\x00" in value
            or "\\" in value
            or value.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or ":" in parts[0]
            or PurePosixPath(value).as_posix() != value
        ):
            raise ValueError("content_relpath must be a canonical POSIX relative path")
        return value

    @field_validator("acl_groups")
    @classmethod
    def normalize_acl_groups(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("acl_groups must be unique")
        for value in values:
            if not value or len(value) > 128 or _has_control_character(value):
                raise ValueError("acl_groups values must be bounded printable strings")
        return tuple(sorted(values))

    @field_validator("metadata")
    @classmethod
    def validate_metadata_numbers(
        cls, values: dict[str, MetadataScalar]
    ) -> dict[str, MetadataScalar]:
        for key, value in values.items():
            normalized_key = "".join(
                char for char in key.casefold() if char.isalnum()
            )
            if normalized_key in PROTECTED_METADATA_KEYS:
                raise ValueError("metadata key aliases a protected event field")
            if (
                not key
                or len(key) > 64
                or _has_control_character(key)
            ):
                raise ValueError("metadata keys must be bounded printable strings")
            if isinstance(value, str) and (
                len(value) > 512 or _has_control_character(value)
            ):
                raise ValueError(
                    "metadata string values must be bounded printable strings"
                )
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("metadata numbers must be finite")
        return values

    @model_validator(mode="after")
    def validate_operation_shape(self) -> SourceEvent:
        if self.operation == "UPSERT":
            if (
                self.content_relpath is None
                or self.declared_media_type is None
                or self.content_sha256 is None
                or not self.acl_groups
            ):
                raise ValueError(
                    "UPSERT requires content_relpath, declared_media_type, "
                    "content_sha256, and acl_groups"
                )
            return self
        if self.expected_revision_id is None:
            raise ValueError("DELETE requires expected_revision_id")
        if (
            self.content_relpath is not None
            or self.declared_media_type is not None
            or self.content_sha256 is not None
            or self.acl_groups
        ):
            raise ValueError("DELETE must not carry content or acl_groups")
        return self


def canonical_source_event_bytes(event: SourceEvent) -> bytes:
    return json.dumps(
        event.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def source_event_payload_sha256(event: SourceEvent) -> str:
    return hashlib.sha256(canonical_source_event_bytes(event)).hexdigest()


class SourceEventReceipt(SourceEventModel):
    schema_version: Literal["source_event_receipt_v1"] = "source_event_receipt_v1"
    event_id: str = Field(min_length=1, max_length=128)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    operation: SourceOperation
    tenant_id: str = Field(min_length=1, max_length=128)
    region: str = Field(min_length=1, max_length=64)
    source_system: str = Field(min_length=1, max_length=128)
    source_key: str = Field(min_length=1, max_length=256)
    actor_pseudonym: str = Field(min_length=1, max_length=128)
    occurred_at: datetime
    previous_revision_id: str | None = Field(
        default=None,
        pattern=r"^rev_[0-9a-f]{64}$",
    )
    resulting_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{64}$")
    deleted: bool

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("receipt occurred_at must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator(
        "event_id",
        "tenant_id",
        "region",
        "source_system",
        "source_key",
        "actor_pseudonym",
    )
    @classmethod
    def validate_printable_identifiers(cls, value: str) -> str:
        if _has_control_character(value):
            raise ValueError("receipt identifiers must not contain control characters")
        return value

    @model_validator(mode="after")
    def validate_receipt_binding(self) -> SourceEventReceipt:
        if self.resulting_revision_id != f"rev_{self.payload_sha256}":
            raise ValueError("receipt revision must bind its payload SHA-256")
        if self.deleted != (self.operation == "DELETE"):
            raise ValueError("receipt deleted state must match operation")
        if self.previous_revision_id == self.resulting_revision_id:
            raise ValueError("receipt revision cannot reference itself")
        return self


class SourceHead(SourceEventModel):
    source_system: str = Field(min_length=1, max_length=128)
    source_key: str = Field(min_length=1, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=128)
    region: str = Field(min_length=1, max_length=64)
    acl_groups: tuple[str, ...] = Field(max_length=100)
    current_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{64}$")
    deleted: bool

    @field_validator(
        "source_system",
        "source_key",
        "tenant_id",
        "region",
    )
    @classmethod
    def validate_printable_identifiers(cls, value: str) -> str:
        if _has_control_character(value):
            raise ValueError(
                "source-head identifiers must not contain control characters"
            )
        return value

    @field_validator("acl_groups")
    @classmethod
    def validate_acl_groups(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or len(values) != len(set(values)):
            raise ValueError("source-head ACL groups must be non-empty and unique")
        if any(
            len(value) > 128 or _has_control_character(value)
            for value in values
        ):
            raise ValueError("source-head ACL groups must be bounded printable strings")
        if values != tuple(sorted(values)):
            raise ValueError("source-head ACL groups must use canonical order")
        return values


class SourceEventLedgerSnapshot(SourceEventModel):
    schema_version: Literal["source_event_ledger_v1"] = "source_event_ledger_v1"
    receipts: tuple[SourceEventReceipt, ...] = Field(default_factory=tuple)
    source_heads: tuple[SourceHead, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_unique_canonical_order(self) -> SourceEventLedgerSnapshot:
        event_ids = [receipt.event_id for receipt in self.receipts]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("snapshot receipt event IDs must be unique")
        if event_ids != sorted(event_ids):
            raise ValueError("snapshot receipts must use canonical event-ID order")
        source_identities = [
            (head.source_system, head.source_key) for head in self.source_heads
        ]
        if len(source_identities) != len(set(source_identities)):
            raise ValueError("snapshot source identities must be unique")
        if source_identities != sorted(source_identities):
            raise ValueError("snapshot source heads must use canonical identity order")

        receipts_by_revision = {
            receipt.resulting_revision_id: receipt for receipt in self.receipts
        }
        if len(receipts_by_revision) != len(self.receipts):
            raise ValueError("snapshot receipt revisions must be unique")
        heads_by_identity = {
            (head.source_system, head.source_key): head
            for head in self.source_heads
        }
        receipts_by_identity: dict[
            tuple[str, str], list[SourceEventReceipt]
        ] = {}
        for receipt in self.receipts:
            identity = (receipt.source_system, receipt.source_key)
            receipts_by_identity.setdefault(identity, []).append(receipt)
        if set(receipts_by_identity) != set(heads_by_identity):
            raise ValueError("snapshot receipts and source heads must cover the same identities")

        for identity, identity_receipts in receipts_by_identity.items():
            head = heads_by_identity[identity]
            current = receipts_by_revision.get(head.current_revision_id)
            if current is None or (
                current.source_system,
                current.source_key,
            ) != identity:
                raise ValueError("snapshot source-head current revision is unknown")
            if (
                current.tenant_id != head.tenant_id
                or current.region != head.region
                or current.deleted != head.deleted
            ):
                raise ValueError("snapshot source head does not match current receipt")

            roots = [
                receipt
                for receipt in identity_receipts
                if receipt.previous_revision_id is None
            ]
            if len(roots) != 1:
                raise ValueError("snapshot source lineage must have exactly one root")
            child_by_previous: dict[str, SourceEventReceipt] = {}
            for receipt in identity_receipts:
                previous_id = receipt.previous_revision_id
                if previous_id is None:
                    continue
                parent = receipts_by_revision.get(previous_id)
                if parent is None or (
                    parent.source_system,
                    parent.source_key,
                    parent.tenant_id,
                ) != (
                    receipt.source_system,
                    receipt.source_key,
                    receipt.tenant_id,
                ):
                    raise ValueError("snapshot receipt previous revision is unknown")
                if previous_id in child_by_previous:
                    raise ValueError("snapshot source lineage cannot branch")
                child_by_previous[previous_id] = receipt

            visited: set[str] = set()
            cursor = roots[0]
            while True:
                if cursor.resulting_revision_id in visited:
                    raise ValueError("snapshot source lineage contains a cycle")
                visited.add(cursor.resulting_revision_id)
                child = child_by_previous.get(cursor.resulting_revision_id)
                if child is None:
                    break
                cursor = child
            if len(visited) != len(identity_receipts):
                raise ValueError("snapshot source lineage contains disconnected receipts")
            if cursor.resulting_revision_id != head.current_revision_id:
                raise ValueError("snapshot source head is not the lineage tip")
        return self


class SourceEventApplication(SourceEventModel):
    status: Literal["APPLIED", "REPLAYED"]
    receipt: SourceEventReceipt


class SourceEventConflict(Exception):
    def __init__(
        self,
        *,
        code: SourceEventConflictCode,
        event_id: str,
        message: str,
    ) -> None:
        self.code = code
        self.event_id = event_id
        self.message = message
        super().__init__(f"{code}: {message} ({event_id})")


class SourceEventLedger:
    def __init__(self) -> None:
        self._receipts: dict[str, SourceEventReceipt] = {}
        self._source_heads: dict[tuple[str, str], SourceHead] = {}

    @classmethod
    def from_snapshot(
        cls,
        snapshot: SourceEventLedgerSnapshot,
    ) -> SourceEventLedger:
        validated = SourceEventLedgerSnapshot.model_validate(
            snapshot.model_dump(mode="json")
        )
        ledger = cls()
        ledger._receipts = {
            receipt.event_id: receipt.model_copy(deep=True)
            for receipt in validated.receipts
        }
        ledger._source_heads = {
            (head.source_system, head.source_key): head.model_copy(deep=True)
            for head in validated.source_heads
        }
        return ledger

    def apply(self, event: SourceEvent) -> SourceEventApplication:
        payload_sha256 = source_event_payload_sha256(event)
        existing = self._receipts.get(event.event_id)
        if existing is not None:
            if existing.payload_sha256 != payload_sha256:
                raise SourceEventConflict(
                    code="event_payload_conflict",
                    event_id=event.event_id,
                    message="accepted event ID has a different canonical payload",
                )
            return SourceEventApplication(status="REPLAYED", receipt=existing)

        identity = (event.source_system, event.source_key)
        previous = self._source_heads.get(identity)
        if previous is not None and previous.tenant_id != event.tenant_id:
            raise SourceEventConflict(
                code="source_tenant_conflict",
                event_id=event.event_id,
                message="source identity is owned by another tenant",
            )
        if previous is None:
            if event.operation == "DELETE":
                raise SourceEventConflict(
                    code="source_not_found",
                    event_id=event.event_id,
                    message="DELETE source identity does not exist",
                )
            if event.expected_revision_id is not None:
                raise SourceEventConflict(
                    code="expected_revision_conflict",
                    event_id=event.event_id,
                    message="new source must not declare an expected revision",
                )
        elif event.expected_revision_id != previous.current_revision_id:
            raise SourceEventConflict(
                code="expected_revision_conflict",
                event_id=event.event_id,
                message="expected revision does not match the current source head",
            )
        elif event.operation == "DELETE" and event.region != previous.region:
            raise SourceEventConflict(
                code="source_region_conflict",
                event_id=event.event_id,
                message="DELETE region does not match the current source head",
            )
        elif event.operation == "DELETE" and previous.deleted:
            raise SourceEventConflict(
                code="source_already_deleted",
                event_id=event.event_id,
                message="DELETE source identity is already tombstoned",
            )
        previous_revision_id = (
            None if previous is None else previous.current_revision_id
        )
        resulting_revision_id = f"rev_{payload_sha256}"
        receipt = SourceEventReceipt(
            event_id=event.event_id,
            payload_sha256=payload_sha256,
            operation=event.operation,
            tenant_id=event.tenant_id,
            region=event.region,
            source_system=event.source_system,
            source_key=event.source_key,
            actor_pseudonym=event.actor_pseudonym,
            occurred_at=event.occurred_at,
            previous_revision_id=previous_revision_id,
            resulting_revision_id=resulting_revision_id,
            deleted=event.operation == "DELETE",
        )
        head = SourceHead(
            source_system=event.source_system,
            source_key=event.source_key,
            tenant_id=event.tenant_id,
            region=(
                previous.region
                if event.operation == "DELETE" and previous is not None
                else event.region
            ),
            acl_groups=(
                previous.acl_groups
                if event.operation == "DELETE" and previous is not None
                else event.acl_groups
            ),
            current_revision_id=resulting_revision_id,
            deleted=event.operation == "DELETE",
        )
        self._receipts[event.event_id] = receipt
        self._source_heads[identity] = head
        return SourceEventApplication(status="APPLIED", receipt=receipt)

    def snapshot(self) -> SourceEventLedgerSnapshot:
        return SourceEventLedgerSnapshot(
            receipts=[
                self._receipts[event_id] for event_id in sorted(self._receipts)
            ],
            source_heads=[
                self._source_heads[identity]
                for identity in sorted(self._source_heads)
            ],
        )


def canonical_source_event_ledger_bytes(
    snapshot: SourceEventLedgerSnapshot,
) -> bytes:
    return json.dumps(
        snapshot.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


__all__ = [
    "MetadataScalar",
    "SourceEvent",
    "SourceEventApplication",
    "SourceEventConflict",
    "SourceEventConflictCode",
    "SourceEventLedger",
    "SourceEventLedgerSnapshot",
    "SourceEventModel",
    "SourceEventReceipt",
    "SourceHead",
    "SourceOperation",
    "canonical_source_event_ledger_bytes",
    "canonical_source_event_bytes",
    "source_event_payload_sha256",
]
