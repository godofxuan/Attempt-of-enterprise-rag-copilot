from __future__ import annotations

import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from multiprocessing import get_context
from pathlib import Path

import pytest
from pydantic import ValidationError

import app.ingestion.revision_catalog as revision_catalog_module
from app.ingestion.revision_catalog import (
    CatalogConflict,
    CatalogStorageError,
    RevisionCatalogSnapshot,
    PersistentRevisionCatalog,
    RevisionCatalogEnvelope,
    RevisionMaterialization,
    canonical_revision_catalog_envelope_bytes,
)
from app.ingestion.source_events import (
    SourceEvent,
    SourceEventConflict,
)
from app.security.private_fs import private_directory_permissions_are_secure


UTC_NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


def _upsert(
    *,
    event_id: str = "evt-a-001",
    source_key: str = "policy-a",
    content_sha256: str = "a" * 64,
    expected_revision_id: str | None = None,
    acl_groups: tuple[str, ...] = ("group-legal", "group-readers"),
) -> SourceEvent:
    return SourceEvent(
        event_id=event_id,
        operation="UPSERT",
        tenant_id="tenant-alpha",
        region="ap-east",
        source_system="policy-portal",
        source_key=source_key,
        expected_revision_id=expected_revision_id,
        occurred_at=UTC_NOW,
        content_relpath=f"policies/{source_key}.md",
        declared_media_type="text/markdown",
        content_sha256=content_sha256,
        actor_pseudonym="operator-alpha",
        acl_groups=acl_groups,
        metadata={"fixture": True},
    )


def _delete(
    *,
    event_id: str,
    source_key: str,
    expected_revision_id: str,
) -> SourceEvent:
    return SourceEvent(
        event_id=event_id,
        operation="DELETE",
        tenant_id="tenant-alpha",
        region="ap-east",
        source_system="policy-portal",
        source_key=source_key,
        expected_revision_id=expected_revision_id,
        occurred_at=UTC_NOW,
        actor_pseudonym="operator-alpha",
    )


def _materialization(
    event: SourceEvent,
    *,
    document_id: str | None = None,
    normalized_sha256: str = "f" * 64,
) -> RevisionMaterialization:
    assert event.content_sha256 is not None
    suffix = event.content_sha256[:32]
    return RevisionMaterialization(
        document_id=document_id or f"doc-{event.source_key}",
        asset_id=f"asset_{suffix}",
        parent_event_id=event.event_id,
        content_sha256=event.content_sha256,
        normalized_sha256=normalized_sha256,
        parser_name="markdown",
        parser_version="2",
        normalizer_version="normalize-v2",
    )


def _apply_in_process(
    root_text: str,
    event_payload: dict[str, object],
    materialization_payload: dict[str, object],
    start_at: float | None = None,
) -> tuple[str, str]:
    if start_at is not None:
        while time.time() < start_at:
            time.sleep(0.005)
    catalog = PersistentRevisionCatalog(Path(root_text))
    event = SourceEvent.model_validate(event_payload)
    materialization = RevisionMaterialization.model_validate(
        materialization_payload
    )
    try:
        result = catalog.apply(event, materialization=materialization)
    except SourceEventConflict as exc:
        return "CONFLICT", exc.code
    return result.status, result.revision.revision_id


def _hold_catalog_lock(
    root_text: str,
    ready_text: str,
    release_text: str,
) -> str:
    catalog = PersistentRevisionCatalog(Path(root_text))
    ready = Path(ready_text)
    release = Path(release_text)
    with catalog._locked():
        ready.write_text("ready", encoding="ascii")
        deadline = time.monotonic() + 20.0
        while not release.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("test release marker was not published")
            time.sleep(0.01)
    return "released"


