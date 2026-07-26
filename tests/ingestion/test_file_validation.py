from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import filesystem as filesystem_module
from app.ingestion.file_validation import (
    AssetAdmissionError,
    AssetAdmissionPolicy,
    admit_source_event_asset,
)
from app.ingestion import quarantine as quarantine_module
from app.ingestion.quarantine import IngestedAsset
from app.ingestion.source_events import SourceEvent
from app.security.identity import Principal


def _operator(
    *,
    tenant_id: str = "tenant-a",
    region: str = "cn-east",
    roles: list[str] | None = None,
) -> Principal:
    now = datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc)
    return Principal(
        subject="operator-001",
        tenant_id=tenant_id,
        region=region,
        groups=["knowledge-admin"],
        roles=["rag.operator"] if roles is None else roles,
        issuer="https://identity.example.invalid",
        audience="rag-copilot",
        key_id="demo-key-001",
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )


def _upsert_event(
    *,
    content_relpath: str,
    declared_media_type: str,
    content: bytes,
    expected_content: bytes | None = None,
) -> SourceEvent:
    return SourceEvent(
        event_id="evt-g3-001",
        operation="UPSERT",
        tenant_id="tenant-a",
        region="cn-east",
        source_system="enterprise-drop",
        source_key="policies/leave",
        occurred_at=datetime(2026, 7, 26, 8, 5, tzinfo=timezone.utc),
        content_relpath=content_relpath,
        declared_media_type=declared_media_type,
        content_sha256=hashlib.sha256(
            content if expected_content is None else expected_content
        ).hexdigest(),
        actor_pseudonym="actor-001",
        acl_groups=("hr-readers",),
    )


def test_authorized_pdf_is_staged_with_bound_redacted_receipt(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    source_root.mkdir()
    content = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
    source = source_root / "Quarterly-Leave-Policy.pdf"
    source.write_bytes(content)
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type="application/pdf",
        content=content,
    )

    receipt = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )

    assert receipt.status == "STAGED"
    assert receipt.reason_code == "accepted"
    assert receipt.parent_event_id == event.event_id
    assert receipt.parent_asset_id is None
    assert receipt.declared_media_type == "application/pdf"
    assert receipt.verified_media_type == "application/pdf"
    assert receipt.byte_count == len(content)
    assert receipt.content_sha256 == hashlib.sha256(content).hexdigest()
    assert receipt.original_name_redacted == "[redacted].pdf"
    assert receipt.stored_relpath is not None
    assert re.fullmatch(
        r"staged/asset_[0-9a-f]{32}/payload\.pdf",
        receipt.stored_relpath,
    )

    asset_directory = storage_root / Path(receipt.stored_relpath).parent
    assert (storage_root / receipt.stored_relpath).read_bytes() == content
    stored_receipt = json.loads(
        (asset_directory / "receipt.json").read_text(encoding="utf-8")
    )
    assert stored_receipt == receipt.model_dump(mode="json")
    serialized = json.dumps(stored_receipt, sort_keys=True)
    assert source.name not in serialized
    assert str(source_root) not in serialized
    assert content.decode("ascii") not in serialized
    assert list((storage_root / ".incoming").iterdir()) == []


def test_signature_spoof_is_quarantined_as_non_parseable_blob(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    source_root.mkdir()
    content = b"This is plain text disguised with a PDF suffix.\n"
    source = source_root / "disguised.pdf"
    source.write_bytes(content)
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type="application/pdf",
        content=content,
    )

    receipt = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )

    assert receipt.status == "QUARANTINED"
    assert receipt.reason_code == "signature_mismatch"
    assert receipt.verified_media_type == "text/plain"
    assert receipt.stored_relpath is not None
    assert re.fullmatch(
        r"quarantine/asset_[0-9a-f]{32}/payload\.blob",
        receipt.stored_relpath,
    )
    assert (storage_root / receipt.stored_relpath).read_bytes() == content
    assert list((storage_root / "staged").iterdir()) == []
    assert list((storage_root / ".incoming").iterdir()) == []


