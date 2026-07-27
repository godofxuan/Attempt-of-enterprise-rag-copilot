from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.filesystem import atomic_directory_move
from app.indexing.store import (
    ActiveIndexPointer,
    activate_version,
    load_active_pointer,
    load_index_version,
    publication_lock,
)


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
IMAGE_REFERENCE_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9._:/-]{0,399}@sha256:[0-9a-f]{64}$"
)
RUNTIME_CONTRACT_PATHS = (
    ".dockerignore",
    "Dockerfile",
    "deploy/compose.yaml",
    "requirements.txt",
)


class DeploymentRelease(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["enterprise_deployment_release_v1"]
    producer: Literal["enterprise_agentic_rag_v2"]
    release_id: str = Field(pattern=IDENTIFIER_PATTERN.pattern)
    image_reference: str = Field(max_length=472)
    source_commit: str = Field(pattern=COMMIT_PATTERN.pattern)
    runtime_contract_sha256: str = Field(pattern=SHA256_PATTERN.pattern)
    index_run_id: str = Field(pattern=IDENTIFIER_PATTERN.pattern)
    index_manifest_sha256: str = Field(pattern=SHA256_PATTERN.pattern)
    previous_release_id: str | None = Field(
        default=None,
        pattern=IDENTIFIER_PATTERN.pattern,
    )
    created_at: datetime

    @field_validator("image_reference")
    @classmethod
    def validate_image_reference(cls, value: str) -> str:
        name, _, _ = value.partition("@sha256:")
        if (
            not IMAGE_REFERENCE_PATTERN.fullmatch(value)
            or ".." in value
            or "://" in name
        ):
            raise ValueError(
                "image reference must contain an exact sha256 manifest digest"
            )
        return value

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class DeploymentActivePointer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["enterprise_active_deployment_v1"]
    producer: Literal["enterprise_agentic_rag_v2"]
    release_id: str = Field(pattern=IDENTIFIER_PATTERN.pattern)
    release_manifest_sha256: str = Field(pattern=SHA256_PATTERN.pattern)
    index_run_id: str = Field(pattern=IDENTIFIER_PATTERN.pattern)
    index_manifest_sha256: str = Field(pattern=SHA256_PATTERN.pattern)
    previous_release_id: str | None = Field(
        default=None,
        pattern=IDENTIFIER_PATTERN.pattern,
    )
    activated_at: datetime

    @field_validator("activated_at")
    @classmethod
    def validate_activated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("activated_at must be timezone-aware")
        return value


class PendingDeploymentTransaction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["enterprise_deployment_transaction_v1"]
    producer: Literal["enterprise_agentic_rag_v2"]
    operation: Literal["activate", "rollback"]
    previous_deployment: DeploymentActivePointer | None
    previous_index: ActiveIndexPointer | None
    target_deployment: DeploymentActivePointer
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value


def _resolved_root(root: Path) -> Path:
    candidate = Path(os.path.abspath(root))
    if candidate.exists() and candidate.is_symlink():
        raise PermissionError("deployment state root must not be a symlink")
    return candidate


def _release_path(root: Path, release_id: str) -> Path:
    if not IDENTIFIER_PATTERN.fullmatch(release_id):
        raise ValueError("invalid deployment release ID")
    releases = (_resolved_root(root) / "releases").resolve()
    target = (releases / release_id).resolve()
    if target.parent != releases:
        raise PermissionError("deployment release path escapes the release root")
    return target


def _canonical_bytes(model: BaseModel) -> bytes:
    payload = model.model_dump(mode="json")
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("ascii")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_regular_file(path: Path, *, max_bytes: int = 65_536) -> bytes:
    before = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(before.st_mode):
        raise PermissionError(f"deployment artifact is not a regular file: {path.name}")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        current = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or path.is_symlink()
            or (opened.st_dev, opened.st_ino)
            != (current.st_dev, current.st_ino)
            or (before.st_dev, before.st_ino)
            != (opened.st_dev, opened.st_ino)
        ):
            raise PermissionError(
                f"deployment artifact changed before open: {path.name}"
            )
        if opened.st_size > max_bytes:
            raise ValueError(f"deployment artifact exceeds size limit: {path.name}")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != opened.st_size:
            raise RuntimeError(
                f"deployment artifact changed while reading: {path.name}"
            )
        return payload
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if path.exists():
            path.unlink()
        raise


