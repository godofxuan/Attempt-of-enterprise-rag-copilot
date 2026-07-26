from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.filesystem import atomic_directory_move
from app.indexing.builder import (
    EmbedText,
    build_index_artifacts,
    validate_index_directory,
)
from app.indexing.manifest import IndexManifest, load_index_manifest
from app.ingestion.chunking import ChunkerConfig
from app.ingestion.parsers import ParserRegistry


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_LOCK_POLL_SECONDS = 0.01


class ActiveIndexPointer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["enterprise_active_index_v1"]
    producer: Literal["enterprise_agentic_rag_v2"]
    run_id: str = Field(min_length=1, pattern=RUN_ID_PATTERN.pattern)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    activated_at: datetime

    @field_validator("activated_at")
    @classmethod
    def validate_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("activated_at must be timezone-aware")
        return value


@dataclass(frozen=True)
class LoadedIndexVersion:
    path: Path
    manifest: IndexManifest
    manifest_sha256: str


def _validate_run_id(run_id: str) -> str:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(
            "run_id must start with an alphanumeric character and contain only "
            "letters, numbers, dot, underscore, or hyphen"
        )
    return run_id


def _resolved_root(root: Path) -> Path:
    return Path(root).resolve()


def _version_path(root: Path, run_id: str) -> Path:
    safe_run_id = _validate_run_id(run_id)
    versions = (_resolved_root(root) / "versions").resolve()
    target = (versions / safe_run_id).resolve()
    if target.parent != versions:
        raise PermissionError("index version path escapes the version root")
    return target


def _manifest_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_pointer(root: Path) -> ActiveIndexPointer:
    pointer_path = _resolved_root(root) / "active.json"
    payload = json.loads(pointer_path.read_text(encoding="utf-8"))
    return ActiveIndexPointer.model_validate(payload)


def load_active_pointer(root: Path) -> ActiveIndexPointer:
    return _load_pointer(root)


def load_index_version(
    root: Path,
    run_id: str | None = None,
) -> LoadedIndexVersion:
    pointer = None
    if run_id is None:
        pointer = _load_pointer(root)
        run_id = pointer.run_id
    version_path = _version_path(root, run_id)
    if not version_path.is_dir():
        raise FileNotFoundError(f"index version not found: {run_id}")
    manifest_path = version_path / "manifest.json"
    manifest = load_index_manifest(manifest_path)
    if manifest.run_id != run_id:
        raise ValueError(
            f"index version directory {run_id!r} contains manifest for "
            f"{manifest.run_id!r}"
        )
    validate_index_directory(version_path, manifest)
    manifest_sha256 = _manifest_hash(manifest_path)
    if pointer is not None and pointer.manifest_sha256 != manifest_sha256:
        raise ValueError("active pointer manifest hash does not match index version")
    return LoadedIndexVersion(
        path=version_path,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )


def load_active_manifest(root: Path) -> IndexManifest:
    return load_index_version(root).manifest


def _serialize_pointer(pointer: ActiveIndexPointer) -> bytes:
    payload = pointer.model_dump(mode="json")
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return text.encode("utf-8")


def _atomic_write_pointer(
    root: Path,
    pointer: ActiveIndexPointer,
    *,
    before_replace: Callable[[], None] | None = None,
) -> None:
    root = _resolved_root(root)
    root.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".active.json.",
        suffix=".tmp",
        dir=root,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_serialize_pointer(pointer))
            handle.flush()
            os.fsync(handle.fileno())
        if before_replace is not None:
            before_replace()
        os.replace(temporary_path, root / "active.json")
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def activate_version(
    root: Path,
    run_id: str,
    *,
    activated_at: datetime | None = None,
    before_replace: Callable[[], None] | None = None,
    _lock_held: bool = False,
) -> ActiveIndexPointer:
    if not _lock_held:
        with publication_lock(root):
            return activate_version(
                root,
                run_id,
                activated_at=activated_at,
                before_replace=before_replace,
                _lock_held=True,
            )
    loaded = load_index_version(root, run_id)
    pointer = ActiveIndexPointer(
        schema_version="enterprise_active_index_v1",
        producer="enterprise_agentic_rag_v2",
        run_id=run_id,
        manifest_sha256=loaded.manifest_sha256,
        activated_at=activated_at or datetime.now(timezone.utc),
    )
    _atomic_write_pointer(root, pointer, before_replace=before_replace)
    return pointer