def test_upsert_persists_one_atomic_checksum_bound_catalog(tmp_path: Path) -> None:
    root = (tmp_path / "catalog").absolute()
    catalog = PersistentRevisionCatalog(root)
    event = _upsert()

    applied = catalog.apply(event, materialization=_materialization(event))
    snapshot = catalog.snapshot()
    raw = catalog.catalog_path.read_bytes()
    envelope = RevisionCatalogEnvelope.model_validate_json(raw)

    assert applied.status == "APPLIED"
    assert len(snapshot.ledger.receipts) == 1
    assert len(snapshot.ledger.source_heads) == 1
    assert snapshot.revisions == (applied.revision,)
    assert envelope.snapshot == snapshot
    assert envelope.generation == 1
    assert raw == canonical_revision_catalog_envelope_bytes(envelope)
    assert not list(root.glob(".catalog.json.tmp-*"))
    assert private_directory_permissions_are_secure(root)


def test_restart_replays_without_rewriting_catalog(tmp_path: Path) -> None:
    root = (tmp_path / "catalog").absolute()
    event = _upsert()
    first = PersistentRevisionCatalog(root)
    applied = first.apply(event, materialization=_materialization(event))
    accepted_bytes = first.catalog_path.read_bytes()

    restarted = PersistentRevisionCatalog(root)
    replay = restarted.apply(event)

    assert replay.status == "REPLAYED"
    assert replay.receipt == applied.receipt
    assert replay.revision == applied.revision
    assert restarted.catalog_path.read_bytes() == accepted_bytes


@pytest.mark.parametrize("case", ["event_payload", "stale_revision", "materialization"])
def test_conflicts_leave_authoritative_catalog_byte_exact(
    tmp_path: Path,
    case: str,
) -> None:
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    first_event = _upsert()
    first = catalog.apply(
        first_event,
        materialization=_materialization(first_event),
    )
    accepted_bytes = catalog.catalog_path.read_bytes()

    if case == "event_payload":
        event = _upsert(content_sha256="b" * 64)
        materialization = _materialization(event)
        expected_error = SourceEventConflict
    elif case == "stale_revision":
        event = _upsert(
            event_id="evt-a-002",
            content_sha256="b" * 64,
            expected_revision_id="rev_" + "0" * 64,
        )
        materialization = _materialization(event)
        expected_error = SourceEventConflict
    else:
        event = first_event
        materialization = _materialization(
            event,
            normalized_sha256="e" * 64,
        )
        expected_error = CatalogConflict

    with pytest.raises(expected_error):
        catalog.apply(event, materialization=materialization)

    assert first.receipt.resulting_revision_id in accepted_bytes.decode("ascii")
    assert catalog.catalog_path.read_bytes() == accepted_bytes


def test_delete_creates_tombstone_and_recreate_preserves_history(
    tmp_path: Path,
) -> None:
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    original_event = _upsert(acl_groups=("group-audit",))
    original = catalog.apply(
        original_event,
        materialization=_materialization(original_event),
    )
    delete_event = _delete(
        event_id="evt-a-delete",
        source_key="policy-a",
        expected_revision_id=original.revision.revision_id,
    )

    deleted = catalog.apply(delete_event)
    tombstone_snapshot = catalog.snapshot()
    recreated_event = _upsert(
        event_id="evt-a-recreate",
        content_sha256="b" * 64,
        expected_revision_id=deleted.revision.revision_id,
        acl_groups=("group-restored",),
    )
    recreated = catalog.apply(
        recreated_event,
        materialization=_materialization(recreated_event),
    )
    final_snapshot = catalog.snapshot()

    assert deleted.revision.deleted is True
    assert deleted.revision.content_sha256 is None
    assert deleted.revision.declared_media_type is None
    assert deleted.revision.materialization is None
    assert deleted.revision.acl_groups == ("group-audit",)
    assert len(tombstone_snapshot.revisions) == 2
    assert len(final_snapshot.revisions) == 3
    assert recreated.revision.previous_revision_id == deleted.revision.revision_id
    assert final_snapshot.ledger.source_heads[0].deleted is False
    assert {item.revision_id for item in final_snapshot.revisions} == {
        original.revision.revision_id,
        deleted.revision.revision_id,
        recreated.revision.revision_id,
    }