def _load_canonical_model(path: Path, model_type):
    payload = _read_regular_file(path)
    model = model_type.model_validate_json(payload)
    if _canonical_bytes(model) != payload:
        raise ValueError(f"deployment artifact is not canonical: {path.name}")
    return model, payload


def load_release(
    state_root: Path,
    release_id: str,
) -> tuple[DeploymentRelease, str]:
    path = _release_path(state_root, release_id) / "manifest.json"
    release, payload = _load_canonical_model(path, DeploymentRelease)
    if release.release_id != release_id:
        raise ValueError("deployment release directory and manifest disagree")
    return release, _sha256(payload)


def register_release(
    state_root: Path,
    index_root: Path,
    release: DeploymentRelease,
) -> str:
    root = _resolved_root(state_root)
    target = _release_path(root, release.release_id)
    if target.exists():
        raise FileExistsError(f"deployment release already exists: {release.release_id}")
    if release.previous_release_id == release.release_id:
        raise ValueError("deployment release cannot reference itself")
    if release.previous_release_id is not None:
        load_release(root, release.previous_release_id)

    index = load_index_version(index_root, release.index_run_id)
    if index.manifest_sha256 != release.index_manifest_sha256:
        raise ValueError("deployment release index manifest hash mismatch")

    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{release.release_id}.staging-",
            dir=target.parent,
        )
    )
    try:
        payload = _canonical_bytes(release)
        _write_exclusive(stage / "manifest.json", payload)
        atomic_directory_move(stage, target)
        return _sha256(payload)
    finally:
        if stage.exists():
            stage.rmdir()


def _active_path(state_root: Path) -> Path:
    return _resolved_root(state_root) / "active.json"


def _pending_path(state_root: Path) -> Path:
    return _resolved_root(state_root) / "pending.json"


def _load_active_optional(state_root: Path) -> DeploymentActivePointer | None:
    path = _active_path(state_root)
    if not path.exists():
        return None
    pointer, _ = _load_canonical_model(path, DeploymentActivePointer)
    return pointer


def load_active_deployment(state_root: Path) -> DeploymentActivePointer:
    pending = _pending_path(state_root)
    if pending.exists():
        raise RuntimeError("deployment transaction recovery is required")
    pointer = _load_active_optional(state_root)
    if pointer is None:
        raise FileNotFoundError("no active deployment release")
    return pointer


def _load_index_pointer_optional(index_root: Path) -> ActiveIndexPointer | None:
    try:
        return load_active_pointer(index_root)
    except FileNotFoundError:
        return None


def _verify_pointer(
    state_root: Path,
    index_root: Path,
    pointer: DeploymentActivePointer,
) -> DeploymentRelease:
    release, release_sha256 = load_release(state_root, pointer.release_id)
    if release_sha256 != pointer.release_manifest_sha256:
        raise ValueError("active deployment release manifest hash mismatch")
    if (
        release.index_run_id != pointer.index_run_id
        or release.index_manifest_sha256 != pointer.index_manifest_sha256
    ):
        raise ValueError("active deployment pointer does not match its release")
    index = load_index_version(index_root)
    if (
        index.manifest.run_id != pointer.index_run_id
        or index.manifest_sha256 != pointer.index_manifest_sha256
    ):
        raise ValueError("active index does not match active deployment")
    return release


def verify_active_deployment(
    state_root: Path,
    index_root: Path,
) -> DeploymentActivePointer:
    pointer = load_active_deployment(state_root)
    _verify_pointer(state_root, index_root, pointer)
    return pointer


