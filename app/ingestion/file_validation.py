from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import stat
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ingestion.path_security import absolute_path_has_redirect, stat_is_redirect
from app.ingestion.quarantine import (
    AssetStorageError,
    IncomingAsset,
    IngestedAsset,
    SecureAssetStore,
)
from app.ingestion.source_events import MEDIA_TYPE_PATTERN, SourceEvent
from app.security.identity import Principal


class AssetAdmissionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AssetAdmissionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["asset_admission_policy_v1"] = (
        "asset_admission_policy_v1"
    )
    operator_role: Literal["rag.operator"] = "rag.operator"
    max_file_bytes: int = Field(
        default=16 * 1024 * 1024,
        ge=1,
        le=128 * 1024 * 1024,
    )
    max_event_bytes: int = Field(
        default=32 * 1024 * 1024,
        ge=1,
        le=512 * 1024 * 1024,
    )
    max_event_files: int = Field(default=32, ge=1, le=1024)
    max_docx_members: int = Field(default=2048, ge=2, le=10000)
    max_docx_member_bytes: int = Field(
        default=8 * 1024 * 1024,
        ge=1,
        le=128 * 1024 * 1024,
    )
    max_docx_total_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=1,
        le=1024 * 1024 * 1024,
    )
    max_docx_compression_ratio: float = Field(default=100.0, ge=1.0, le=1000.0)


DEFAULT_ASSET_ADMISSION_POLICY = AssetAdmissionPolicy()
_ARCHIVE_MEDIA_TYPES = frozenset(
    {
        "application/zip",
        "application/vnd.rar",
        "application/x-7z-compressed",
    }
)
_DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_ALLOWED_MEDIA_BY_SUFFIX = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".csv": "text/csv",
    ".jsonl": "application/x-ndjson",
    ".pdf": "application/pdf",
    ".docx": _DOCX_MEDIA_TYPE,
    ".eml": "message/rfc822",
}
_HTML_WITNESS = re.compile(r"(?is)^\s*(?:<!doctype\s+html\b|<html\b)")
_EMAIL_HEADER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,77}$")


def _authorize(
    *,
    event: SourceEvent,
    principal: Principal,
    policy: AssetAdmissionPolicy,
) -> None:
    if policy.operator_role not in principal.roles:
        raise AssetAdmissionError(
            "operator_role_required",
            "The authenticated principal cannot admit source assets.",
        )
    if principal.tenant_id != event.tenant_id:
        raise AssetAdmissionError(
            "tenant_mismatch",
            "The authenticated principal cannot admit this source asset.",
        )
    if principal.region != event.region:
        raise AssetAdmissionError(
            "region_mismatch",
            "The authenticated principal cannot admit this source asset.",
        )
    if event.operation != "UPSERT":
        raise AssetAdmissionError(
            "operation_not_admissible",
            "This source event does not carry an admissible asset.",
        )


def _revalidate_contracts(
    *,
    event: SourceEvent,
    principal: Principal,
    policy: AssetAdmissionPolicy,
) -> tuple[SourceEvent, Principal, AssetAdmissionPolicy]:
    try:
        validated_event = SourceEvent.model_validate(
            event.model_dump(mode="python")
        )
    except (AttributeError, ValidationError) as exc:
        raise AssetAdmissionError(
            "event_contract_invalid",
            "The source event contract is invalid.",
        ) from exc
    try:
        validated_principal = Principal.model_validate(
            principal.model_dump(mode="python")
        )
    except (AttributeError, ValidationError) as exc:
        raise AssetAdmissionError(
            "principal_contract_invalid",
            "The authenticated principal contract is invalid.",
        ) from exc
    try:
        validated_policy = AssetAdmissionPolicy.model_validate(
            policy.model_dump(mode="python")
        )
    except (AttributeError, ValidationError) as exc:
        raise AssetAdmissionError(
            "admission_policy_invalid",
            "The asset admission policy is invalid.",
        ) from exc
    return validated_event, validated_principal, validated_policy


def validate_asset_admission_context(
    *,
    event: SourceEvent,
    principal: Principal,
    policy: AssetAdmissionPolicy = DEFAULT_ASSET_ADMISSION_POLICY,
) -> tuple[SourceEvent, Principal, AssetAdmissionPolicy]:
    event, principal, policy = _revalidate_contracts(
        event=event,
        principal=principal,
        policy=policy,
    )
    _authorize(event=event, principal=principal, policy=policy)
    return event, principal, policy