def test_snapshot_rejects_root_delete_revision(tmp_path: Path) -> None:
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    event = _upsert()
    catalog.apply(event, materialization=_materialization(event))
    payload = catalog.snapshot().model_dump(mode="json")
    receipt = payload["ledger"]["receipts"][0]
    revision = payload["revisions"][0]
    receipt.update({"operation": "DELETE", "deleted": True})
    payload["ledger"]["source_heads"][0]["deleted"] = True
    revision.update(
        {
            "operation": "DELETE",
            "deleted": True,
            "content_sha256": None,
            "declared_media_type": None,
            "materialization": None,
        }
    )

    with pytest.raises(ValidationError, match="root.*UPSERT"):
        RevisionCatalogSnapshot.model_validate(payload)


def test_snapshot_rejects_delete_after_tombstone(tmp_path: Path) -> None:
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    event = _upsert()
    first = catalog.apply(event, materialization=_materialization(event))
    deleted = catalog.apply(
        _delete(
            event_id="evt-a-delete",
            source_key=event.source_key,
            expected_revision_id=first.revision.revision_id,
        )
    )
    payload = catalog.snapshot().model_dump(mode="json")
    second_hash = "9" * 64
    second_revision_id = f"rev_{second_hash}"
    second_receipt = dict(payload["ledger"]["receipts"][-1])
    second_receipt.update(
        {
            "event_id": "evt-z-delete-again",
            "payload_sha256": second_hash,
            "previous_revision_id": deleted.revision.revision_id,
            "resulting_revision_id": second_revision_id,
        }
    )
    second_revision = dict(payload["revisions"][-1])
    second_revision.update(
        {
            "event_id": "evt-z-delete-again",
            "event_payload_sha256": second_hash,
            "previous_revision_id": deleted.revision.revision_id,
            "revision_id": second_revision_id,
        }
    )
    payload["ledger"]["receipts"].append(second_receipt)
    payload["ledger"]["source_heads"][0]["current_revision_id"] = (
        second_revision_id
    )
    payload["revisions"].append(second_revision)
    payload["revisions"].sort(key=lambda item: item["revision_id"])

    with pytest.raises(ValidationError, match="live revision"):
        RevisionCatalogSnapshot.model_validate(payload)


def test_snapshot_rejects_historical_region_tampering(tmp_path: Path) -> None:
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    first_event = _upsert()
    first = catalog.apply(
        first_event,
        materialization=_materialization(first_event),
    )
    update = _upsert(
        event_id="evt-a-002",
        content_sha256="b" * 64,
        expected_revision_id=first.revision.revision_id,
    )
    catalog.apply(update, materialization=_materialization(update))
    payload = catalog.snapshot().model_dump(mode="json")
    historical = next(
        item
        for item in payload["revisions"]
        if item["revision_id"] == first.revision.revision_id
    )
    historical["region"] = "eu-west"

    with pytest.raises(ValidationError, match="event receipt"):
        RevisionCatalogSnapshot.model_validate(payload)


def test_delete_rejects_materialization_before_catalog_mutation(
    tmp_path: Path,
) -> None:
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    event = _upsert()
    first = catalog.apply(event, materialization=_materialization(event))
    accepted_bytes = catalog.catalog_path.read_bytes()
    delete_event = _delete(
        event_id="evt-a-delete",
        source_key=event.source_key,
        expected_revision_id=first.revision.revision_id,
    )

    with pytest.raises(CatalogConflict, match="DELETE"):
        catalog.apply(
            delete_event,
            materialization=_materialization(event),
        )

    assert catalog.catalog_path.read_bytes() == accepted_bytes