def _target_pointer(
    state_root: Path,
    release: DeploymentRelease,
    *,
    activated_at: datetime | None,
) -> DeploymentActivePointer:
    _, release_sha256 = load_release(state_root, release.release_id)
    return DeploymentActivePointer(
        schema_version="enterprise_active_deployment_v1",
        producer="enterprise_agentic_rag_v2",
        release_id=release.release_id,
        release_manifest_sha256=release_sha256,
        index_run_id=release.index_run_id,
        index_manifest_sha256=release.index_manifest_sha256,
        previous_release_id=release.previous_release_id,
        activated_at=activated_at or datetime.now(timezone.utc),
    )


def _apply_transaction_target(
    state_root: Path,
    index_root: Path,
    transaction: PendingDeploymentTransaction,
    *,
    before_deployment_replace: Callable[[], None] | None = None,
) -> DeploymentActivePointer:
    target = transaction.target_deployment
    release = _verify_release_target(state_root, index_root, target)
    activate_version(index_root, release.index_run_id, _lock_held=True)
    if before_deployment_replace is not None:
        before_deployment_replace()
    _atomic_write(_active_path(state_root), _canonical_bytes(target))
    _pending_path(state_root).unlink()
    return target


def _verify_release_target(
    state_root: Path,
    index_root: Path,
    pointer: DeploymentActivePointer,
) -> DeploymentRelease:
    release, release_sha256 = load_release(state_root, pointer.release_id)
    if (
        release_sha256 != pointer.release_manifest_sha256
        or release.index_run_id != pointer.index_run_id
        or release.index_manifest_sha256 != pointer.index_manifest_sha256
    ):
        raise ValueError("pending deployment target does not match its release")
    index = load_index_version(index_root, release.index_run_id)
    if index.manifest_sha256 != release.index_manifest_sha256:
        raise ValueError("pending deployment target index hash mismatch")
    return release


def _begin_transaction(
    state_root: Path,
    index_root: Path,
    target_release: DeploymentRelease,
    *,
    operation: Literal["activate", "rollback"],
    activated_at: datetime | None,
    before_deployment_replace: Callable[[], None] | None,
) -> DeploymentActivePointer:
    if _pending_path(state_root).exists():
        raise RuntimeError("deployment transaction recovery is required")
    previous_deployment = _load_active_optional(state_root)
    previous_index = _load_index_pointer_optional(index_root)
    if previous_deployment is not None:
        _verify_pointer(state_root, index_root, previous_deployment)
    target = _target_pointer(
        state_root,
        target_release,
        activated_at=activated_at,
    )
    transaction = PendingDeploymentTransaction(
        schema_version="enterprise_deployment_transaction_v1",
        producer="enterprise_agentic_rag_v2",
        operation=operation,
        previous_deployment=previous_deployment,
        previous_index=previous_index,
        target_deployment=target,
        created_at=datetime.now(timezone.utc),
    )
    _write_exclusive(_pending_path(state_root), _canonical_bytes(transaction))
    return _apply_transaction_target(
        state_root,
        index_root,
        transaction,
        before_deployment_replace=before_deployment_replace,
    )


def activate_deployment(
    state_root: Path,
    index_root: Path,
    release_id: str,
    *,
    activated_at: datetime | None = None,
    before_deployment_replace: Callable[[], None] | None = None,
) -> DeploymentActivePointer:
    root = _resolved_root(state_root)
    index_root = _resolved_root(index_root)
    with publication_lock(index_root):
        with publication_lock(root):
            release, _ = load_release(root, release_id)
            current = _load_active_optional(root)
            current_release_id = current.release_id if current is not None else None
            if release.previous_release_id != current_release_id:
                raise ValueError(
                    "deployment release does not extend the active release"
                )
            return _begin_transaction(
                root,
                index_root,
                release,
                operation="activate",
                activated_at=activated_at,
                before_deployment_replace=before_deployment_replace,
            )