def test_event_content_hash_mismatch_is_quarantined(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    source_root.mkdir()
    content = b"%PDF-1.4\n%%EOF\n"
    source = source_root / "changed-after-event.pdf"
    source.write_bytes(content)
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type="application/pdf",
        content=content,
        expected_content=b"%PDF-1.4\noriginal event bytes\n%%EOF\n",
    )

    receipt = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )

    assert receipt.status == "QUARANTINED"
    assert receipt.reason_code == "content_hash_mismatch"
    assert receipt.verified_media_type == "application/pdf"
    assert receipt.content_sha256 == hashlib.sha256(content).hexdigest()
    assert receipt.stored_relpath is not None
    assert receipt.stored_relpath.endswith("/payload.blob")
    assert (storage_root / receipt.stored_relpath).read_bytes() == content


@pytest.mark.parametrize(
    ("principal", "expected_code"),
    [
        (_operator(roles=[]), "operator_role_required"),
        (_operator(tenant_id="tenant-b"), "tenant_mismatch"),
        (_operator(region="eu-west"), "region_mismatch"),
    ],
)
def test_authorization_fails_before_source_or_storage_access(
    tmp_path: Path,
    principal: Principal,
    expected_code: str,
) -> None:
    content = b"%PDF-1.4\n%%EOF\n"
    event = _upsert_event(
        content_relpath="not-present.pdf",
        declared_media_type="application/pdf",
        content=content,
    )
    source_root = tmp_path / "source-must-not-be-touched"
    storage_root = tmp_path / "storage-must-not-be-created"

    with pytest.raises(AssetAdmissionError) as captured:
        admit_source_event_asset(
            event=event,
            principal=principal,
            source_root=source_root,
            storage_root=storage_root,
        )

    assert captured.value.code == expected_code
    assert not source_root.exists()
    assert not storage_root.exists()


@pytest.mark.parametrize(
    ("content", "policy", "expected_code"),
    [
        (b"", AssetAdmissionPolicy(), "empty_file"),
        (
            b"%PDF-1.4\noversized\n%%EOF\n",
            AssetAdmissionPolicy(max_file_bytes=8, max_event_bytes=8),
            "file_size_limit",
        ),
    ],
)
def test_resource_rejection_removes_every_partial_asset(
    tmp_path: Path,
    content: bytes,
    policy: AssetAdmissionPolicy,
    expected_code: str,
) -> None:
    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    source_root.mkdir()
    source = source_root / "bounded.pdf"
    source.write_bytes(content)
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type="application/pdf",
        content=content,
    )

    with pytest.raises(AssetAdmissionError) as captured:
        admit_source_event_asset(
            event=event,
            principal=_operator(),
            source_root=source_root,
            storage_root=storage_root,
            policy=policy,
        )

    assert captured.value.code == expected_code
    assert str(source_root) not in str(captured.value)
    assert source.name not in str(captured.value)
    assert list((storage_root / ".incoming").iterdir()) == []
    assert list((storage_root / "staged").iterdir()) == []
    assert list((storage_root / "quarantine").iterdir()) == []


def test_unknown_binary_is_quarantined_with_specific_reason(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    source_root.mkdir()
    content = b"\x00\xff\x10\x80unknown-binary"
    source = source_root / "unknown.pdf"
    source.write_bytes(content)
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type="application/pdf",
        content=content,
    )

    receipt = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )

    assert receipt.status == "QUARANTINED"
    assert receipt.reason_code == "unknown_binary"
    assert receipt.verified_media_type is None
    assert receipt.stored_relpath is not None
    assert receipt.stored_relpath.endswith("/payload.blob")


def test_zip_archive_is_quarantined_without_extraction(
    tmp_path: Path,
) -> None:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as package:
        package.writestr("nested.txt", "archive body must not be extracted")
    content = archive.getvalue()
    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    source_root.mkdir()
    source = source_root / "unsupported.zip"
    source.write_bytes(content)
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type="application/zip",
        content=content,
    )

    receipt = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )

    assert receipt.status == "QUARANTINED"
    assert receipt.reason_code == "archive_not_supported"
    assert receipt.verified_media_type == "application/zip"
    assert receipt.stored_relpath is not None
    quarantined_directory = (
        storage_root / Path(receipt.stored_relpath).parent
    )
    assert (quarantined_directory / "payload.blob").read_bytes() == content
    assert not (quarantined_directory / "nested.txt").exists()