@contextmanager
def publication_lock(root: Path, *, timeout_seconds: float = 10.0):
    root = _resolved_root(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".publication.lock"
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        current = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or path.is_symlink()
            or metadata.st_nlink != 1
            or (metadata.st_dev, metadata.st_ino)
            != (current.st_dev, current.st_ino)
        ):
            raise PermissionError("index publication lock path is unsafe")
        if metadata.st_size == 0:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        _lock_descriptor(descriptor, timeout_seconds=timeout_seconds)
        try:
            yield
        finally:
            _unlock_descriptor(descriptor)
    finally:
        os.close(descriptor)


def _lock_descriptor(descriptor: int, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError("timed out waiting for index publication lock")
            time.sleep(_LOCK_POLL_SECONDS)


def _unlock_descriptor(descriptor: int) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


def _validate_owned_target(root: Path, run_id: str) -> None:
    try:
        load_index_version(root, run_id)
    except Exception as exc:
        raise PermissionError(
            f"index version {run_id!r} is not a validated v2 artifact; "
            "refusing --force"
        ) from exc


def _refuse_active_overwrite(root: Path, run_id: str) -> None:
    pointer_path = _resolved_root(root) / "active.json"
    if not pointer_path.exists():
        return
    try:
        pointer = _load_pointer(root)
    except Exception as exc:
        raise PermissionError(
            "cannot verify the current active version; refusing --force"
        ) from exc
    if pointer.run_id == run_id:
        raise PermissionError(
            f"cannot overwrite active version {run_id!r} in place; use a new run_id"
        )


def _install_stage(stage: Path, target: Path) -> None:
    if not target.exists():
        atomic_directory_move(stage, target)
        return

    backup = Path(
        tempfile.mkdtemp(
            prefix=f".{target.name}.backup-",
            dir=target.parent,
        )
    )
    backup.rmdir()
    atomic_directory_move(target, backup)
    try:
        atomic_directory_move(stage, target)
    except Exception:
        if not target.exists() and backup.exists():
            atomic_directory_move(backup, target)
        raise
    else:
        shutil.rmtree(backup)


def build_index_version(
    *,
    root: Path,
    input_dir: Path,
    run_id: str,
    chunker_config: ChunkerConfig,
    embedding_model: str,
    embed_text: EmbedText,
    activate: bool = False,
    force: bool = False,
    registry: ParserRegistry | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> IndexManifest:
    safe_run_id = _validate_run_id(run_id)
    root = _resolved_root(root)
    versions = root / "versions"
    target = _version_path(root, safe_run_id)
    if target.exists():
        if not force:
            raise FileExistsError(f"index version already exists: {safe_run_id}")
        _validate_owned_target(root, safe_run_id)
        _refuse_active_overwrite(root, safe_run_id)

    versions.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{safe_run_id}.staging-",
            dir=versions,
        )
    )
    try:
        manifest = build_index_artifacts(
            input_dir=input_dir,
            output_dir=stage,
            run_id=safe_run_id,
            chunker_config=chunker_config,
            embedding_model=embedding_model,
            embed_text=embed_text,
            registry=registry,
            started_at=started_at,
            finished_at=finished_at,
        )
        validate_index_directory(stage, manifest)
        with publication_lock(root):
            _install_stage(stage, target)
            if activate:
                activate_version(root, safe_run_id, _lock_held=True)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)