def _bounded_source_path(source_root: Path, relative_path: str) -> tuple[Path, os.stat_result]:
    root = Path(source_root)
    if not root.is_absolute():
        raise AssetAdmissionError(
            "source_root_invalid",
            "The configured source root is invalid.",
        )
    try:
        redirected_root = absolute_path_has_redirect(root)
    except (OSError, ValueError) as exc:
        raise AssetAdmissionError(
            "source_root_invalid",
            "The configured source root is invalid.",
        ) from exc
    if redirected_root:
        raise AssetAdmissionError(
            "source_root_redirect",
            "The configured source root is redirected.",
        )
    try:
        root_metadata = root.lstat()
    except OSError as exc:
        raise AssetAdmissionError(
            "source_root_invalid",
            "The configured source root is invalid.",
        ) from exc
    if stat_is_redirect(root_metadata) or not stat.S_ISDIR(root_metadata.st_mode):
        raise AssetAdmissionError(
            "source_root_redirect",
            "The configured source root is redirected.",
        )

    candidate = root
    for part in PurePosixPath(relative_path).parts:
        candidate = candidate / part
        try:
            metadata = candidate.lstat()
        except OSError as exc:
            raise AssetAdmissionError(
                "source_asset_unavailable",
                "The source asset is unavailable.",
            ) from exc
        if stat_is_redirect(metadata):
            raise AssetAdmissionError(
                "source_path_redirect",
                "The source asset path is redirected.",
            )
    if not stat.S_ISREG(metadata.st_mode):
        raise AssetAdmissionError(
            "source_not_regular",
            "The source asset is not a regular file.",
        )
    if metadata.st_nlink > 1:
        raise AssetAdmissionError(
            "source_hardlink_rejected",
            "The source asset has multiple filesystem links.",
        )
    return candidate, metadata


def _require_separate_roots(source_root: Path, storage_root: Path) -> None:
    source = Path(source_root)
    storage = Path(storage_root)
    if not source.is_absolute() or not storage.is_absolute():
        return
    source_key = os.path.normcase(os.path.abspath(source))
    storage_key = os.path.normcase(os.path.abspath(storage))
    try:
        common = os.path.commonpath((source_key, storage_key))
    except ValueError:
        return
    if common in {source_key, storage_key}:
        raise AssetAdmissionError(
            "source_storage_root_overlap",
            "Source and application storage roots must be separate.",
        )


def _open_verified_source(path: Path, expected: os.stat_result) -> int:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AssetAdmissionError(
            "source_open_failed",
            "The source asset could not be opened safely.",
        ) from exc
    try:
        actual = os.fstat(descriptor)
    except OSError as exc:
        os.close(descriptor)
        raise AssetAdmissionError(
            "source_open_failed",
            "The source asset could not be opened safely.",
        ) from exc
    if (
        not stat.S_ISREG(actual.st_mode)
        or actual.st_dev != expected.st_dev
        or actual.st_ino != expected.st_ino
    ):
        os.close(descriptor)
        raise AssetAdmissionError(
            "source_changed_during_open",
            "The source asset changed during secure open.",
        )
    return descriptor


def _open_asset_store(storage_root: Path) -> SecureAssetStore:
    try:
        return SecureAssetStore(storage_root)
    except AssetStorageError as exc:
        raise AssetAdmissionError(exc.code, str(exc)) from exc


@contextmanager
def _admission_transaction(
    store: SecureAssetStore,
) -> Iterator[IncomingAsset]:
    try:
        with store.incoming() as transaction:
            yield transaction
    except AssetStorageError as exc:
        raise AssetAdmissionError(exc.code, str(exc)) from exc


def _copy_and_hash(
    descriptor: int,
    destination: Path,
    *,
    byte_limit: int,
) -> tuple[int, str]:
    output_descriptor: int | None = None
    digest = hashlib.sha256()
    total = 0
    try:
        output_descriptor = os.open(
            destination,
            os.O_CREAT
            | os.O_EXCL
            | os.O_WRONLY
            | getattr(os, "O_BINARY", 0),
            0o600,
        )
        with os.fdopen(descriptor, "rb", closefd=False) as source, os.fdopen(
            output_descriptor, "wb", closefd=False
        ) as output:
            while total <= byte_limit:
                block = source.read(min(64 * 1024, byte_limit + 1 - total))
                if not block:
                    break
                output.write(block)
                digest.update(block)
                total += len(block)
            output.flush()
            os.fsync(output.fileno())
    except (OSError, ValueError) as exc:
        raise AssetAdmissionError(
            "asset_copy_failed",
            "The source asset could not be copied safely.",
        ) from exc
    finally:
        if output_descriptor is not None:
            try:
                os.close(output_descriptor)
            except OSError:
                pass
        try:
            os.close(descriptor)
        except OSError:
            pass
    return total, digest.hexdigest()