def test_structurally_valid_docx_is_staged_as_ooxml(
    tmp_path: Path,
) -> None:
    package_bytes = io.BytesIO()
    with zipfile.ZipFile(
        package_bytes,
        "w",
        compression=zipfile.ZIP_STORED,
    ) as package:
        package.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        package.writestr("word/", b"")
        package.writestr(
            "word/document.xml",
            '<w:document xmlns:w="urn:test"><w:body/></w:document>',
        )
    content = package_bytes.getvalue()
    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    source_root.mkdir()
    source = source_root / "policy.docx"
    source.write_bytes(content)
    media_type = (
        "application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document"
    )
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type=media_type,
        content=content,
    )

    receipt = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )

    assert receipt.status == "STAGED"
    assert receipt.reason_code == "accepted"
    assert receipt.verified_media_type == media_type
    assert receipt.stored_relpath is not None
    assert receipt.stored_relpath.endswith("/payload.docx")
    assert (storage_root / receipt.stored_relpath).read_bytes() == content


@pytest.mark.parametrize(
    ("suffix", "declared_media_type", "content"),
    [
        (".txt", "text/plain", b"Fictional policy text.\n"),
        (".md", "text/markdown", b"# Fictional Policy\n\nBody text.\n"),
        (
            ".html",
            "text/html",
            b"<!doctype html><html><body><p>Policy</p></body></html>",
        ),
        (".csv", "text/csv", b"name,value\nalpha,1\n"),
        (
            ".jsonl",
            "application/x-ndjson",
            b'{"name":"alpha","value":1}\n',
        ),
        (
            ".eml",
            "message/rfc822",
            (
                b"From: sender@example.invalid\r\n"
                b"To: receiver@example.invalid\r\n"
                b"Subject: Fictional policy\r\n"
                b"MIME-Version: 1.0\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n"
                b"\r\n"
                b"Fictional message body.\r\n"
            ),
        ),
    ],
)
def test_allowed_textual_family_is_staged_after_bounded_detection(
    tmp_path: Path,
    suffix: str,
    declared_media_type: str,
    content: bytes,
) -> None:
    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    source_root.mkdir()
    source = source_root / f"fictional{suffix}"
    source.write_bytes(content)
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type=declared_media_type,
        content=content,
    )

    receipt = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )

    assert receipt.status == "STAGED"
    assert receipt.reason_code == "accepted"
    assert receipt.verified_media_type == declared_media_type
    assert receipt.stored_relpath is not None
    assert receipt.stored_relpath.endswith(f"/payload{suffix}")
    assert (storage_root / receipt.stored_relpath).read_bytes() == content


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_source_root_below_windows_junction_is_rejected(
    tmp_path: Path,
) -> None:
    actual_parent = tmp_path / "actual-parent"
    source_root = actual_parent / "source"
    source_root.mkdir(parents=True)
    content = b"%PDF-1.4\n%%EOF\n"
    source = source_root / "policy.pdf"
    source.write_bytes(content)
    junction = tmp_path / "redirected-parent"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(actual_parent)],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip("Windows junction creation is unavailable")
    redirected_root = junction / "source"
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type="application/pdf",
        content=content,
    )
    storage_root = tmp_path / "asset-store"

    try:
        with pytest.raises(AssetAdmissionError) as captured:
            admit_source_event_asset(
                event=event,
                principal=_operator(),
                source_root=redirected_root,
                storage_root=storage_root,
            )
        assert captured.value.code == "source_root_redirect"
        assert not storage_root.exists()
    finally:
        if junction.exists():
            os.rmdir(junction)


