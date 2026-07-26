from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.ingestion.file_validation import (
    AssetAdmissionError,
    AssetAdmissionPolicy,
    admit_child_asset_bytes,
    admit_source_event_asset,
)
from app.ingestion.source_events import SourceEvent
from app.ingestion.quarantine import SecureAssetStore
from app.security.identity import Principal


def _operator() -> Principal:
    now = datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc)
    return Principal(
        subject="operator-g4-child",
        tenant_id="tenant-a",
        region="cn-east",
        groups=["knowledge-admin"],
        roles=["rag.operator"],
        issuer="https://identity.example.invalid",
        audience="rag-copilot",
        key_id="demo-key-g4",
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )


def _event(content: bytes) -> SourceEvent:
    return SourceEvent(
        event_id="evt-g4-child",
        operation="UPSERT",
        tenant_id="tenant-a",
        region="cn-east",
        source_system="fictional-mailbox",
        source_key="mail/child-test",
        occurred_at=datetime(2026, 7, 26, 8, 5, tzinfo=timezone.utc),
        content_relpath="parent.eml",
        declared_media_type="message/rfc822",
        content_sha256=hashlib.sha256(content).hexdigest(),
        actor_pseudonym="actor-g4",
        acl_groups=("knowledge-readers",),
    )


def _stage_parent(tmp_path: Path):
    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    source_root.mkdir()
    content = (
        b"From: sender@example.invalid\r\n"
        b"To: reader@example.invalid\r\n"
        b"Subject: Parent\r\n\r\nBody\r\n"
    )
    (source_root / "parent.eml").write_bytes(content)
    event = _event(content)
    parent = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )
    return event, parent, storage_root


def test_child_bytes_reenter_shared_validator_with_parent_lineage(
    tmp_path: Path,
) -> None:
    event, parent, storage_root = _stage_parent(tmp_path)
    content = b"Fictional attachment content.\n"

    child = admit_child_asset_bytes(
        event=event,
        principal=_operator(),
        parent_asset=parent,
        content=content,
        filename_suffix=".txt",
        declared_media_type="text/plain",
        storage_root=storage_root,
    )

    assert child.status == "STAGED"
    assert child.parent_event_id == event.event_id
    assert child.parent_asset_id == parent.asset_id
    assert child.original_name_redacted == "[redacted].txt"
    assert child.content_sha256 == hashlib.sha256(content).hexdigest()
    assert child.stored_relpath is not None
    assert (storage_root / child.stored_relpath).read_bytes() == content


def test_child_type_disagreement_is_quarantined_as_blob(tmp_path: Path) -> None:
    event, parent, storage_root = _stage_parent(tmp_path)

    child = admit_child_asset_bytes(
        event=event,
        principal=_operator(),
        parent_asset=parent,
        content=b"%PDF-1.4\n%%EOF\n",
        filename_suffix=".txt",
        declared_media_type="text/plain",
        storage_root=storage_root,
    )

    assert child.status == "QUARANTINED"
    assert child.reason_code == "signature_mismatch"
    assert child.parent_asset_id == parent.asset_id
    assert child.stored_relpath is not None
    assert child.stored_relpath.endswith("/payload.blob")


def test_msg_child_is_explicitly_unsupported_without_mime_parse(
    tmp_path: Path,
) -> None:
    event, parent, storage_root = _stage_parent(tmp_path)

    child = admit_child_asset_bytes(
        event=event,
        principal=_operator(),
        parent_asset=parent,
        content=b"binary-like-msg-content",
        filename_suffix=".msg",
        declared_media_type="application/vnd.ms-outlook",
        storage_root=storage_root,
    )

    assert child.status == "QUARANTINED"
    assert child.reason_code == "msg_not_supported"


def test_msg_source_is_explicitly_unsupported_before_any_parser(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "msg-source"
    storage_root = tmp_path / "msg-store"
    source_root.mkdir()
    content = b"opaque-msg-source-content"
    source = source_root / "mail.msg"
    source.write_bytes(content)
    event = _event(content).model_copy(
        update={
            "content_relpath": source.name,
            "declared_media_type": "application/vnd.ms-outlook",
        }
    )

    receipt = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )

    assert receipt.status == "QUARANTINED"
    assert receipt.reason_code == "msg_not_supported"


def test_child_admission_rejects_forged_nonexistent_parent(
    tmp_path: Path,
) -> None:
    event, parent, storage_root = _stage_parent(tmp_path)
    forged_id = "asset_" + "e" * 32
    forged = parent.model_copy(
        update={
            "asset_id": forged_id,
            "stored_relpath": f"staged/{forged_id}/payload.eml",
        }
    )

    try:
        admit_child_asset_bytes(
            event=event,
            principal=_operator(),
            parent_asset=forged,
            content=b"orphan child",
            filename_suffix=".txt",
            declared_media_type="text/plain",
            storage_root=storage_root,
        )
    except AssetAdmissionError as error:
        assert error.code == "staged_asset_unavailable"
    else:
        raise AssertionError("forged parent receipt was accepted")


def test_child_api_enforces_event_aggregate_limits_across_repeated_calls(
    tmp_path: Path,
) -> None:
    event, parent, storage_root = _stage_parent(tmp_path)
    policy = AssetAdmissionPolicy(max_event_files=2)
    first = admit_child_asset_bytes(
        event=event,
        principal=_operator(),
        parent_asset=parent,
        content=b"first child",
        filename_suffix=".txt",
        declared_media_type="text/plain",
        storage_root=storage_root,
        policy=policy,
    )
    assert first.status == "STAGED"

    try:
        admit_child_asset_bytes(
            event=event,
            principal=_operator(),
            parent_asset=parent,
            content=b"second child",
            filename_suffix=".txt",
            declared_media_type="text/plain",
            storage_root=storage_root,
            policy=policy,
        )
    except AssetAdmissionError as error:
        assert error.code == "event_file_count_limit"
    else:
        raise AssertionError("event file-count limit was bypassed")


def test_child_event_budget_check_and_publish_are_concurrency_atomic(
    tmp_path: Path,
    monkeypatch,
) -> None:
    event, parent, storage_root = _stage_parent(tmp_path)
    policy = AssetAdmissionPolicy(max_event_files=2)
    original_usage = SecureAssetStore.event_usage
    state_lock = threading.Lock()
    active = 0
    max_active = 0

    def slow_usage(store: SecureAssetStore, parent_event_id: str):
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.05)
            return original_usage(store, parent_event_id)
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(SecureAssetStore, "event_usage", slow_usage)
    start = threading.Barrier(2)

    def admit(label: bytes) -> str:
        start.wait()
        try:
            receipt = admit_child_asset_bytes(
                event=event,
                principal=_operator(),
                parent_asset=parent,
                content=label,
                filename_suffix=".txt",
                declared_media_type="text/plain",
                storage_root=storage_root,
                policy=policy,
            )
            return receipt.status
        except AssetAdmissionError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(admit, (b"first child", b"second child")))

    assert sorted(results) == ["STAGED", "event_file_count_limit"]
    assert max_active == 1
    store = SecureAssetStore(storage_root)
    assert original_usage(store, event.event_id)[0] == 2
