from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.indexing.change_plan import (
    ChangePlanError,
    PlanExclusion,
    build_change_plan,
    canonical_change_plan_bytes,
)
from app.ingestion.revision_catalog import (
    PersistentRevisionCatalog,
    RevisionCatalogSnapshot,
    RevisionMaterialization,
    empty_revision_catalog_snapshot,
)
from app.ingestion.source_events import SourceEvent


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


def _upsert(
    source_key: str,
    *,
    event_id: str,
    content: str,
    expected: str | None = None,
    acl: tuple[str, ...] = ("group-readers",),
) -> SourceEvent:
    return SourceEvent(
        event_id=event_id,
        operation="UPSERT",
        tenant_id="tenant-alpha",
        region="ap-east",
        source_system="portal",
        source_key=source_key,
        expected_revision_id=expected,
        occurred_at=NOW,
        content_relpath=f"policies/{source_key}.md",
        declared_media_type="text/markdown",
        content_sha256=content * 64,
        actor_pseudonym="operator-alpha",
        acl_groups=acl,
    )


def _delete(source_key: str, *, event_id: str, expected: str) -> SourceEvent:
    return SourceEvent(
        event_id=event_id,
        operation="DELETE",
        tenant_id="tenant-alpha",
        region="ap-east",
        source_system="portal",
        source_key=source_key,
        expected_revision_id=expected,
        occurred_at=NOW,
        actor_pseudonym="operator-alpha",
    )


def _materialization(
    event: SourceEvent,
    *,
    parser_version: str = "2",
    normalizer_version: str = "normalize-v2",
) -> RevisionMaterialization:
    assert event.content_sha256 is not None
    return RevisionMaterialization(
        document_id=f"doc-{event.source_key}",
        asset_id=f"asset_{event.content_sha256[:32]}",
        parent_event_id=event.event_id,
        content_sha256=event.content_sha256,
        normalized_sha256=event.content_sha256,
        parser_name="markdown",
        parser_version=parser_version,
        normalizer_version=normalizer_version,
    )


def _apply(catalog: PersistentRevisionCatalog, event: SourceEvent):
    return catalog.apply(
        event,
        materialization=(
            _materialization(event) if event.operation == "UPSERT" else None
        ),
    )


def _classified_snapshots(
    root: Path,
) -> tuple[RevisionCatalogSnapshot, RevisionCatalogSnapshot]:
    catalog = PersistentRevisionCatalog(root)
    first: dict[str, str] = {}
    for source_key, content in (
        ("changed", "a"),
        ("deleted", "b"),
        ("restored", "c"),
        ("same", "d"),
        ("old-tombstone", "e"),
    ):
        event = _upsert(
            source_key,
            event_id=f"evt-{source_key}-1",
            content=content,
        )
        first[source_key] = _apply(catalog, event).revision.revision_id

    restored_delete = _apply(
        catalog,
        _delete(
            "restored",
            event_id="evt-restored-delete",
            expected=first["restored"],
        ),
    )
    _apply(
        catalog,
        _delete(
            "old-tombstone",
            event_id="evt-old-tombstone-delete",
            expected=first["old-tombstone"],
        ),
    )
    base = catalog.snapshot()

    _apply(
        catalog,
        _upsert(
            "changed",
            event_id="evt-changed-2",
            content="f",
            expected=first["changed"],
        ),
    )
    _apply(
        catalog,
        _delete(
            "deleted",
            event_id="evt-deleted-delete",
            expected=first["deleted"],
        ),
    )
    _apply(
        catalog,
        _upsert(
            "restored",
            event_id="evt-restored-2",
            content="1",
            expected=restored_delete.revision.revision_id,
        ),
    )
    _apply(
        catalog,
        _upsert("new", event_id="evt-new-1", content="2"),
    )
    return base, catalog.snapshot()


def test_change_plan_classifies_all_source_transitions_without_overlap(
    tmp_path: Path,
) -> None:
    base, target = _classified_snapshots((tmp_path / "catalog").absolute())

    plan = build_change_plan(
        base=base,
        target=target,
        base_index_run_id="index-base",
        target_index_run_id="index-target",
    )

    assert [(item.source_key, item.reason_code) for item in plan.upserts] == [
        ("changed", "content_changed"),
        ("new", "new_source"),
        ("restored", "source_restored"),
    ]
    assert [(item.source_key, item.reason_code) for item in plan.deletes] == [
        ("deleted", "source_deleted")
    ]
    assert [item.source_key for item in plan.unchanged] == ["same"]
    assert [item.source_key for item in plan.retained_tombstones] == [
        "old-tombstone"
    ]
    assert plan.executable is True
    classified = [
        (item.source_system, item.source_key)
        for group in (
            plan.upserts,
            plan.deletes,
            plan.unchanged,
            plan.retained_tombstones,
        )
        for item in group
    ]
    assert len(classified) == len(set(classified))