def test_admission_revalidates_forged_source_event_before_path_access(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    outside = tmp_path / "outside.pdf"
    content = b"%PDF-1.4\n%%EOF\n"
    outside.write_bytes(content)
    valid_event = _upsert_event(
        content_relpath="inside.pdf",
        declared_media_type="application/pdf",
        content=content,
    )
    forged_event = valid_event.model_copy(
        update={"content_relpath": "../outside.pdf"}
    )
    storage_root = tmp_path / "asset-store"

    with pytest.raises(AssetAdmissionError) as captured:
        admit_source_event_asset(
            event=forged_event,
            principal=_operator(),
            source_root=source_root,
            storage_root=storage_root,
        )

    assert captured.value.code == "event_contract_invalid"
    assert not storage_root.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_storage_root_below_windows_junction_is_rejected_as_admission_error(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    content = b"%PDF-1.4\n%%EOF\n"
    source = source_root / "policy.pdf"
    source.write_bytes(content)
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type="application/pdf",
        content=content,
    )
    actual_parent = tmp_path / "actual-storage-parent"
    actual_store = actual_parent / "asset-store"
    actual_store.mkdir(parents=True)
    junction = tmp_path / "redirected-storage-parent"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(actual_parent)],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip("Windows junction creation is unavailable")
    redirected_store = junction / "asset-store"

    try:
        with pytest.raises(AssetAdmissionError) as captured:
            admit_source_event_asset(
                event=event,
                principal=_operator(),
                source_root=source_root,
                storage_root=redirected_store,
            )
        assert captured.value.code == "storage_root_redirect"
        assert str(actual_parent) not in str(captured.value)
        assert list(actual_store.iterdir()) == []
    finally:
        if junction.exists():
            os.rmdir(junction)


def test_publication_failure_is_safe_and_removes_incoming_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    source_root.mkdir()
    content = b"%PDF-1.4\n%%EOF\n"
    source = source_root / "policy.pdf"
    source.write_bytes(content)
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type="application/pdf",
        content=content,
    )

    def fail_publication(source_path: Path, destination_path: Path) -> None:
        raise OSError("synthetic publication failure")

    monkeypatch.setattr(
        quarantine_module,
        "atomic_directory_move",
        fail_publication,
    )

    with pytest.raises(AssetAdmissionError) as captured:
        admit_source_event_asset(
            event=event,
            principal=_operator(),
            source_root=source_root,
            storage_root=storage_root,
        )

    assert captured.value.code == "storage_publish_failed"
    assert str(storage_root) not in str(captured.value)
    assert source.name not in str(captured.value)
    assert list((storage_root / ".incoming").iterdir()) == []
    assert list((storage_root / "staged").iterdir()) == []
    assert list((storage_root / "quarantine").iterdir()) == []


def test_windows_transient_publication_denial_is_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    source_root.mkdir()
    content = b"%PDF-1.4\n%%EOF\n"
    source = source_root / "policy.pdf"
    source.write_bytes(content)
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type="application/pdf",
        content=content,
    )
    original_move = filesystem_module._move_once
    calls = 0

    def transient_denial(
        source_path: Path,
        destination_path: Path,
        *,
        replace: bool,
    ) -> None:
        nonlocal calls
        calls += 1
        if calls <= 2:
            error = PermissionError(13, "synthetic sharing denial")
            error.winerror = 5
            raise error
        original_move(source_path, destination_path, replace=replace)

    monkeypatch.setattr(filesystem_module, "_move_once", transient_denial)

    receipt = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )

    assert receipt.status == "STAGED"
    assert 3 <= calls <= filesystem_module._WINDOWS_DIRECTORY_MOVE_ATTEMPTS
    assert receipt.stored_relpath is not None
    assert (storage_root / receipt.stored_relpath).read_bytes() == content
    assert list((storage_root / ".incoming").iterdir()) == []


