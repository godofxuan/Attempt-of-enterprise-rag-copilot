from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.ingestion.source_events import (
    SourceEvent,
    SourceEventConflict,
    SourceEventLedger,
    SourceEventLedgerSnapshot,
    canonical_source_event_ledger_bytes,
    canonical_source_event_bytes,
    source_event_payload_sha256,
)


CONTENT_SHA256 = "a" * 64


def _upsert_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "source_event_v1",
        "event_id": "evt-001",
        "operation": "UPSERT",
        "tenant_id": "tenant-alpha",
        "region": "ap-east",
        "source_system": "policy-portal",
        "source_key": "policy-001",
        "expected_revision_id": None,
        "occurred_at": datetime(
            2026,
            7,
            26,
            16,
            0,
            tzinfo=timezone(timedelta(hours=8)),
        ),
        "content_relpath": "policies/policy-001.md",
        "declared_media_type": "Text/Markdown",
        "content_sha256": CONTENT_SHA256,
        "actor_pseudonym": "operator-alpha",
        "acl_groups": ["group-readers", "group-legal"],
        "metadata": {"priority": "standard", "sequence": 1},
    }
    payload.update(overrides)
    return payload


def test_valid_upsert_has_stable_canonical_serialization() -> None:
    first = SourceEvent.model_validate(_upsert_payload())
    second = SourceEvent.model_validate(
        _upsert_payload(
            occurred_at=datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc),
            declared_media_type="text/markdown",
            acl_groups=["group-legal", "group-readers"],
            metadata={"sequence": 1, "priority": "standard"},
        )
    )

    assert first.occurred_at == datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc)
    assert first.acl_groups == ("group-legal", "group-readers")
    assert first.declared_media_type == "text/markdown"
    canonical = canonical_source_event_bytes(first)
    assert canonical == canonical_source_event_bytes(second)
    assert source_event_payload_sha256(first) == hashlib.sha256(canonical).hexdigest()
    assert source_event_payload_sha256(first) == (
        "42121ffe7e15d087618afa55991b82ebc33f0bd4c105369279b13e013a9fed8e"
    )


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("content_relpath", "policies/deleted.md"),
        ("declared_media_type", "text/markdown"),
        ("content_sha256", CONTENT_SHA256),
        ("acl_groups", ["group-legal"]),
    ],
)
def test_delete_is_content_free(
    field_name: str,
    field_value: object,
) -> None:
    payload = _upsert_payload(
        event_id="evt-delete-001",
        operation="DELETE",
        expected_revision_id="rev_" + "b" * 64,
        content_relpath=None,
        declared_media_type=None,
        content_sha256=None,
        acl_groups=[],
        metadata={},
    )
    valid = SourceEvent.model_validate(payload)
    assert valid.operation == "DELETE"

    payload[field_name] = field_value
    with pytest.raises(ValidationError, match="DELETE"):
        SourceEvent.model_validate(payload)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "/etc/policy.md",
        "../policy.md",
        "policies/../policy.md",
        "C:/policies/policy.md",
        "\\\\server\\share\\policy.md",
        "policies\\policy.md",
        "policies/\x00policy.md",
    ],
)
def test_upsert_rejects_unsafe_content_relpath(unsafe_path: str) -> None:
    with pytest.raises(ValidationError, match="content_relpath"):
        SourceEvent.model_validate(_upsert_payload(content_relpath=unsafe_path))


