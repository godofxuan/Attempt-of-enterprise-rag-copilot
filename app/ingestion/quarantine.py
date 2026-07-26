from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import shutil
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterator, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.ingestion.path_security import absolute_path_has_redirect, stat_is_redirect
from app.filesystem import atomic_directory_move

AssetStatus = Literal["STAGED", "QUARANTINED", "REJECTED"]
_REDACTED_NAME = re.compile(r"^\[redacted\](?:\.[a-z0-9]{1,10})?$")


class AssetStorageError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class IngestedAsset(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

    schema_version: Literal["ingested_asset_v1"] = "ingested_asset_v1"
    asset_id: str = Field(pattern=r"^asset_[0-9a-f]{32}$")
    parent_event_id: str = Field(min_length=1, max_length=128)
    parent_asset_id: str | None = Field(default=None, max_length=128)
    stored_relpath: str | None = Field(default=None, max_length=512)
    original_name_redacted: str = Field(min_length=1, max_length=64)
    declared_media_type: str = Field(min_length=1, max_length=128)
    verified_media_type: str | None = Field(default=None, max_length=128)
    byte_count: int = Field(ge=0)
    content_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    status: AssetStatus
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    created_at: datetime

    @field_validator("stored_relpath")
    @classmethod
    def validate_stored_relpath(cls, value: str | None) -> str | None:
        if value is None:
            return None
        path = PurePosixPath(value)
        if (
            "\x00" in value
            or "\\" in value
            or ":" in value
            or path.is_absolute()
            or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("stored_relpath must be canonical and relative")
        return value

    @field_validator("original_name_redacted")
    @classmethod
    def validate_redacted_name(cls, value: str) -> str:
        if _REDACTED_NAME.fullmatch(value) is None:
            raise ValueError("original_name_redacted is not safely redacted")
        return value

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_disposition_shape(self) -> IngestedAsset:
        if self.status == "STAGED":
            expected_prefix = f"staged/{self.asset_id}/payload."
            if (
                self.reason_code != "accepted"
                or self.stored_relpath is None
                or not self.stored_relpath.startswith(expected_prefix)
                or self.stored_relpath.endswith(".blob")
                or self.verified_media_type is None
                or self.content_sha256 is None
                or self.byte_count == 0
            ):
                raise ValueError("staged receipt fields are inconsistent")
        elif self.status == "QUARANTINED":
            if (
                self.reason_code == "accepted"
                or self.stored_relpath
                != f"quarantine/{self.asset_id}/payload.blob"
                or self.content_sha256 is None
                or self.byte_count == 0
            ):
                raise ValueError("quarantined receipt fields are inconsistent")
        elif (
            self.reason_code == "accepted"
            or self.stored_relpath is not None
            or self.content_sha256 is not None
        ):
            raise ValueError("rejected receipt fields are inconsistent")
        return self


@dataclass(frozen=True)
class IncomingAsset:
    asset_id: str
    directory: Path
    payload_path: Path


def _canonical_receipt_bytes(receipt: IngestedAsset) -> bytes:
    return (
        json.dumps(
            receipt.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


class SecureAssetStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        if not self.root.is_absolute():
            raise AssetStorageError(
                "storage_root_invalid",
                "The configured asset storage root is invalid.",
            )
        self._prepare_root()

    def _prepare_root(self) -> None:
        try:
            self._prepare_root_unchecked()
        except AssetStorageError:
            raise
        except (OSError, ValueError) as exc:
            raise AssetStorageError(
                "storage_root_invalid",
                "The configured asset storage root is invalid.",
            ) from exc

    def _prepare_root_unchecked(self) -> None:
        existing = self.root
        while not existing.exists() and existing != existing.parent:
            existing = existing.parent
        if absolute_path_has_redirect(existing):
            raise AssetStorageError(
                "storage_root_redirect",
                "The configured asset storage root is redirected.",
            )
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if (
            absolute_path_has_redirect(self.root)
            or stat_is_redirect(self.root.lstat())
            or not self.root.is_dir()
        ):
            raise AssetStorageError(
                "storage_root_redirect",
                "The configured asset storage root is redirected.",
            )
        for name in (".incoming", ".locks", "staged", "quarantine"):
            directory = self.root / name
            directory.mkdir(exist_ok=True, mode=0o700)
            if (
                absolute_path_has_redirect(directory)
                or stat_is_redirect(directory.lstat())
                or not directory.is_dir()
            ):
                raise AssetStorageError(
                    "storage_root_redirect",
                    "The configured asset storage root is redirected.",
                )

    @contextmanager
    def event_admission_lock(self, parent_event_id: str) -> Iterator[None]:
        lock_name = hashlib.sha256(parent_event_id.encode("utf-8")).hexdigest()
        lock_path = self.root / ".locks" / f"event_{lock_name}.lock"
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        locked = False
        try:
            if lock_path.exists() and stat_is_redirect(lock_path.lstat()):
                raise AssetStorageError(
                    "event_lock_redirect",
                    "The event admission lock is redirected.",
                )
            descriptor = os.open(lock_path, flags, 0o600)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink > 1:
                raise AssetStorageError(
                    "event_lock_redirect",
                    "The event admission lock is not a private regular file.",
                )
            if metadata.st_size == 0:
                os.write(descriptor, b"\x00")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = True
            yield
        except AssetStorageError:
            raise
        except OSError as exc:
            raise AssetStorageError(
                "event_lock_failed",
                "The event admission lock could not be acquired safely.",
            ) from exc
        finally:
            if descriptor is not None:
                if locked:
                    try:
                        os.lseek(descriptor, 0, os.SEEK_SET)
                        if os.name == "nt":
                            import msvcrt

                            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl

                            fcntl.flock(descriptor, fcntl.LOCK_UN)
                    except OSError:
                        pass
                os.close(descriptor)

    @contextmanager
    def incoming(self) -> Iterator[IncomingAsset]:
        incoming_root = self.root / ".incoming"
        transaction: IncomingAsset | None = None
        for _ in range(16):
            asset_id = f"asset_{secrets.token_hex(16)}"
            directory = incoming_root / asset_id
            try:
                directory.mkdir(mode=0o700)
            except FileExistsError:
                continue
            except OSError as exc:
                raise AssetStorageError(
                    "storage_allocate_failed",
                    "An incoming asset transaction could not be allocated.",
                ) from exc
            transaction = IncomingAsset(
                asset_id=asset_id,
                directory=directory,
                payload_path=directory / "payload.part",
            )
            break
        if transaction is None:
            raise AssetStorageError(
                "asset_name_exhausted",
                "A unique asset storage name could not be allocated.",
            )
        try:
            yield transaction
        finally:
            if transaction.directory.exists():
                try:
                    resolved = transaction.directory.resolve(strict=True)
                    incoming_resolved = incoming_root.resolve(strict=True)
                    resolved.relative_to(incoming_resolved)
                    shutil.rmtree(resolved)
                except (OSError, ValueError) as exc:
                    raise AssetStorageError(
                        "storage_cleanup_failed",
                        "The incoming asset transaction could not be cleaned safely.",
                    ) from exc

    def commit(
        self,
        transaction: IncomingAsset,
        *,
        receipt: IngestedAsset,
        payload_suffix: str,
    ) -> None:
        if receipt.asset_id != transaction.asset_id:
            raise AssetStorageError(
                "asset_identity_mismatch",
                "The asset receipt identity does not match its transaction.",
            )
        destination_kind = (
            "staged" if receipt.status == "STAGED" else "quarantine"
        )
        expected_relpath = (
            f"{destination_kind}/{receipt.asset_id}/payload{payload_suffix}"
        )
        if receipt.stored_relpath != expected_relpath:
            raise AssetStorageError(
                "asset_path_mismatch",
                "The asset receipt path does not match its transaction.",
            )

        try:
            payload = transaction.directory / f"payload{payload_suffix}"
            os.replace(transaction.payload_path, payload)
            receipt_path = transaction.directory / "receipt.json"
            receipt_bytes = _canonical_receipt_bytes(receipt)
            descriptor = os.open(
                receipt_path,
                os.O_CREAT
                | os.O_EXCL
                | os.O_WRONLY
                | getattr(os, "O_BINARY", 0),
                0o600,
            )
            try:
                with os.fdopen(descriptor, "wb", closefd=False) as stream:
                    stream.write(receipt_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                os.close(descriptor)

            destination = self.root / destination_kind / receipt.asset_id
            try:
                atomic_directory_move(transaction.directory, destination)
            except FileExistsError as exc:
                raise AssetStorageError(
                    "asset_name_collision",
                    "The asset storage name already exists.",
                ) from exc
        except AssetStorageError:
            raise
        except OSError as exc:
            raise AssetStorageError(
                "storage_publish_failed",
                "The asset could not be published safely.",
            ) from exc

    def read_staged(
        self,
        receipt: IngestedAsset,
        *,
        byte_limit: int,
        _require_active_parent: bool = True,
    ) -> bytes:
        if byte_limit < 1:
            raise AssetStorageError(
                "staged_read_limit_invalid",
                "The staged asset read limit is invalid.",
            )
        validated, _, payload_path = self._validated_staged_payload(
            receipt,
            require_active_parent=_require_active_parent,
        )

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(payload_path, flags)
        except OSError as exc:
            raise AssetStorageError(
                "staged_asset_unavailable",
                "The staged asset is unavailable.",
            ) from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink > 1:
                raise AssetStorageError(
                    "staged_asset_redirect",
                    "The staged asset is not a private regular file.",
                )
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                data = stream.read(byte_limit + 1)
        except AssetStorageError:
            raise
        except OSError as exc:
            raise AssetStorageError(
                "staged_asset_unavailable",
                "The staged asset is unavailable.",
            ) from exc
        finally:
            os.close(descriptor)

        digest = hashlib.sha256(data).hexdigest()
        if (
            len(data) > byte_limit
            or len(data) != validated.byte_count
            or digest != validated.content_sha256
        ):
            raise AssetStorageError(
                "staged_asset_integrity_mismatch",
                "The staged asset failed its integrity check.",
            )
        return data

    def load_staged_receipt(self, asset_id: str) -> IngestedAsset:
        if re.fullmatch(r"asset_[0-9a-f]{32}", asset_id) is None:
            raise AssetStorageError(
                "asset_identity_invalid",
                "The staged asset identity is invalid.",
            )
        asset_directory = self.root / "staged" / asset_id
        receipt_path = asset_directory / "receipt.json"
        self._require_safe_staged_component(asset_directory, directory=True)
        self._require_safe_staged_component(receipt_path, directory=False)
        receipt = self._load_receipt(
            receipt_path,
            expected_status="STAGED",
        )
        if receipt.asset_id != asset_id:
            raise AssetStorageError(
                "asset_identity_mismatch",
                "The staged receipt identity does not match its location.",
            )
        self._validated_staged_payload(
            receipt,
            require_active_parent=True,
        )
        return receipt

    def _validated_staged_payload(
        self,
        receipt: IngestedAsset,
        *,
        require_active_parent: bool,
    ) -> tuple[IngestedAsset, Path, Path]:
        try:
            validated = IngestedAsset.model_validate(
                receipt.model_dump(mode="python")
            )
        except Exception as exc:
            raise AssetStorageError(
                "staged_receipt_invalid",
                "The staged asset receipt is invalid.",
            ) from exc
        if validated.status != "STAGED" or validated.stored_relpath is None:
            raise AssetStorageError(
                "staged_receipt_required",
                "A staged asset receipt is required.",
            )
        if require_active_parent:
            self._require_active_parent_chain(validated)

        asset_directory = self.root / "staged" / validated.asset_id
        quarantine_directory = self.root / "quarantine" / validated.asset_id
        if quarantine_directory.exists():
            raise AssetStorageError(
                "staged_asset_superseded",
                "The staged asset has a quarantine disposition.",
            )
        payload_path = self.root / PurePosixPath(validated.stored_relpath)
        expected_directory = payload_path.parent
        if expected_directory != asset_directory:
            raise AssetStorageError(
                "staged_path_mismatch",
                "The staged asset path does not match its receipt.",
            )
        self._require_safe_staged_component(asset_directory, directory=True)
        self._require_safe_staged_component(payload_path, directory=False)

        receipt_path = asset_directory / "receipt.json"
        self._require_safe_staged_component(receipt_path, directory=False)
        try:
            if receipt_path.read_bytes() != _canonical_receipt_bytes(validated):
                raise AssetStorageError(
                    "staged_receipt_integrity_mismatch",
                    "The stored asset receipt failed its integrity check.",
                )
        except AssetStorageError:
            raise
        except OSError as exc:
            raise AssetStorageError(
                "staged_asset_unavailable",
                "The staged asset is unavailable.",
            ) from exc
        return validated, asset_directory, payload_path

    def staged_path(self, receipt: IngestedAsset, *, byte_limit: int) -> Path:
        self.read_staged(receipt, byte_limit=byte_limit)
        assert receipt.stored_relpath is not None
        return self.root / PurePosixPath(receipt.stored_relpath)

    def quarantine_staged(
        self,
        receipt: IngestedAsset,
        *,
        reason_code: str,
    ) -> IngestedAsset:
        if reason_code == "accepted" or re.fullmatch(
            r"[a-z][a-z0-9_]{0,63}", reason_code
        ) is None:
            raise AssetStorageError(
                "quarantine_reason_invalid",
                "The quarantine reason is invalid.",
            )
        staged_directory = self.root / "staged" / receipt.asset_id
        quarantine_directory = self.root / "quarantine" / receipt.asset_id
        if quarantine_directory.exists():
            existing = self._load_receipt(
                quarantine_directory / "receipt.json",
                expected_status="QUARANTINED",
            )
            if (
                existing.parent_event_id != receipt.parent_event_id
                or existing.parent_asset_id != receipt.parent_asset_id
                or existing.content_sha256 != receipt.content_sha256
                or existing.reason_code != reason_code
            ):
                raise AssetStorageError(
                    "quarantine_reason_conflict",
                    "The existing quarantine disposition conflicts.",
                )
            if staged_directory.exists():
                try:
                    shutil.rmtree(staged_directory)
                except OSError as exc:
                    raise AssetStorageError(
                        "quarantine_transition_failed",
                        "The superseded staged asset could not be cleaned.",
                    ) from exc
            return existing

        validated, _, payload_path = self._validated_staged_payload(
            receipt,
            require_active_parent=False,
        )

        quarantined = IngestedAsset(
            asset_id=validated.asset_id,
            parent_event_id=validated.parent_event_id,
            parent_asset_id=validated.parent_asset_id,
            stored_relpath=(
                f"quarantine/{validated.asset_id}/payload.blob"
            ),
            original_name_redacted=validated.original_name_redacted,
            declared_media_type=validated.declared_media_type,
            verified_media_type=validated.verified_media_type,
            byte_count=validated.byte_count,
            content_sha256=validated.content_sha256,
            status="QUARANTINED",
            reason_code=reason_code,
            created_at=datetime.now(timezone.utc),
        )
        incoming_root = self.root / ".incoming"
        transition_directory: Path | None = None
        for _ in range(16):
            candidate = incoming_root / (
                f"transition_{receipt.asset_id}_{secrets.token_hex(8)}"
            )
            try:
                candidate.mkdir(mode=0o700)
            except FileExistsError:
                continue
            except OSError as exc:
                raise AssetStorageError(
                    "storage_allocate_failed",
                    "A quarantine transition could not be allocated.",
                ) from exc
            transition_directory = candidate
            break
        if transition_directory is None:
            raise AssetStorageError(
                "asset_name_exhausted",
                "A quarantine transition name could not be allocated.",
            )

        published = False
        try:
            self._copy_private_file(
                payload_path,
                transition_directory / "payload.blob",
                expected_byte_count=validated.byte_count,
                expected_sha256=validated.content_sha256,
            )
            self._write_private_file(
                transition_directory / "receipt.staged.json",
                _canonical_receipt_bytes(validated),
            )
            self._write_private_file(
                transition_directory / "receipt.json",
                _canonical_receipt_bytes(quarantined),
            )
            atomic_directory_move(transition_directory, quarantine_directory)
            published = True
            shutil.rmtree(staged_directory)
        except OSError as exc:
            raise AssetStorageError(
                "quarantine_transition_failed",
                "The staged asset could not be quarantined safely.",
            ) from exc
        finally:
            if not published and transition_directory.exists():
                try:
                    shutil.rmtree(transition_directory)
                except OSError as exc:
                    raise AssetStorageError(
                        "storage_cleanup_failed",
                        "The quarantine transition could not be cleaned safely.",
                    ) from exc
        return quarantined

    def event_usage(self, parent_event_id: str) -> tuple[int, int]:
        seen: set[str] = set()
        file_count = 0
        byte_count = 0
        for kind in ("staged", "quarantine"):
            root = self.root / kind
            try:
                directories = tuple(root.iterdir())
            except OSError as exc:
                raise AssetStorageError(
                    "storage_inventory_failed",
                    "The asset store could not be inventoried safely.",
                ) from exc
            for directory in directories:
                if not directory.is_dir():
                    raise AssetStorageError(
                        "storage_inventory_invalid",
                        "The asset store inventory is invalid.",
                    )
                receipt = self._load_receipt(
                    directory / "receipt.json",
                    expected_status=(
                        "STAGED" if kind == "staged" else "QUARANTINED"
                    ),
                )
                if (
                    receipt.asset_id in seen
                    or receipt.parent_event_id != parent_event_id
                ):
                    continue
                seen.add(receipt.asset_id)
                file_count += 1
                byte_count += receipt.byte_count
        return file_count, byte_count

    def _require_active_parent_chain(self, receipt: IngestedAsset) -> None:
        parent_id = receipt.parent_asset_id
        seen = {receipt.asset_id}
        for _ in range(128):
            if parent_id is None:
                return
            if parent_id in seen:
                raise AssetStorageError(
                    "staged_parent_cycle",
                    "The staged asset parent chain contains a cycle.",
                )
            seen.add(parent_id)
            if (self.root / "quarantine" / parent_id).exists():
                raise AssetStorageError(
                    "staged_parent_quarantined",
                    "An ancestor of the staged asset is quarantined.",
                )
            parent = self._load_receipt(
                self.root / "staged" / parent_id / "receipt.json",
                expected_status="STAGED",
            )
            if parent.parent_event_id != receipt.parent_event_id:
                raise AssetStorageError(
                    "staged_parent_event_mismatch",
                    "The staged asset parent chain crosses event boundaries.",
                )
            parent_id = parent.parent_asset_id
        raise AssetStorageError(
            "staged_parent_depth_invalid",
            "The staged asset parent chain is too deep.",
        )

    @staticmethod
    def _load_receipt(
        path: Path,
        *,
        expected_status: AssetStatus,
    ) -> IngestedAsset:
        try:
            raw = path.read_bytes()
            receipt = IngestedAsset.model_validate_json(raw)
        except Exception as exc:
            raise AssetStorageError(
                "stored_receipt_invalid",
                "A stored asset receipt is invalid.",
            ) from exc
        if (
            receipt.status != expected_status
            or raw != _canonical_receipt_bytes(receipt)
        ):
            raise AssetStorageError(
                "stored_receipt_integrity_mismatch",
                "A stored asset receipt failed its integrity check.",
            )
        return receipt

    @staticmethod
    def _copy_private_file(
        source: Path,
        destination: Path,
        *,
        expected_byte_count: int,
        expected_sha256: str | None,
    ) -> None:
        if expected_sha256 is None:
            raise AssetStorageError(
                "staged_receipt_invalid",
                "The staged asset receipt is invalid.",
            )
        source_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        source_flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            source_descriptor = os.open(source, source_flags)
        except OSError as exc:
            raise AssetStorageError(
                "staged_asset_unavailable",
                "The staged asset is unavailable.",
            ) from exc
        try:
            metadata = os.fstat(source_descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink > 1:
                raise AssetStorageError(
                    "staged_asset_redirect",
                    "The staged asset is not a private regular file.",
                )
            destination_descriptor = os.open(
                destination,
                os.O_CREAT
                | os.O_EXCL
                | os.O_WRONLY
                | getattr(os, "O_BINARY", 0),
                0o600,
            )
            try:
                digest = hashlib.sha256()
                byte_count = 0
                with (
                    os.fdopen(
                        source_descriptor,
                        "rb",
                        closefd=False,
                    ) as source_stream,
                    os.fdopen(
                        destination_descriptor,
                        "wb",
                        closefd=False,
                    ) as destination_stream,
                ):
                    while True:
                        chunk = source_stream.read(1024 * 1024)
                        if not chunk:
                            break
                        byte_count += len(chunk)
                        if byte_count > expected_byte_count:
                            raise AssetStorageError(
                                "staged_asset_integrity_mismatch",
                                "The staged asset failed its integrity check.",
                            )
                        digest.update(chunk)
                        destination_stream.write(chunk)
                    destination_stream.flush()
                    os.fsync(destination_stream.fileno())
                if (
                    byte_count != expected_byte_count
                    or digest.hexdigest() != expected_sha256
                ):
                    raise AssetStorageError(
                        "staged_asset_integrity_mismatch",
                        "The staged asset failed its integrity check.",
                    )
            finally:
                os.close(destination_descriptor)
        finally:
            os.close(source_descriptor)

    @staticmethod
    def _write_private_file(path: Path, content: bytes) -> None:
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

    @staticmethod
    def _require_safe_staged_component(path: Path, *, directory: bool) -> None:
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise AssetStorageError(
                "staged_asset_unavailable",
                "The staged asset is unavailable.",
            ) from exc
        expected = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(
            metadata.st_mode
        )
        if stat_is_redirect(metadata) or not expected:
            raise AssetStorageError(
                "staged_asset_redirect",
                "The staged asset path is redirected.",
            )


__all__ = [
    "AssetStatus",
    "AssetStorageError",
    "IncomingAsset",
    "IngestedAsset",
    "SecureAssetStore",
]