@pytest.mark.parametrize(
    (
        "suffix",
        "declared_media_type",
        "content",
        "expected_code",
        "verified_media_type",
    ),
    [
        (
            ".exe",
            "text/plain",
            b"printable but unsupported\n",
            "extension_not_allowed",
            "text/plain",
        ),
        (
            ".pdf",
            "text/plain",
            b"%PDF-1.4\n%%EOF\n",
            "declared_media_mismatch",
            "application/pdf",
        ),
        (
            ".txt",
            "text/plain",
            b"<!doctype html><html><body>markup</body></html>",
            "signature_mismatch",
            "text/html",
        ),
        (
            ".docx",
            (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            b"PK\x03\x04not-a-valid-ooxml-directory",
            "invalid_docx_structure",
            "application/zip",
        ),
    ],
)
def test_type_disagreement_has_deterministic_quarantine_reason(
    tmp_path: Path,
    suffix: str,
    declared_media_type: str,
    content: bytes,
    expected_code: str,
    verified_media_type: str,
) -> None:
    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    source_root.mkdir()
    source = source_root / f"fixture{suffix}"
    source.write_bytes(content)
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type=declared_media_type,
        content=content,
    )

    receipt = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )

    assert receipt.status == "QUARANTINED"
    assert receipt.reason_code == expected_code
    assert receipt.verified_media_type == verified_media_type
    assert receipt.stored_relpath is not None
    assert receipt.stored_relpath.endswith("/payload.blob")


@pytest.mark.parametrize(
    ("suffix", "declared_media_type", "content", "verified_media_type"),
    [
        (
            ".rar",
            "application/vnd.rar",
            b"Rar!\x1a\x07\x00synthetic",
            "application/vnd.rar",
        ),
        (
            ".7z",
            "application/x-7z-compressed",
            b"7z\xbc\xaf\x27\x1csynthetic",
            "application/x-7z-compressed",
        ),
    ],
)
def test_non_zip_archive_signatures_are_quarantined(
    tmp_path: Path,
    suffix: str,
    declared_media_type: str,
    content: bytes,
    verified_media_type: str,
) -> None:
    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    source_root.mkdir()
    source = source_root / f"archive{suffix}"
    source.write_bytes(content)
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type=declared_media_type,
        content=content,
    )

    receipt = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )

    assert receipt.status == "QUARANTINED"
    assert receipt.reason_code == "archive_not_supported"
    assert receipt.verified_media_type == verified_media_type


def test_symbolic_link_source_escape_is_rejected_when_supported(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    content = b"%PDF-1.4\n%%EOF\n"
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(content)
    linked = source_root / "linked.pdf"
    try:
        linked.symlink_to(outside)
    except OSError:
        pytest.skip("symbolic-link creation is unavailable")
    event = _upsert_event(
        content_relpath=linked.name,
        declared_media_type="application/pdf",
        content=content,
    )
    storage_root = tmp_path / "asset-store"

    with pytest.raises(AssetAdmissionError) as captured:
        admit_source_event_asset(
            event=event,
            principal=_operator(),
            source_root=source_root,
            storage_root=storage_root,
        )

    assert captured.value.code == "source_path_redirect"
    assert not storage_root.exists()


def test_hardlinked_source_is_rejected(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    content = b"%PDF-1.4\n%%EOF\n"
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(content)
    linked = source_root / "hardlinked.pdf"
    try:
        os.link(outside, linked)
    except OSError:
        pytest.skip("hard-link creation is unavailable")
    event = _upsert_event(
        content_relpath=linked.name,
        declared_media_type="application/pdf",
        content=content,
    )
    storage_root = tmp_path / "asset-store"

    with pytest.raises(AssetAdmissionError) as captured:
        admit_source_event_asset(
            event=event,
            principal=_operator(),
            source_root=source_root,
            storage_root=storage_root,
        )

    assert captured.value.code == "source_hardlink_rejected"
    assert not storage_root.exists()


def test_file_identity_change_between_lstat_and_open_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    content = b"%PDF-1.4\noriginal\n%%EOF\n"
    replacement_content = b"%PDF-1.4\nreplacement\n%%EOF\n"
    source = source_root / "policy.pdf"
    replacement = source_root / "replacement.pdf"
    source.write_bytes(content)
    replacement.write_bytes(replacement_content)
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type="application/pdf",
        content=content,
    )
    storage_root = tmp_path / "asset-store"
    real_open = os.open

    def switched_open(path, flags, mode=0o777):
        target = Path(path)
        if target == source:
            return real_open(replacement, flags, mode)
        return real_open(path, flags, mode)

    monkeypatch.setattr("app.ingestion.file_validation.os.open", switched_open)

    with pytest.raises(AssetAdmissionError) as captured:
        admit_source_event_asset(
            event=event,
            principal=_operator(),
            source_root=source_root,
            storage_root=storage_root,
        )

    assert captured.value.code == "source_changed_during_open"
    assert list((storage_root / ".incoming").iterdir()) == []
    assert list((storage_root / "staged").iterdir()) == []
    assert list((storage_root / "quarantine").iterdir()) == []


def test_quarantine_does_not_invoke_parser_or_change_index_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ingestion.parsers import ParserRegistry

    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    index_root = tmp_path / "indexes"
    source_root.mkdir()
    index_root.mkdir()
    active = index_root / "active.json"
    active_bytes = b'{"schema_version":"index_active_pointer_v1","run_id":"old"}\n'
    active.write_bytes(active_bytes)
    content = b"plain text disguised as PDF\n"
    source = source_root / "disguised.pdf"
    source.write_bytes(content)
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type="application/pdf",
        content=content,
    )
    parser_calls = 0

    def fail_if_called(self, path):
        nonlocal parser_calls
        parser_calls += 1
        raise AssertionError("parser must not run during admission")

    monkeypatch.setattr(ParserRegistry, "parse", fail_if_called)

    receipt = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )

    assert receipt.status == "QUARANTINED"
    assert parser_calls == 0
    assert active.read_bytes() == active_bytes
    assert list(index_root.iterdir()) == [active]


