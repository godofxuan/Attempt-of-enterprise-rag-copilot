from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import stat
import tempfile
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit


_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def normalized_ollama_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if parsed.scheme != "http":
        raise ValueError("evaluation lock requires a local HTTP Ollama origin")
    if parsed.path not in {"", "/", "/v1", "/v1/"}:
        raise ValueError("evaluation lock requires an Ollama origin or /v1 endpoint")
    host = (parsed.hostname or "").lower()
    if host == "localhost":
        host = "127.0.0.1"
    elif host in {"127.0.0.1", "::1"}:
        pass
    else:
        raise ValueError("evaluation lock is only supported for local Ollama origins")
    if parsed.port is None:
        raise ValueError("evaluation lock requires an explicit Ollama port")
    rendered_host = "[::1]" if host == "::1" else host
    return f"http://{rendered_host}:{parsed.port}"


def evaluation_lock_path(origin: str, *, lock_root: Path | None = None) -> Path:
    normalized = normalized_ollama_origin(origin)
    root = _prepare_lock_root(lock_root)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
    return root / f"r2-s4-{digest}.lock"


@contextlib.contextmanager
def evaluation_lock(
    origin: str,
    *,
    lock_root: Path | None = None,
) -> Iterator[Path]:
    path = evaluation_lock_path(origin, lock_root=lock_root)
    before = _optional_lstat(path, "evaluation lock path")
    if before is not None:
        _validate_regular_non_redirecting(before, "evaluation lock path")
    fd = _open_regular_lock_file(path)
    locked = False
    try:
        after = path.lstat()
        _validate_regular_non_redirecting(after, "evaluation lock path")
        opened = os.fstat(fd)
        _validate_regular_non_redirecting(opened, "evaluation lock file")
        if before is not None and _file_identity(before) != _file_identity(after):
            raise ValueError("evaluation lock path changed before use")
        if _file_identity(after) != _file_identity(opened):
            raise ValueError("evaluation lock path changed before use")
        _acquire_os_lock(fd, origin)
        locked = True
        post_acquire = path.lstat()
        _validate_regular_non_redirecting(post_acquire, "evaluation lock path")
        opened_after_acquire = os.fstat(fd)
        _validate_regular_non_redirecting(
            opened_after_acquire,
            "evaluation lock file",
        )
        if _file_identity(post_acquire) != _file_identity(opened_after_acquire):
            raise ValueError("evaluation lock path changed before use")
        try:
            yield path
        finally:
            if locked:
                _release_os_lock(fd)
                locked = False
    finally:
        os.close(fd)


def _prepare_lock_root(lock_root: Path | None) -> Path:
    root = (
        Path(lock_root)
        if lock_root is not None
        else Path(
            os.environ.get(
                "R2_S4_EVALUATION_LOCK_DIR",
                str(Path(tempfile.gettempdir()) / "r2_s4_evaluation_locks"),
            )
        )
    )
    root = _absolute_lexical(root)
    _validate_existing_chain(root.parent, "evaluation lock root parent")
    root.mkdir(parents=True, exist_ok=True)
    _validate_existing_chain(root, "evaluation lock root")
    observed = root.lstat()
    if _is_redirecting_path(observed) or not stat.S_ISDIR(observed.st_mode):
        raise ValueError("evaluation lock root must be a directory")
    return root


def _open_regular_lock_file(path: Path) -> int:
    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(path, flags, 0o600)
    except OSError as exc:
        if exc.errno in {
            errno.ELOOP,
            errno.ENOTDIR,
            errno.EPERM,
            errno.EACCES,
        }:
            raise ValueError(
                "evaluation lock path must be a regular non-redirecting file"
            ) from exc
        raise


def _acquire_os_lock(fd: int, origin: str) -> None:
    if os.name == "nt":
        import msvcrt

        if os.fstat(fd).st_size == 0:
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, b"0")
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError(f"evaluation lock is already held for {origin}") from exc
        return

    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise RuntimeError(f"evaluation lock is already held for {origin}") from exc


def _release_os_lock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(fd, fcntl.LOCK_UN)


def _validate_existing_chain(path: Path, label: str) -> None:
    chain: list[Path] = []
    current = path
    while True:
        chain.append(current)
        if current.parent == current:
            break
        current = current.parent
    missing = False
    for candidate in reversed(chain):
        try:
            observed = candidate.lstat()
        except FileNotFoundError:
            missing = True
            continue
        except OSError as exc:
            raise ValueError(f"{label} cannot be inspected") from exc
        if missing:
            raise ValueError(f"{label} changed during lexical validation")
        if _is_redirecting_path(observed):
            raise ValueError(f"{label} cannot contain a symlink or redirect")
        if not stat.S_ISDIR(observed.st_mode):
            raise ValueError(f"{label} has a non-directory path component")


def _optional_lstat(path: Path, label: str):
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError(f"{label} cannot be inspected") from exc


def _validate_regular_non_redirecting(value: os.stat_result, label: str) -> None:
    if _is_redirecting_path(value) or not stat.S_ISREG(value.st_mode):
        raise ValueError(f"{label} must be a regular non-redirecting file")


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
    )


def _absolute_lexical(path: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else Path.cwd() / candidate


def _is_redirecting_path(value: object) -> bool:
    return stat.S_ISLNK(value.st_mode) or bool(
        getattr(value, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
    )


__all__ = [
    "evaluation_lock",
    "evaluation_lock_path",
    "normalized_ollama_origin",
]