def test_independent_process_writers_are_both_durable(tmp_path: Path) -> None:
    root = (tmp_path / "catalog").absolute()
    event_a = _upsert(event_id="evt-a", source_key="policy-a")
    event_b = _upsert(
        event_id="evt-b",
        source_key="policy-b",
        content_sha256="b" * 64,
    )
    context = get_context("spawn")
    start_at = time.time() + 2.0

    with ProcessPoolExecutor(max_workers=2, mp_context=context) as executor:
        futures = [
            executor.submit(
                _apply_in_process,
                str(root),
                event.model_dump(mode="json"),
                _materialization(event).model_dump(mode="json"),
                start_at,
            )
            for event in (event_a, event_b)
        ]
        outcomes = [future.result(timeout=20) for future in futures]

    assert [status for status, _ in outcomes] == ["APPLIED", "APPLIED"]
    snapshot = PersistentRevisionCatalog(root).snapshot()
    assert len(snapshot.revisions) == 2
    assert {head.source_key for head in snapshot.ledger.source_heads} == {
        "policy-a",
        "policy-b",
    }


def test_competing_process_updates_accept_exactly_one(tmp_path: Path) -> None:
    root = (tmp_path / "catalog").absolute()
    catalog = PersistentRevisionCatalog(root)
    original_event = _upsert()
    original = catalog.apply(
        original_event,
        materialization=_materialization(original_event),
    )
    updates = [
        _upsert(
            event_id=f"evt-update-{suffix}",
            content_sha256=content * 64,
            expected_revision_id=original.revision.revision_id,
        )
        for suffix, content in (("b", "b"), ("c", "c"))
    ]
    context = get_context("spawn")
    start_at = time.time() + 2.0

    with ProcessPoolExecutor(max_workers=2, mp_context=context) as executor:
        futures = [
            executor.submit(
                _apply_in_process,
                str(root),
                event.model_dump(mode="json"),
                _materialization(event).model_dump(mode="json"),
                start_at,
            )
            for event in updates
        ]
        outcomes = [future.result(timeout=20) for future in futures]

    assert sorted(status for status, _ in outcomes) == ["APPLIED", "CONFLICT"]
    assert {detail for status, detail in outcomes if status == "CONFLICT"} == {
        "expected_revision_conflict"
    }
    assert len(PersistentRevisionCatalog(root).snapshot().revisions) == 2


def test_second_process_times_out_while_catalog_lock_is_held(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "catalog").absolute()
    ready = tmp_path / "lock-ready"
    release = tmp_path / "lock-release"
    context = get_context("spawn")

    with ProcessPoolExecutor(max_workers=1, mp_context=context) as executor:
        holder = executor.submit(
            _hold_catalog_lock,
            str(root),
            str(ready),
            str(release),
        )
        deadline = time.monotonic() + 10.0
        while not ready.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("lock holder did not become ready")
            time.sleep(0.01)
        try:
            with pytest.raises(CatalogStorageError) as captured:
                PersistentRevisionCatalog(
                    root,
                    lock_timeout_seconds=0.1,
                ).snapshot()
        finally:
            release.write_text("release", encoding="ascii")
        assert holder.result(timeout=10) == "released"

    assert captured.value.code == "catalog_lock_timeout"


def test_pre_replace_failure_preserves_old_catalog_and_retry_is_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    original_event = _upsert()
    original = catalog.apply(
        original_event,
        materialization=_materialization(original_event),
    )
    accepted_bytes = catalog.catalog_path.read_bytes()
    update = _upsert(
        event_id="evt-a-002",
        content_sha256="b" * 64,
        expected_revision_id=original.revision.revision_id,
    )

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("synthetic pre-replace failure")

    monkeypatch.setattr(
        revision_catalog_module,
        "_replace_catalog_file",
        fail_replace,
    )
    with pytest.raises(CatalogStorageError) as captured:
        catalog.apply(update, materialization=_materialization(update))

    assert captured.value.code == "catalog_publish_failed"
    assert catalog.catalog_path.read_bytes() == accepted_bytes
    assert not list(catalog.root.glob(".catalog.json.tmp-*"))

    monkeypatch.undo()
    retried = catalog.apply(update, materialization=_materialization(update))
    assert retried.status == "APPLIED"
    assert len(catalog.snapshot().revisions) == 2