def test_repeated_admission_uses_distinct_unpredictable_names(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    source_root.mkdir()
    content = b"%PDF-1.4\n%%EOF\n"
    source = source_root / "sensitive-original-name.pdf"
    source.write_bytes(content)
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type="application/pdf",
        content=content,
    )

    first = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )
    second = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )

    assert first.asset_id != second.asset_id
    assert first.stored_relpath != second.stored_relpath
    assert source.stem not in first.model_dump_json()
    assert source.stem not in second.model_dump_json()
    assert len(list((storage_root / "staged").iterdir())) == 2


def test_ingested_asset_rejects_cross_field_receipt_contradictions(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    source_root.mkdir()
    content = b"%PDF-1.4\n%%EOF\n"
    source = source_root / "policy.pdf"
    source.write_bytes(content)
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type="application/pdf",
        content=content,
    )
    receipt = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )
    contradictory = receipt.model_dump(mode="python")
    contradictory.update(
        {
            "status": "STAGED",
            "reason_code": "signature_mismatch",
            "stored_relpath": (
                f"quarantine/{receipt.asset_id}/payload.blob"
            ),
        }
    )

    with pytest.raises(ValidationError):
        IngestedAsset.model_validate(contradictory)


def test_untrusted_long_extension_is_not_preserved_in_redacted_name(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    storage_root = tmp_path / "asset-store"
    source_root.mkdir()
    content = b"unsupported but printable content\n"
    source = source_root / "record.highlyconfidentialtype"
    source.write_bytes(content)
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type="text/plain",
        content=content,
    )

    receipt = admit_source_event_asset(
        event=event,
        principal=_operator(),
        source_root=source_root,
        storage_root=storage_root,
    )

    assert receipt.status == "QUARANTINED"
    assert receipt.reason_code == "extension_not_allowed"
    assert receipt.original_name_redacted == "[redacted]"


def test_source_and_storage_roots_cannot_overlap(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    content = b"%PDF-1.4\n%%EOF\n"
    source = source_root / "policy.pdf"
    source.write_bytes(content)
    event = _upsert_event(
        content_relpath=source.name,
        declared_media_type="application/pdf",
        content=content,
    )
    storage_root = source_root / "application-owned-store"

    with pytest.raises(AssetAdmissionError) as captured:
        admit_source_event_asset(
            event=event,
            principal=_operator(),
            source_root=source_root,
            storage_root=storage_root,
        )

    assert captured.value.code == "source_storage_root_overlap"
    assert not storage_root.exists()