def test_change_plan_is_byte_deterministic_after_restart_and_repeat(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "catalog").absolute()
    base, target = _classified_snapshots(root)

    first = build_change_plan(
        base=base,
        target=target,
        base_index_run_id="index-base",
        target_index_run_id="index-target",
    )
    second = build_change_plan(
        base=base,
        target=PersistentRevisionCatalog(root).snapshot(),
        base_index_run_id="index-base",
        target_index_run_id="index-target",
    )

    assert first == second
    assert first.plan_id == second.plan_id
    assert canonical_change_plan_bytes(first) == canonical_change_plan_bytes(second)
    assert b"created_at" not in canonical_change_plan_bytes(first)


def test_plan_requires_distinct_base_and_target_index_runs(
    tmp_path: Path,
) -> None:
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    event = _upsert("a", event_id="evt-a", content="a")
    _apply(catalog, event)
    nonempty = catalog.snapshot()

    with pytest.raises(ChangePlanError) as missing:
        build_change_plan(
            base=nonempty,
            target=nonempty,
            base_index_run_id=None,
            target_index_run_id="index-target",
        )
    assert missing.value.code == "base_index_run_required"

    with pytest.raises(ChangePlanError) as unexpected:
        build_change_plan(
            base=empty_revision_catalog_snapshot(),
            target=nonempty,
            base_index_run_id="index-impossible",
            target_index_run_id="index-target",
        )
    assert unexpected.value.code == "base_index_run_unexpected"

    with pytest.raises(ChangePlanError) as same:
        build_change_plan(
            base=nonempty,
            target=nonempty,
            base_index_run_id="index-same",
            target_index_run_id="index-same",
        )
    assert same.value.code == "target_index_run_conflict"


def test_parser_or_normalizer_change_is_not_governance_only(
    tmp_path: Path,
) -> None:
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    first_event = _upsert("a", event_id="evt-a-1", content="a")
    first = _apply(catalog, first_event)
    base = catalog.snapshot()
    second_event = _upsert(
        "a",
        event_id="evt-a-2",
        content="a",
        expected=first.revision.revision_id,
    )
    catalog.apply(
        second_event,
        materialization=_materialization(
            second_event,
            parser_version="3",
            normalizer_version="normalize-v3",
        ),
    )

    plan = build_change_plan(
        base=base,
        target=catalog.snapshot(),
        base_index_run_id="index-base",
        target_index_run_id="index-target",
    )

    assert [(item.source_key, item.reason_code) for item in plan.upserts] == [
        ("a", "materialization_changed")
    ]


def test_independent_event_order_produces_same_catalog_and_plan(
    tmp_path: Path,
) -> None:
    events = [
        _upsert("a", event_id="evt-a", content="a"),
        _upsert("b", event_id="evt-b", content="b"),
    ]
    catalog_ab = PersistentRevisionCatalog((tmp_path / "ab").absolute())
    catalog_ba = PersistentRevisionCatalog((tmp_path / "ba").absolute())
    for event in events:
        _apply(catalog_ab, event)
    for event in reversed(events):
        _apply(catalog_ba, event)

    empty = empty_revision_catalog_snapshot()
    plan_ab = build_change_plan(
        base=empty,
        target=catalog_ab.snapshot(),
        base_index_run_id=None,
        target_index_run_id="index-first",
    )
    plan_ba = build_change_plan(
        base=empty,
        target=catalog_ba.snapshot(),
        base_index_run_id=None,
        target_index_run_id="index-first",
    )

    assert catalog_ab.snapshot() == catalog_ba.snapshot()
    assert canonical_change_plan_bytes(plan_ab) == canonical_change_plan_bytes(plan_ba)


