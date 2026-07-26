from __future__ import annotations

import hashlib
import json
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ingestion.revision_catalog import (
    DocumentRevision,
    RevisionCatalogSnapshot,
    revision_catalog_sha256,
)


ChangeReason = Literal[
    "content_changed",
    "governance_changed",
    "materialization_changed",
    "new_source",
    "revision_only",
    "source_deleted",
    "source_restored",
    "tombstone_retained",
    "unchanged",
]


class ChangePlanModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class PlannedSourceChange(ChangePlanModel):
    source_system: str = Field(min_length=1, max_length=128)
    source_key: str = Field(min_length=1, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=128)
    region: str = Field(min_length=1, max_length=64)
    previous_revision_id: str | None = Field(
        default=None,
        pattern=r"^rev_[0-9a-f]{64}$",
    )
    target_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{64}$")
    reason_code: ChangeReason


class PlanExclusion(ChangePlanModel):
    event_id: str = Field(min_length=1, max_length=128)
    event_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tenant_id: str = Field(min_length=1, max_length=128)
    source_system: str = Field(min_length=1, max_length=128)
    source_key: str = Field(min_length=1, max_length=256)
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class ChangePlan(ChangePlanModel):
    schema_version: Literal["change_plan_v1"] = "change_plan_v1"
    plan_id: str = Field(pattern=r"^plan_[0-9a-f]{64}$")
    base_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_events_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_index_run_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    target_index_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    executable: bool
    base_event_count: int = Field(ge=0)
    target_event_count: int = Field(ge=0)
    added_event_count: int = Field(ge=0)
    excluded_event_count: int = Field(ge=0)
    upsert_count: int = Field(ge=0)
    delete_count: int = Field(ge=0)
    unchanged_count: int = Field(ge=0)
    retained_tombstone_count: int = Field(ge=0)
    upserts: tuple[PlannedSourceChange, ...] = ()
    deletes: tuple[PlannedSourceChange, ...] = ()
    unchanged: tuple[PlannedSourceChange, ...] = ()
    retained_tombstones: tuple[PlannedSourceChange, ...] = ()
    conflicts: tuple[PlanExclusion, ...] = ()
    quarantined: tuple[PlanExclusion, ...] = ()

    @field_validator(
        "upserts",
        "deletes",
        "unchanged",
        "retained_tombstones",
    )
    @classmethod
    def validate_change_order(
        cls,
        values: tuple[PlannedSourceChange, ...],
    ) -> tuple[PlannedSourceChange, ...]:
        identities = [
            (item.source_system, item.source_key) for item in values
        ]
        if identities != sorted(identities) or len(identities) != len(
            set(identities)
        ):
            raise ValueError("planned source changes must use unique canonical order")
        return values

    @field_validator("conflicts", "quarantined")
    @classmethod
    def validate_exclusion_order(
        cls,
        values: tuple[PlanExclusion, ...],
    ) -> tuple[PlanExclusion, ...]:
        identities = [
            (
                item.source_system,
                item.source_key,
                item.event_id,
                item.event_payload_sha256,
                item.reason_code,
            )
            for item in values
        ]
        if identities != sorted(identities) or len(identities) != len(
            set(identities)
        ):
            raise ValueError("plan exclusions must use unique canonical order")
        return values

    @model_validator(mode="after")
    def validate_plan(self) -> ChangePlan:
        groups = (
            self.upserts,
            self.deletes,
            self.unchanged,
            self.retained_tombstones,
        )
        identities = [
            (item.source_system, item.source_key)
            for group in groups
            for item in group
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("ChangePlan source classifications must not overlap")
        exclusion_identities = [
            (item.event_id, item.event_payload_sha256)
            for group in (self.conflicts, self.quarantined)
            for item in group
        ]
        if len(exclusion_identities) != len(set(exclusion_identities)):
            raise ValueError(
                "ChangePlan attempts cannot have multiple exclusion dispositions"
            )
        if self.base_event_count == 0:
            if self.base_index_run_id is not None:
                raise ValueError(
                    "empty ChangePlan base cannot declare an index run"
                )
        elif self.base_index_run_id is None:
            raise ValueError(
                "non-empty ChangePlan base requires an index run"
            )
        if (
            self.base_index_run_id is not None
            and self.base_index_run_id == self.target_index_run_id
        ):
            raise ValueError(
                "ChangePlan target index run must differ from its base"
            )
        if (
            self.target_event_count < self.base_event_count
            or self.added_event_count
            != self.target_event_count - self.base_event_count
            or self.excluded_event_count
            != len(self.conflicts) + len(self.quarantined)
        ):
            raise ValueError("ChangePlan event counts are inconsistent")
        if (
            self.upsert_count != len(self.upserts)
            or self.delete_count != len(self.deletes)
            or self.unchanged_count != len(self.unchanged)
            or self.retained_tombstone_count
            != len(self.retained_tombstones)
        ):
            raise ValueError("ChangePlan counts do not match classifications")
        if self.executable != (not self.conflicts and not self.quarantined):
            raise ValueError("ChangePlan executable state does not match exclusions")
        if self.plan_id != _plan_id(self.model_dump(mode="json", exclude={"plan_id"})):
            raise ValueError("ChangePlan ID does not bind canonical plan inputs")
        return self


class ChangePlanError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _plan_id(payload: object) -> str:
    return f"plan_{hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()}"


def _event_set_sha256(payload_hashes: Iterable[str]) -> str:
    return hashlib.sha256(
        _canonical_json_bytes(sorted(payload_hashes))
    ).hexdigest()


def _canonical_exclusions(
    values: Iterable[PlanExclusion],
) -> tuple[PlanExclusion, ...]:
    validated = [
        PlanExclusion.model_validate(value.model_dump(mode="json"))
        for value in values
    ]
    return tuple(
        sorted(
            validated,
            key=lambda item: (
                item.source_system,
                item.source_key,
                item.event_id,
                item.event_payload_sha256,
                item.reason_code,
            ),
        )
    )


def _require_forward_history(
    base: RevisionCatalogSnapshot,
    target: RevisionCatalogSnapshot,
) -> None:
    target_receipts = {
        receipt.event_id: receipt for receipt in target.ledger.receipts
    }
    for receipt in base.ledger.receipts:
        if target_receipts.get(receipt.event_id) != receipt:
            raise ChangePlanError(
                "target_not_forward",
                "Target catalog removes or rewrites an accepted event receipt.",
            )
    target_revisions = {
        revision.revision_id: revision for revision in target.revisions
    }
    for revision in base.revisions:
        if target_revisions.get(revision.revision_id) != revision:
            raise ChangePlanError(
                "target_not_forward",
                "Target catalog removes or rewrites an accepted revision.",
            )


def _validate_index_run_transition(
    *,
    base_event_count: int,
    base_index_run_id: str | None,
    target_index_run_id: str,
) -> None:
    if base_event_count > 0 and base_index_run_id is None:
        raise ChangePlanError(
            "base_index_run_required",
            "A non-empty base catalog requires its immutable index run ID.",
        )
    if base_event_count == 0 and base_index_run_id is not None:
        raise ChangePlanError(
            "base_index_run_unexpected",
            "An empty base catalog cannot declare an index run ID.",
        )
    if (
        base_index_run_id is not None
        and base_index_run_id == target_index_run_id
    ):
        raise ChangePlanError(
            "target_index_run_conflict",
            "Target index run ID must differ from the immutable base run.",
        )


def _source_change(
    *,
    target_revision: DocumentRevision,
    previous_revision_id: str | None,
    reason_code: ChangeReason,
) -> PlannedSourceChange:
    return PlannedSourceChange(
        source_system=target_revision.source_system,
        source_key=target_revision.source_key,
        tenant_id=target_revision.tenant_id,
        region=target_revision.region,
        previous_revision_id=previous_revision_id,
        target_revision_id=target_revision.revision_id,
        reason_code=reason_code,
    )


def _materialization_inputs(
    revision: DocumentRevision,
) -> tuple[str | None, ...]:
    materialization = revision.materialization
    if materialization is None:
        return (revision.declared_media_type, None, None, None, None, None)
    return (
        revision.declared_media_type,
        materialization.document_id,
        materialization.normalized_sha256,
        materialization.parser_name,
        materialization.parser_version,
        materialization.normalizer_version,
    )


def build_change_plan(
    *,
    base: RevisionCatalogSnapshot,
    target: RevisionCatalogSnapshot,
    base_index_run_id: str | None,
    target_index_run_id: str,
    conflicts: Iterable[PlanExclusion] = (),
    quarantined: Iterable[PlanExclusion] = (),
) -> ChangePlan:
    validated_base = RevisionCatalogSnapshot.model_validate(
        base.model_dump(mode="json")
    )
    validated_target = RevisionCatalogSnapshot.model_validate(
        target.model_dump(mode="json")
    )
    _require_forward_history(validated_base, validated_target)
    base_event_count = len(validated_base.ledger.receipts)
    target_event_count = len(validated_target.ledger.receipts)
    _validate_index_run_transition(
        base_event_count=base_event_count,
        base_index_run_id=base_index_run_id,
        target_index_run_id=target_index_run_id,
    )

    base_heads = {
        (head.source_system, head.source_key): head
        for head in validated_base.ledger.source_heads
    }
    target_heads = {
        (head.source_system, head.source_key): head
        for head in validated_target.ledger.source_heads
    }
    target_revisions = {
        revision.revision_id: revision
        for revision in validated_target.revisions
    }
    base_revisions = {
        revision.revision_id: revision
        for revision in validated_base.revisions
    }

    upserts: list[PlannedSourceChange] = []
    deletes: list[PlannedSourceChange] = []
    unchanged: list[PlannedSourceChange] = []
    retained_tombstones: list[PlannedSourceChange] = []

    for identity in sorted(target_heads):
        target_head = target_heads[identity]
        target_revision = target_revisions[target_head.current_revision_id]
        base_head = base_heads.get(identity)
        previous_revision_id = (
            None if base_head is None else base_head.current_revision_id
        )
        if (
            base_head is not None
            and base_head.current_revision_id == target_head.current_revision_id
        ):
            destination = (
                retained_tombstones if target_head.deleted else unchanged
            )
            destination.append(
                _source_change(
                    target_revision=target_revision,
                    previous_revision_id=previous_revision_id,
                    reason_code=(
                        "tombstone_retained"
                        if target_head.deleted
                        else "unchanged"
                    ),
                )
            )
            continue

        if target_head.deleted:
            destination = (
                retained_tombstones if base_head is None else deletes
            )
            destination.append(
                _source_change(
                    target_revision=target_revision,
                    previous_revision_id=previous_revision_id,
                    reason_code=(
                        "tombstone_retained"
                        if base_head is None
                        else "source_deleted"
                    ),
                )
            )
            continue

        if base_head is None:
            reason: ChangeReason = "new_source"
        elif base_head.deleted:
            reason = "source_restored"
        else:
            base_revision = base_revisions[base_head.current_revision_id]
            if base_revision.content_sha256 != target_revision.content_sha256:
                reason = "content_changed"
            elif _materialization_inputs(
                base_revision
            ) != _materialization_inputs(target_revision):
                reason = "materialization_changed"
            elif (
                base_revision.region != target_revision.region
                or base_revision.acl_groups != target_revision.acl_groups
            ):
                reason = "governance_changed"
            else:
                unchanged.append(
                    _source_change(
                        target_revision=target_revision,
                        previous_revision_id=previous_revision_id,
                        reason_code="revision_only",
                    )
                )
                continue
        upserts.append(
            _source_change(
                target_revision=target_revision,
                previous_revision_id=previous_revision_id,
                reason_code=reason,
            )
        )

    base_receipt_ids = {
        receipt.event_id for receipt in validated_base.ledger.receipts
    }
    added_receipts = [
        receipt
        for receipt in validated_target.ledger.receipts
        if receipt.event_id not in base_receipt_ids
    ]
    canonical_conflicts = _canonical_exclusions(conflicts)
    canonical_quarantined = _canonical_exclusions(quarantined)
    requested_payload_hashes = [
        *(receipt.payload_sha256 for receipt in added_receipts),
        *(
            item.event_payload_sha256
            for item in (*canonical_conflicts, *canonical_quarantined)
        ),
    ]
    payload = {
        "schema_version": "change_plan_v1",
        "base_catalog_sha256": revision_catalog_sha256(validated_base),
        "target_catalog_sha256": revision_catalog_sha256(validated_target),
        "source_events_sha256": _event_set_sha256(requested_payload_hashes),
        "base_index_run_id": base_index_run_id,
        "target_index_run_id": target_index_run_id,
        "executable": not canonical_conflicts and not canonical_quarantined,
        "base_event_count": base_event_count,
        "target_event_count": target_event_count,
        "added_event_count": len(added_receipts),
        "excluded_event_count": (
            len(canonical_conflicts) + len(canonical_quarantined)
        ),
        "upsert_count": len(upserts),
        "delete_count": len(deletes),
        "unchanged_count": len(unchanged),
        "retained_tombstone_count": len(retained_tombstones),
        "upserts": [item.model_dump(mode="json") for item in upserts],
        "deletes": [item.model_dump(mode="json") for item in deletes],
        "unchanged": [item.model_dump(mode="json") for item in unchanged],
        "retained_tombstones": [
            item.model_dump(mode="json") for item in retained_tombstones
        ],
        "conflicts": [
            item.model_dump(mode="json") for item in canonical_conflicts
        ],
        "quarantined": [
            item.model_dump(mode="json") for item in canonical_quarantined
        ],
    }
    return ChangePlan(
        plan_id=_plan_id(payload),
        **payload,
    )


def canonical_change_plan_bytes(plan: ChangePlan) -> bytes:
    validated = ChangePlan.model_validate(plan.model_dump(mode="json"))
    return _canonical_json_bytes(validated.model_dump(mode="json"))


__all__ = [
    "ChangePlan",
    "ChangePlanError",
    "PlanExclusion",
    "PlannedSourceChange",
    "build_change_plan",
    "canonical_change_plan_bytes",
]