def test_post_replace_failure_is_recovered_as_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    event = _upsert()

    def fail_sync(
        path: Path,
        directory_descriptor: int | None = None,
    ) -> None:
        raise OSError("synthetic post-replace sync failure")

    monkeypatch.setattr(revision_catalog_module, "_sync_directory", fail_sync)
    with pytest.raises(CatalogStorageError) as captured:
        catalog.apply(event, materialization=_materialization(event))

    assert captured.value.code == "catalog_commit_outcome_unknown"
    monkeypatch.undo()
    recovered = catalog.apply(event, materialization=_materialization(event))
    assert recovered.status == "REPLAYED"
    assert len(catalog.snapshot().revisions) == 1


def test_post_replace_verification_failure_has_unknown_commit_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    event = _upsert()
    original_reader = revision_catalog_module._read_safe_regular_file

    def fail_published_read(path: Path, *, byte_limit: int) -> bytes:
        if path.name == "catalog.json":
            raise CatalogStorageError(
                "catalog_read_failed",
                "synthetic published-read failure",
            )
        return original_reader(path, byte_limit=byte_limit)

    monkeypatch.setattr(
        revision_catalog_module,
        "_read_safe_regular_file",
        fail_published_read,
    )
    with pytest.raises(CatalogStorageError) as captured:
        catalog.apply(event, materialization=_materialization(event))

    assert captured.value.code == "catalog_commit_outcome_unknown"
    monkeypatch.undo()
    assert catalog.apply(event).status == "REPLAYED"


def test_owned_orphan_temp_is_removed_during_locked_recovery(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "catalog").absolute()
    catalog = PersistentRevisionCatalog(root)
    event = _upsert()
    catalog.apply(event, materialization=_materialization(event))
    orphan = root / ".catalog.json.tmp-0123456789abcdef"
    orphan.write_bytes(b"incomplete")

    restored = PersistentRevisionCatalog(root).snapshot()

    assert len(restored.revisions) == 1
    assert not orphan.exists()


def test_initialized_catalog_deletion_is_not_treated_as_empty(
    tmp_path: Path,
) -> None:
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    event = _upsert()
    catalog.apply(event, materialization=_materialization(event))
    catalog.catalog_path.unlink()

    with pytest.raises(CatalogStorageError) as captured:
        PersistentRevisionCatalog(catalog.root).snapshot()

    assert captured.value.code == "catalog_missing"


def test_older_internally_valid_catalog_is_detected_as_rollback(
    tmp_path: Path,
) -> None:
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    first_event = _upsert()
    first = catalog.apply(
        first_event,
        materialization=_materialization(first_event),
    )
    older_bytes = catalog.catalog_path.read_bytes()
    second_event = _upsert(
        event_id="evt-a-002",
        content_sha256="b" * 64,
        expected_revision_id=first.revision.revision_id,
    )
    catalog.apply(
        second_event,
        materialization=_materialization(second_event),
    )
    catalog.catalog_path.write_bytes(older_bytes)

    with pytest.raises(CatalogStorageError) as captured:
        PersistentRevisionCatalog(catalog.root).snapshot()

    assert captured.value.code == "catalog_rollback_detected"


def test_tampered_checksum_and_noncanonical_catalog_fail_closed(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "catalog").absolute()
    catalog = PersistentRevisionCatalog(root)
    event = _upsert()
    catalog.apply(event, materialization=_materialization(event))
    accepted = catalog.catalog_path.read_bytes()
    payload = json.loads(accepted)
    payload["snapshot_sha256"] = "0" * 64
    catalog.catalog_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="ascii",
    )
    tampered_bytes = catalog.catalog_path.read_bytes()

    with pytest.raises(CatalogStorageError) as captured:
        PersistentRevisionCatalog(root).snapshot()

    assert captured.value.code == "catalog_integrity_failed"
    assert catalog.catalog_path.read_bytes() == tampered_bytes