def _detected_media_type(path: Path) -> str | None:
    content = path.read_bytes()
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "application/zip"
    if content.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")):
        return "application/vnd.rar"
    if content.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "application/x-7z-compressed"
    if _looks_like_eml_bytes(content):
        return "message/rfc822"
    if b"\x00" in content:
        return None
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if _HTML_WITNESS.match(text):
        return "text/html"
    if _looks_like_eml(text):
        return "message/rfc822"
    if _looks_like_jsonl(text):
        return "application/x-ndjson"
    if _looks_like_csv(text):
        return "text/csv"
    return "text/plain"


def _looks_like_eml_bytes(content: bytes) -> bool:
    normalized = content.replace(b"\r\n", b"\n")
    header_block, separator, _ = normalized.partition(b"\n\n")
    if not separator or len(header_block) > 64 * 1024:
        return False
    try:
        headers = header_block.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        return False
    return _looks_like_eml(f"{headers}\n\n")


def _looks_like_eml(text: str) -> bool:
    normalized = text.replace("\r\n", "\n")
    header_block, separator, _ = normalized.partition("\n\n")
    if not separator:
        return False
    lines = header_block.splitlines()
    if not lines or len(lines) > 200:
        return False
    names: set[str] = set()
    for line in lines:
        if line.startswith((" ", "\t")):
            if not names:
                return False
            continue
        name, delimiter, _ = line.partition(":")
        if not delimiter or _EMAIL_HEADER_NAME.fullmatch(name) is None:
            return False
        names.add(name.casefold())
    witnesses = {"from", "to", "subject", "date", "mime-version", "content-type"}
    return len(names & witnesses) >= 2