def test_plan_rejects_target_that_removes_accepted_history(
    tmp_path: Path,
) -> None:
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    event_a = _upsert("a", event_id="evt-a", content="a")
    event_b = _upsert("b", event_id="evt-b", content="b")
    _apply(catalog, event_a)
    base = catalog.snapshot()
    _apply(catalog, event_b)
    target_payload = catalog.snapshot().model_dump(mode="json")
    target_payload["ledger"]["receipts"] = [
        item
        for item in target_payload["ledger"]["receipts"]
        if item["source_key"] != "a"
    ]
    target_payload["ledger"]["source_heads"] = [
        item
        for item in target_payload["ledger"]["source_heads"]
        if item["source_key"] != "a"
    ]
    target_payload["revisions"] = [
        item
        for item in target_payload["revisions"]
        if item["source_key"] != "a"
    ]
    rewritten = RevisionCatalogSnapshot.model_validate(target_payload)

    with pytest.raises(ChangePlanError) as captured:
        build_change_plan(
            base=base,
            target=rewritten,
            base_index_run_id="index-base",
            target_index_run_id="index-target",
        )

    assert captured.value.code == "target_not_forward"


def test_explicit_conflict_or_quarantine_makes_plan_non_executable(
    tmp_path: Path,
) -> None:
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    event = _upsert("a", event_id="evt-a", content="a")
    _apply(catalog, event)
    exclusion = PlanExclusion(
        event_id="evt-blocked-1",
        event_payload_sha256="8" * 64,
        tenant_id="tenant-alpha",
        source_system="portal",
        source_key="blocked",
        reason_code="asset_quarantined",
    )

    plan = build_change_plan(
        base=empty_revision_catalog_snapshot(),
        target=catalog.snapshot(),
        base_index_run_id=None,
        target_index_run_id="index-target",
        quarantined=(exclusion,),
    )

    assert plan.executable is False
    assert plan.quarantined == (exclusion,)


def test_source_cannot_be_both_conflicted_and_quarantined(
    tmp_path: Path,
) -> None:
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    event = _upsert("a", event_id="evt-a", content="a")
    _apply(catalog, event)
    conflicted = PlanExclusion(
        event_id="evt-blocked-1",
        event_payload_sha256="8" * 64,
        tenant_id="tenant-alpha",
        source_system="portal",
        source_key="blocked",
        reason_code="expected_revision_conflict",
    )
    quarantined = conflicted.model_copy(
        update={"reason_code": "asset_quarantined"}
    )

    with pytest.raises(ValueError, match="multiple exclusion"):
        build_change_plan(
            base=empty_revision_catalog_snapshot(),
            target=catalog.snapshot(),
            base_index_run_id=None,
            target_index_run_id="index-target",
            conflicts=(conflicted,),
            quarantined=(quarantined,),
        )


def test_same_source_can_record_multiple_distinct_excluded_attempts(
    tmp_path: Path,
) -> None:
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    event = _upsert("a", event_id="evt-a", content="a")
    _apply(catalog, event)
    exclusions = (
        PlanExclusion(
            event_id="evt-blocked-1",
            event_payload_sha256="8" * 64,
            tenant_id="tenant-alpha",
            source_system="portal",
            source_key="blocked",
            reason_code="expected_revision_conflict",
        ),
        PlanExclusion(
            event_id="evt-blocked-2",
            event_payload_sha256="9" * 64,
            tenant_id="tenant-alpha",
            source_system="portal",
            source_key="blocked",
            reason_code="event_payload_conflict",
        ),
    )

    plan = build_change_plan(
        base=empty_revision_catalog_snapshot(),
        target=catalog.snapshot(),
        base_index_run_id=None,
        target_index_run_id="index-target",
        conflicts=reversed(exclusions),
    )

    assert plan.conflicts == exclusions
    assert plan.excluded_event_count == 2
    assert plan.executable is False


def test_failed_catalog_or_plan_does_not_touch_index_state(tmp_path: Path) -> None:
    index_root = tmp_path / "indexes"
    version = index_root / "versions" / "existing"
    version.mkdir(parents=True)
    (version / "manifest.json").write_text("immutable", encoding="ascii")
    active = index_root / "active.json"
    active.write_text('{"run_id":"existing"}', encoding="ascii")
    before = {
        path.relative_to(index_root).as_posix(): path.read_bytes()
        for path in index_root.rglob("*")
        if path.is_file()
    }
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    event = _upsert("a", event_id="evt-a", content="a")
    first = _apply(catalog, event)
    stale = _upsert(
        "a",
        event_id="evt-a-stale",
        content="b",
        expected="rev_" + "0" * 64,
    )

    with pytest.raises(Exception):
        _apply(catalog, stale)
    with pytest.raises(ChangePlanError):
        build_change_plan(
            base=catalog.snapshot(),
            target=empty_revision_catalog_snapshot(),
            base_index_run_id="existing",
            target_index_run_id="new",
        )

    after = {
        path.relative_to(index_root).as_posix(): path.read_bytes()
        for path in index_root.rglob("*")
        if path.is_file()
    }
    assert first.revision.revision_id
    assert after == before