def test_pretty_or_unsupported_catalog_is_not_accepted(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "catalog").absolute()
    catalog = PersistentRevisionCatalog(root)
    event = _upsert()
    catalog.apply(event, materialization=_materialization(event))
    payload = json.loads(catalog.catalog_path.read_bytes())
    catalog.catalog_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="ascii",
    )
    with pytest.raises(CatalogStorageError) as noncanonical:
        PersistentRevisionCatalog(root).snapshot()
    assert noncanonical.value.code == "catalog_noncanonical"

    payload["schema_version"] = "revision_catalog_file_v999"
    catalog.catalog_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="ascii",
    )
    with pytest.raises(CatalogStorageError) as unsupported:
        PersistentRevisionCatalog(root).snapshot()
    assert unsupported.value.code == "catalog_schema_unsupported"


def test_broken_catalog_symlink_is_not_treated_as_empty(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "catalog").absolute()
    root.mkdir()
    catalog_path = root / "catalog.json"
    try:
        catalog_path.symlink_to(tmp_path / "missing-target.json")
    except OSError:
        pytest.skip("symbolic-link creation is unavailable on this platform")

    with pytest.raises(CatalogStorageError) as captured:
        PersistentRevisionCatalog(root).snapshot()

    assert captured.value.code == "catalog_file_unsafe"


def test_catalog_rejects_oversized_or_hardlinked_authoritative_file(
    tmp_path: Path,
) -> None:
    oversized_root = (tmp_path / "oversized").absolute()
    oversized_root.mkdir()
    (oversized_root / "catalog.json").write_bytes(b"x" * 257)
    with pytest.raises(CatalogStorageError) as oversized:
        PersistentRevisionCatalog(
            oversized_root,
            max_catalog_bytes=256,
        ).snapshot()
    assert oversized.value.code == "catalog_too_large"

    linked_root = (tmp_path / "linked").absolute()
    linked_root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"{}")
    try:
        os.link(outside, linked_root / "catalog.json")
    except OSError:
        pytest.skip("hardlink creation is unavailable on this platform")
    with pytest.raises(CatalogStorageError) as linked:
        PersistentRevisionCatalog(linked_root).snapshot()
    assert linked.value.code == "catalog_file_unsafe"


def test_materialization_is_strict_and_content_bound(tmp_path: Path) -> None:
    event = _upsert()
    with pytest.raises(ValidationError):
        RevisionMaterialization.model_validate(
            {
                **_materialization(event).model_dump(mode="json"),
                "unexpected": "field",
            }
        )
    with pytest.raises(CatalogConflict, match="content"):
        PersistentRevisionCatalog((tmp_path / "invalid").absolute()).apply(
            event,
            materialization=_materialization(
                event.model_copy(update={"content_sha256": "b" * 64})
            ),
        )
    assert not (tmp_path / "invalid").exists()


def test_materialization_cannot_be_rebound_to_another_event(
    tmp_path: Path,
) -> None:
    original = _upsert(event_id="evt-original")
    replacement = _upsert(event_id="evt-replacement")
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())

    with pytest.raises(CatalogConflict) as captured:
        catalog.apply(
            replacement,
            materialization=_materialization(original),
        )

    assert captured.value.code == "materialization_event_mismatch"
    assert not catalog.catalog_path.exists()


def test_first_upsert_without_materialization_does_not_publish_catalog(
    tmp_path: Path,
) -> None:
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())

    with pytest.raises(CatalogConflict) as captured:
        catalog.apply(_upsert())

    assert captured.value.code == "materialization_required"
    assert not catalog.catalog_path.exists()