def _looks_like_jsonl(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines or len(lines) > 10000:
        return False
    try:
        return all(isinstance(json.loads(line), dict) for line in lines)
    except (TypeError, ValueError):
        return False


def _looks_like_csv(text: str) -> bool:
    if "," not in text:
        return False
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error:
        return False
    if len(rows) < 2 or len(rows[0]) < 2:
        return False
    width = len(rows[0])
    return all(len(row) == width for row in rows)


def _is_bounded_docx(path: Path, policy: AssetAdmissionPolicy) -> bool:
    try:
        with zipfile.ZipFile(path) as package:
            members = package.infolist()
    except (OSError, zipfile.BadZipFile):
        return False
    if not 2 <= len(members) <= policy.max_docx_members:
        return False

    names: set[str] = set()
    total_size = 0
    for member in members:
        name = member.filename
        logical_name = name[:-1] if member.is_dir() else name
        parts = logical_name.split("/")
        if (
            not logical_name
            or "\x00" in logical_name
            or "\\" in logical_name
            or logical_name.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or logical_name in names
            or member.flag_bits & 0x1
            or (member.is_dir() and member.file_size != 0)
            or member.file_size > policy.max_docx_member_bytes
        ):
            return False
        names.add(logical_name)
        total_size += member.file_size
        if total_size > policy.max_docx_total_bytes:
            return False
        if (
            member.file_size > 0
            and member.file_size / max(1, member.compress_size)
            > policy.max_docx_compression_ratio
        ):
            return False
    return {"[Content_Types].xml", "word/document.xml"}.issubset(names)


def _publish_receipt(
    *,
    store: SecureAssetStore,
    transaction: IncomingAsset,
    event: SourceEvent,
    byte_count: int,
    content_sha256: str,
    status: Literal["STAGED", "QUARANTINED"],
    reason_code: str,
    verified_media_type: str | None,
    payload_suffix: str,
    redacted_suffix: str,
    parent_asset_id: str | None = None,
    declared_media_type: str | None = None,
) -> IngestedAsset:
    destination_kind = "staged" if status == "STAGED" else "quarantine"
    effective_declared_media_type = (
        event.declared_media_type
        if declared_media_type is None
        else declared_media_type
    )
    assert effective_declared_media_type is not None
    receipt = IngestedAsset(
        asset_id=transaction.asset_id,
        parent_event_id=event.event_id,
        parent_asset_id=parent_asset_id,
        stored_relpath=(
            f"{destination_kind}/{transaction.asset_id}/payload{payload_suffix}"
        ),
        original_name_redacted=f"[redacted]{_safe_redacted_suffix(redacted_suffix)}",
        declared_media_type=effective_declared_media_type,
        verified_media_type=verified_media_type,
        byte_count=byte_count,
        content_sha256=content_sha256,
        status=status,
        reason_code=reason_code,
        created_at=datetime.now(timezone.utc),
    )
    store.commit(
        transaction,
        receipt=receipt,
        payload_suffix=payload_suffix,
    )
    return receipt


def _safe_redacted_suffix(suffix: str) -> str:
    if suffix in _ALLOWED_MEDIA_BY_SUFFIX or suffix in {
        ".zip",
        ".rar",
        ".7z",
        ".msg",
    }:
        return suffix
    return ""


def _classify_copied_asset(
    *,
    path: Path,
    suffix: str,
    declared_media_type: str,
    policy: AssetAdmissionPolicy,
) -> tuple[
    Literal["STAGED", "QUARANTINED"],
    str,
    str | None,
    str,
]:
    detected_media_type = _detected_media_type(path)
    if (
        detected_media_type == "application/zip"
        and suffix == ".docx"
        and declared_media_type == _DOCX_MEDIA_TYPE
    ):
        if not _is_bounded_docx(path, policy):
            return (
                "QUARANTINED",
                "invalid_docx_structure",
                "application/zip",
                ".blob",
            )
        detected_media_type = _DOCX_MEDIA_TYPE

    if suffix == ".msg":
        return (
            "QUARANTINED",
            "msg_not_supported",
            detected_media_type,
            ".blob",
        )
    if detected_media_type in _ARCHIVE_MEDIA_TYPES:
        return (
            "QUARANTINED",
            "archive_not_supported",
            detected_media_type,
            ".blob",
        )
    if detected_media_type is None:
        return ("QUARANTINED", "unknown_binary", None, ".blob")

    expected_media_type = _ALLOWED_MEDIA_BY_SUFFIX.get(suffix)
    if expected_media_type is None:
        reason_code = "extension_not_allowed"
    elif declared_media_type != expected_media_type:
        reason_code = "declared_media_mismatch"
    elif not (
        detected_media_type == expected_media_type
        or (
            expected_media_type == "text/markdown"
            and detected_media_type == "text/plain"
        )
    ):
        reason_code = "signature_mismatch"
    else:
        return ("STAGED", "accepted", expected_media_type, suffix)
    return ("QUARANTINED", reason_code, detected_media_type, ".blob")


def _write_bounded_bytes(
    content: bytes,
    destination: Path,
    *,
    byte_limit: int,
) -> tuple[int, str]:
    if not isinstance(content, bytes):
        raise AssetAdmissionError(
            "child_content_invalid",
            "Child asset content must be immutable bytes.",
        )
    byte_count = len(content)
    if byte_count == 0:
        raise AssetAdmissionError("empty_file", "The child asset is empty.")
    if byte_count > byte_limit:
        raise AssetAdmissionError(
            "file_size_limit",
            "The child asset exceeds the admission byte limit.",
        )
    descriptor: int | None = None
    try:
        descriptor = os.open(
            destination,
            os.O_CREAT
            | os.O_EXCL
            | os.O_WRONLY
            | getattr(os, "O_BINARY", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise AssetAdmissionError(
            "asset_copy_failed",
            "The child asset could not be copied safely.",
        ) from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
    return byte_count, hashlib.sha256(content).hexdigest()


def admit_child_asset_bytes(
    *,
    event: SourceEvent,
    principal: Principal,
    parent_asset: IngestedAsset,
    content: bytes,
    filename_suffix: str,
    declared_media_type: str,
    storage_root: Path,
    policy: AssetAdmissionPolicy = DEFAULT_ASSET_ADMISSION_POLICY,
) -> IngestedAsset:
    event, principal, policy = validate_asset_admission_context(
        event=event,
        principal=principal,
        policy=policy,
    )
    try:
        parent = IngestedAsset.model_validate(
            parent_asset.model_dump(mode="python")
        )
    except (AttributeError, ValidationError) as exc:
        raise AssetAdmissionError(
            "parent_asset_contract_invalid",
            "The parent asset receipt is invalid.",
        ) from exc
    if parent.parent_event_id != event.event_id:
        raise AssetAdmissionError(
            "parent_event_mismatch",
            "The child asset parent does not belong to this event.",
        )
    if parent.status != "STAGED":
        raise AssetAdmissionError(
            "staged_parent_required",
            "A staged parent asset is required.",
        )
    if not isinstance(content, bytes):
        raise AssetAdmissionError(
            "child_content_invalid",
            "Child asset content must be immutable bytes.",
        )
    suffix = filename_suffix.casefold()
    if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) is None:
        suffix = ""
    media_type = declared_media_type.casefold()
    if MEDIA_TYPE_PATTERN.fullmatch(media_type) is None:
        raise AssetAdmissionError(
            "declared_media_type_invalid",
            "The child declared media type is invalid.",
        )

    store = _open_asset_store(storage_root)
    try:
        with store.event_admission_lock(event.event_id):
            store.read_staged(parent, byte_limit=max(1, parent.byte_count))
            event_file_count, event_byte_count = store.event_usage(event.event_id)
            if event_file_count + 1 > policy.max_event_files:
                raise AssetAdmissionError(
                    "event_file_count_limit",
                    "The child asset exceeds the event file-count limit.",
                )
            if event_byte_count + len(content) > policy.max_event_bytes:
                raise AssetAdmissionError(
                    "event_byte_limit",
                    "The child asset exceeds the event byte limit.",
                )
            limit = min(policy.max_file_bytes, policy.max_event_bytes)
            with _admission_transaction(store) as transaction:
                byte_count, content_sha256 = _write_bounded_bytes(
                    content,
                    transaction.payload_path,
                    byte_limit=limit,
                )
                status, reason_code, verified_media_type, payload_suffix = (
                    _classify_copied_asset(
                        path=transaction.payload_path,
                        suffix=suffix,
                        declared_media_type=media_type,
                        policy=policy,
                    )
                )
                return _publish_receipt(
                    store=store,
                    transaction=transaction,
                    event=event,
                    byte_count=byte_count,
                    content_sha256=content_sha256,
                    status=status,
                    reason_code=reason_code,
                    verified_media_type=verified_media_type,
                    payload_suffix=payload_suffix,
                    redacted_suffix=suffix,
                    parent_asset_id=parent.asset_id,
                    declared_media_type=media_type,
                )
    except AssetStorageError as exc:
        raise AssetAdmissionError(exc.code, str(exc)) from exc


def admit_source_event_asset(
    *,
    event: SourceEvent,
    principal: Principal,
    source_root: Path,
    storage_root: Path,
    policy: AssetAdmissionPolicy = DEFAULT_ASSET_ADMISSION_POLICY,
) -> IngestedAsset:
    event, principal, policy = validate_asset_admission_context(
        event=event,
        principal=principal,
        policy=policy,
    )
    _require_separate_roots(source_root, storage_root)
    assert event.content_relpath is not None
    assert event.declared_media_type is not None
    assert event.content_sha256 is not None
    source_path, source_metadata = _bounded_source_path(
        source_root,
        event.content_relpath,
    )
    store = _open_asset_store(storage_root)
    limit = min(policy.max_file_bytes, policy.max_event_bytes)

    with _admission_transaction(store) as transaction:
        descriptor = _open_verified_source(source_path, source_metadata)
        byte_count, content_sha256 = _copy_and_hash(
            descriptor,
            transaction.payload_path,
            byte_limit=limit,
        )
        if byte_count == 0:
            raise AssetAdmissionError(
                "empty_file",
                "The source asset is empty.",
            )
        if byte_count > limit:
            raise AssetAdmissionError(
                "file_size_limit",
                "The source asset exceeds the admission byte limit.",
            )
        suffix = PurePosixPath(event.content_relpath).suffix.lower()
        detected_media_type = _detected_media_type(transaction.payload_path)
        if content_sha256 != event.content_sha256:
            return _publish_receipt(
                store=store,
                transaction=transaction,
                event=event,
                byte_count=byte_count,
                content_sha256=content_sha256,
                status="QUARANTINED",
                reason_code="content_hash_mismatch",
                verified_media_type=detected_media_type,
                payload_suffix=".blob",
                redacted_suffix=suffix,
            )
        status, reason_code, verified_media_type, payload_suffix = (
            _classify_copied_asset(
                path=transaction.payload_path,
                suffix=suffix,
                declared_media_type=event.declared_media_type,
                policy=policy,
            )
        )
        return _publish_receipt(
            store=store,
            transaction=transaction,
            event=event,
            byte_count=byte_count,
            content_sha256=content_sha256,
            status=status,
            reason_code=reason_code,
            verified_media_type=verified_media_type,
            payload_suffix=payload_suffix,
            redacted_suffix=suffix,
        )


__all__ = [
    "AssetAdmissionError",
    "AssetAdmissionPolicy",
    "DEFAULT_ASSET_ADMISSION_POLICY",
    "IngestedAsset",
    "admit_child_asset_bytes",
    "admit_source_event_asset",
    "validate_asset_admission_context",
]