def rollback_deployment(
    state_root: Path,
    index_root: Path,
    *,
    activated_at: datetime | None = None,
    before_deployment_replace: Callable[[], None] | None = None,
) -> DeploymentActivePointer:
    root = _resolved_root(state_root)
    index_root = _resolved_root(index_root)
    with publication_lock(index_root):
        with publication_lock(root):
            current = load_active_deployment(root)
            current_release, _ = load_release(root, current.release_id)
            previous_release_id = current_release.previous_release_id
            if previous_release_id is None:
                raise ValueError("active deployment has no previous release")
            previous_release, _ = load_release(root, previous_release_id)
            return _begin_transaction(
                root,
                index_root,
                previous_release,
                operation="rollback",
                activated_at=activated_at,
                before_deployment_replace=before_deployment_replace,
            )


def _remove_optional_pointer(path: Path) -> None:
    if not path.exists():
        return
    metadata = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise PermissionError("refusing to remove unsafe deployment pointer")
    path.unlink()


def recover_deployment(
    state_root: Path,
    index_root: Path,
    *,
    strategy: Literal["restore_previous", "complete_target"],
) -> DeploymentActivePointer | None:
    root = _resolved_root(state_root)
    index_root = _resolved_root(index_root)
    with publication_lock(index_root):
        with publication_lock(root):
            pending_path = _pending_path(root)
            transaction, _ = _load_canonical_model(
                pending_path,
                PendingDeploymentTransaction,
            )
            if strategy == "complete_target":
                return _apply_transaction_target(root, index_root, transaction)

            previous_index = transaction.previous_index
            if previous_index is None:
                _remove_optional_pointer(index_root / "active.json")
            else:
                loaded = load_index_version(index_root, previous_index.run_id)
                if loaded.manifest_sha256 != previous_index.manifest_sha256:
                    raise ValueError("previous index manifest hash mismatch")
                activate_version(index_root, previous_index.run_id, _lock_held=True)

            previous_deployment = transaction.previous_deployment
            if previous_deployment is None:
                _remove_optional_pointer(_active_path(root))
            else:
                _verify_release_target(root, index_root, previous_deployment)
                _atomic_write(
                    _active_path(root),
                    _canonical_bytes(previous_deployment),
                )
            pending_path.unlink()
            return previous_deployment


def render_compose_environment(
    state_root: Path,
    index_root: Path,
) -> str:
    pointer = verify_active_deployment(state_root, index_root)
    release, _ = load_release(state_root, pointer.release_id)
    values = {
        "DEPLOYMENT_EXPECTED_INDEX_MANIFEST_SHA256": (
            pointer.index_manifest_sha256
        ),
        "DEPLOYMENT_EXPECTED_INDEX_RUN_ID": pointer.index_run_id,
        "DEPLOYMENT_RELEASE_ID": pointer.release_id,
        "RAG_IMAGE": release.image_reference,
    }
    return "".join(f"{key}={values[key]}\n" for key in sorted(values))


def calculate_runtime_contract_sha256(repository_root: Path) -> str:
    root = Path(repository_root).resolve()
    digest = hashlib.sha256()
    for relative_path in RUNTIME_CONTRACT_PATHS:
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root):
            raise PermissionError("runtime contract path escapes repository")
        payload = _read_regular_file(path, max_bytes=2_000_000)
        encoded = relative_path.encode("ascii")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


__all__ = [
    "DeploymentActivePointer",
    "DeploymentRelease",
    "PendingDeploymentTransaction",
    "RUNTIME_CONTRACT_PATHS",
    "activate_deployment",
    "calculate_runtime_contract_sha256",
    "load_active_deployment",
    "load_release",
    "recover_deployment",
    "register_release",
    "render_compose_environment",
    "rollback_deployment",
    "verify_active_deployment",
]