@pytest.mark.parametrize(
    "override",
    [
        {"acl_groups": ["g" * 129]},
        {"metadata": {"k" * 65: "value"}},
        {"metadata": {"key": "v" * 513}},
    ],
)
def test_source_event_rejects_overlong_nested_values(
    override: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        SourceEvent.model_validate(_upsert_payload(**override))


@pytest.mark.parametrize(
    "override",
    [
        {"unexpected_field": "not-allowed"},
        {"occurred_at": datetime(2026, 7, 26, 8, 0)},
        {"event_id": "e" * 129},
        {"content_sha256": CONTENT_SHA256.upper()},
    ],
)
def test_source_event_rejects_extra_naive_or_overlong_fields(
    override: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        SourceEvent.model_validate(_upsert_payload(**override))


def test_same_event_and_canonical_payload_is_an_idempotent_replay() -> None:
    ledger = SourceEventLedger()
    first_event = SourceEvent.model_validate(_upsert_payload())
    equivalent_event = SourceEvent.model_validate(
        _upsert_payload(
            occurred_at=datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc),
            declared_media_type="text/markdown",
            acl_groups=["group-legal", "group-readers"],
            metadata={"sequence": 1, "priority": "standard"},
        )
    )

    first = ledger.apply(first_event)
    accepted_snapshot = ledger.snapshot()
    replay = ledger.apply(equivalent_event)

    assert first.status == "APPLIED"
    assert replay.status == "REPLAYED"
    assert replay.receipt == first.receipt
    assert ledger.snapshot() == accepted_snapshot


def test_same_event_id_with_different_payload_conflicts_without_mutation() -> None:
    ledger = SourceEventLedger()
    ledger.apply(SourceEvent.model_validate(_upsert_payload()))
    accepted_snapshot = ledger.snapshot()
    changed = SourceEvent.model_validate(
        _upsert_payload(content_sha256="b" * 64)
    )

    with pytest.raises(SourceEventConflict) as captured:
        ledger.apply(changed)

    assert captured.value.code == "event_payload_conflict"
    assert captured.value.event_id == "evt-001"
    assert ledger.snapshot() == accepted_snapshot


def test_stale_expected_revision_conflicts_without_state_mutation() -> None:
    ledger = SourceEventLedger()
    first = ledger.apply(SourceEvent.model_validate(_upsert_payload()))
    accepted_snapshot = ledger.snapshot()
    stale = SourceEvent.model_validate(
        _upsert_payload(
            event_id="evt-002",
            expected_revision_id="rev_" + "0" * 64,
            content_sha256="b" * 64,
        )
    )

    with pytest.raises(SourceEventConflict) as captured:
        ledger.apply(stale)

    assert first.receipt.resulting_revision_id != stale.expected_revision_id
    assert captured.value.code == "expected_revision_conflict"
    assert ledger.snapshot() == accepted_snapshot


def test_correct_revision_update_and_delete_preserve_lineage() -> None:
    ledger = SourceEventLedger()
    first = ledger.apply(SourceEvent.model_validate(_upsert_payload()))
    update = ledger.apply(
        SourceEvent.model_validate(
            _upsert_payload(
                event_id="evt-002",
                expected_revision_id=first.receipt.resulting_revision_id,
                content_sha256="b" * 64,
                acl_groups=["group-audit"],
            )
        )
    )
    delete_event = SourceEvent.model_validate(
        _upsert_payload(
            event_id="evt-delete-001",
            operation="DELETE",
            expected_revision_id=update.receipt.resulting_revision_id,
            content_relpath=None,
            declared_media_type=None,
            content_sha256=None,
            acl_groups=[],
            metadata={},
        )
    )

    deleted = ledger.apply(delete_event)
    accepted_snapshot = ledger.snapshot()
    replay = ledger.apply(delete_event)

    assert update.receipt.previous_revision_id == first.receipt.resulting_revision_id
    assert deleted.receipt.previous_revision_id == update.receipt.resulting_revision_id
    assert deleted.receipt.deleted is True
    assert accepted_snapshot.source_heads[0].acl_groups == ("group-audit",)
    assert accepted_snapshot.source_heads[0].deleted is True
    assert replay.status == "REPLAYED"
    assert replay.receipt == deleted.receipt
    assert ledger.snapshot() == accepted_snapshot


def test_cross_tenant_source_identity_conflicts_without_mutation() -> None:
    ledger = SourceEventLedger()
    first = ledger.apply(SourceEvent.model_validate(_upsert_payload()))
    accepted_snapshot = ledger.snapshot()
    takeover = SourceEvent.model_validate(
        _upsert_payload(
            event_id="evt-tenant-takeover",
            tenant_id="tenant-beta",
            expected_revision_id=first.receipt.resulting_revision_id,
            content_sha256="b" * 64,
        )
    )

    with pytest.raises(SourceEventConflict) as captured:
        ledger.apply(takeover)

    assert captured.value.code == "source_tenant_conflict"
    assert ledger.snapshot() == accepted_snapshot


@pytest.mark.parametrize(
    "protected_key",
    [
        "event_id",
        "operation",
        "tenantId",
        "Tenant-ID",
        "region",
        "sourceSystem",
        "source_key",
        "ACL-Groups",
        "actor_pseudonym",
        "expectedRevisionId",
        "revision_id",
        "contentSha256",
    ],
)
def test_metadata_cannot_override_protected_event_fields(
    protected_key: str,
) -> None:
    with pytest.raises(ValidationError, match="protected"):
        SourceEvent.model_validate(
            _upsert_payload(metadata={protected_key: "shadow-value"})
        )

    accepted = SourceEvent.model_validate(
        _upsert_payload(metadata={"business_priority": "standard"})
    )
    assert accepted.metadata == {"business_priority": "standard"}


def test_commuting_sources_have_one_snapshot_and_competing_updates_conflict() -> None:
    event_a = SourceEvent.model_validate(
        _upsert_payload(event_id="evt-a", source_key="policy-a")
    )
    event_b = SourceEvent.model_validate(
        _upsert_payload(
            event_id="evt-b",
            source_key="policy-b",
            content_relpath="policies/policy-b.md",
            content_sha256="b" * 64,
        )
    )
    ledger_ab = SourceEventLedger()
    ledger_ab.apply(event_a)
    first_b = ledger_ab.apply(event_b)
    ledger_ba = SourceEventLedger()
    ledger_ba.apply(event_b)
    ledger_ba.apply(event_a)

    snapshot = ledger_ab.snapshot()
    assert snapshot == ledger_ba.snapshot()
    assert canonical_source_event_ledger_bytes(snapshot) == (
        canonical_source_event_ledger_bytes(ledger_ba.snapshot())
    )

    restored = SourceEventLedger.from_snapshot(snapshot)
    replay = restored.apply(event_b)
    assert replay.status == "REPLAYED"
    assert replay.receipt == first_b.receipt
    assert restored.snapshot() == snapshot

    update_one = SourceEvent.model_validate(
        _upsert_payload(
            event_id="evt-b-update-1",
            source_key="policy-b",
            content_relpath="policies/policy-b.md",
            content_sha256="c" * 64,
            expected_revision_id=first_b.receipt.resulting_revision_id,
        )
    )
    update_two = SourceEvent.model_validate(
        _upsert_payload(
            event_id="evt-b-update-2",
            source_key="policy-b",
            content_relpath="policies/policy-b.md",
            content_sha256="d" * 64,
            expected_revision_id=first_b.receipt.resulting_revision_id,
        )
    )
    restored.apply(update_one)
    accepted_snapshot = restored.snapshot()

    with pytest.raises(SourceEventConflict) as captured:
        restored.apply(update_two)

    assert captured.value.code == "expected_revision_conflict"
    assert restored.snapshot() == accepted_snapshot


def test_accepted_receipts_and_snapshots_are_immutable() -> None:
    ledger = SourceEventLedger()
    applied = ledger.apply(SourceEvent.model_validate(_upsert_payload()))
    accepted_snapshot = ledger.snapshot()

    with pytest.raises(ValidationError, match="frozen"):
        applied.receipt.tenant_id = "tenant-beta"
    with pytest.raises(ValidationError, match="frozen"):
        accepted_snapshot.source_heads[0].deleted = True

    assert ledger.snapshot() == accepted_snapshot


def test_snapshot_rejects_duplicate_event_receipts() -> None:
    ledger = SourceEventLedger()
    ledger.apply(SourceEvent.model_validate(_upsert_payload()))
    payload = ledger.snapshot().model_dump(mode="json")
    payload["receipts"].append(dict(payload["receipts"][0]))

    with pytest.raises(ValidationError, match="receipt event IDs"):
        SourceEventLedgerSnapshot.model_validate(payload)


def test_snapshot_rejects_unknown_current_revision() -> None:
    ledger = SourceEventLedger()
    ledger.apply(SourceEvent.model_validate(_upsert_payload()))
    payload = ledger.snapshot().model_dump(mode="json")
    payload["source_heads"][0]["current_revision_id"] = "rev_" + "0" * 64

    with pytest.raises(ValidationError, match="current revision"):
        SourceEventLedgerSnapshot.model_validate(payload)


@pytest.mark.parametrize(
    "override",
    [
        {"event_id": "evt-\x00-unsafe"},
        {"source_key": "policy\nunsafe"},
        {"expected_revision_id": "not-a-revision"},
        {"declared_media_type": "not a media type"},
    ],
)
def test_source_event_rejects_malformed_identifiers_and_media_types(
    override: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        SourceEvent.model_validate(_upsert_payload(**override))


def test_delete_requires_a_live_existing_source() -> None:
    missing_ledger = SourceEventLedger()
    missing_delete = SourceEvent.model_validate(
        _upsert_payload(
            event_id="evt-delete-missing",
            operation="DELETE",
            expected_revision_id="rev_" + "0" * 64,
            content_relpath=None,
            declared_media_type=None,
            content_sha256=None,
            acl_groups=[],
            metadata={},
        )
    )
    with pytest.raises(SourceEventConflict) as missing:
        missing_ledger.apply(missing_delete)
    assert missing.value.code == "source_not_found"
    assert missing_ledger.snapshot().receipts == ()

    ledger = SourceEventLedger()
    first = ledger.apply(SourceEvent.model_validate(_upsert_payload()))
    delete = SourceEvent.model_validate(
        _upsert_payload(
            event_id="evt-delete-001",
            operation="DELETE",
            expected_revision_id=first.receipt.resulting_revision_id,
            content_relpath=None,
            declared_media_type=None,
            content_sha256=None,
            acl_groups=[],
            metadata={},
        )
    )
    deleted = ledger.apply(delete)
    accepted_snapshot = ledger.snapshot()
    second_delete = SourceEvent.model_validate(
        _upsert_payload(
            event_id="evt-delete-002",
            operation="DELETE",
            expected_revision_id=deleted.receipt.resulting_revision_id,
            content_relpath=None,
            declared_media_type=None,
            content_sha256=None,
            acl_groups=[],
            metadata={},
        )
    )
    with pytest.raises(SourceEventConflict) as already_deleted:
        ledger.apply(second_delete)
    assert already_deleted.value.code == "source_already_deleted"
    assert ledger.snapshot() == accepted_snapshot


def test_delete_region_mismatch_conflicts_before_mutation() -> None:
    ledger = SourceEventLedger()
    first = ledger.apply(SourceEvent.model_validate(_upsert_payload()))
    accepted_snapshot = ledger.snapshot()
    wrong_region = SourceEvent.model_validate(
        _upsert_payload(
            event_id="evt-delete-wrong-region",
            operation="DELETE",
            region="eu-west",
            expected_revision_id=first.receipt.resulting_revision_id,
            content_relpath=None,
            declared_media_type=None,
            content_sha256=None,
            acl_groups=[],
            metadata={},
        )
    )

    with pytest.raises(SourceEventConflict) as captured:
        ledger.apply(wrong_region)

    assert captured.value.code == "source_region_conflict"
    assert ledger.snapshot() == accepted_snapshot


@pytest.mark.parametrize(
    "tamper_case",
    [
        "receipt_payload",
        "receipt_deleted",
        "previous_revision",
        "head_tenant",
    ],
)
def test_snapshot_rejects_tampered_lineage(tamper_case: str) -> None:
    ledger = SourceEventLedger()
    first = ledger.apply(SourceEvent.model_validate(_upsert_payload()))
    ledger.apply(
        SourceEvent.model_validate(
            _upsert_payload(
                event_id="evt-002",
                expected_revision_id=first.receipt.resulting_revision_id,
                content_sha256="b" * 64,
            )
        )
    )
    payload = ledger.snapshot().model_dump(mode="json")
    if tamper_case == "receipt_payload":
        payload["receipts"][0]["payload_sha256"] = "f" * 64
    elif tamper_case == "receipt_deleted":
        payload["receipts"][0]["deleted"] = True
    elif tamper_case == "previous_revision":
        payload["receipts"][1]["previous_revision_id"] = "rev_" + "0" * 64
    else:
        payload["source_heads"][0]["tenant_id"] = "tenant-beta"

    with pytest.raises(ValidationError):
        SourceEventLedgerSnapshot.model_validate(payload)


def test_upsert_can_recreate_tombstoned_source_with_exact_revision() -> None:
    ledger = SourceEventLedger()
    first = ledger.apply(SourceEvent.model_validate(_upsert_payload()))
    deleted = ledger.apply(
        SourceEvent.model_validate(
            _upsert_payload(
                event_id="evt-delete-001",
                operation="DELETE",
                expected_revision_id=first.receipt.resulting_revision_id,
                content_relpath=None,
                declared_media_type=None,
                content_sha256=None,
                acl_groups=[],
                metadata={},
            )
        )
    )
    recreated = ledger.apply(
        SourceEvent.model_validate(
            _upsert_payload(
                event_id="evt-recreate-001",
                expected_revision_id=deleted.receipt.resulting_revision_id,
                content_sha256="b" * 64,
                acl_groups=["group-restored"],
            )
        )
    )
    snapshot = ledger.snapshot()

    assert recreated.receipt.previous_revision_id == (
        deleted.receipt.resulting_revision_id
    )
    assert recreated.receipt.deleted is False
    assert snapshot.source_heads[0].deleted is False
    assert snapshot.source_heads[0].acl_groups == ("group-restored",)
