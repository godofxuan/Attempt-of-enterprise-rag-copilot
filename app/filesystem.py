from __future__ import annotations

import ctypes
import errno
import os
import sys
import time
from pathlib import Path

_WINDOWS_DIRECTORY_MOVE_ATTEMPTS = 8
_WINDOWS_DIRECTORY_MOVE_BASE_DELAY_SECONDS = 0.01
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


def _linux_rename_no_replace(source: Path, destination: Path) -> bool:
    if not sys.platform.startswith("linux"):
        return False
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        return False
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        _AT_FDCWD,
        os.fsencode(source),
        _AT_FDCWD,
        os.fsencode(destination),
        _RENAME_NOREPLACE,
    )
    if result == 0:
        return True
    error_code = ctypes.get_errno()
    if error_code in {errno.ENOSYS, errno.EINVAL}:
        return False
    raise OSError(
        error_code,
        os.strerror(error_code),
        os.fspath(destination),
    )


def _move_once(source: Path, destination: Path, *, replace: bool) -> None:
    if replace:
        os.replace(source, destination)
        return
    if _linux_rename_no_replace(source, destination):
        return
    if destination.exists():
        raise FileExistsError(
            errno.EEXIST,
            os.strerror(errno.EEXIST),
            os.fspath(destination),
        )
    os.rename(source, destination)


def atomic_directory_move(
    source: Path,
    destination: Path,
    *,
    replace: bool = False,
) -> None:
    """Atomically publish a directory with bounded Windows sharing retries."""
    source = Path(source)
    destination = Path(destination)
    for attempt in range(_WINDOWS_DIRECTORY_MOVE_ATTEMPTS):
        try:
            _move_once(source, destination, replace=replace)
            return
        except FileExistsError:
            raise
        except PermissionError as exc:
            retryable = (
                os.name == "nt"
                and getattr(exc, "winerror", None) == 5
                and source.is_dir()
                and not destination.exists()
                and attempt + 1 < _WINDOWS_DIRECTORY_MOVE_ATTEMPTS
            )
            if not retryable:
                raise
            time.sleep(
                min(
                    _WINDOWS_DIRECTORY_MOVE_BASE_DELAY_SECONDS * (2**attempt),
                    0.08,
                )
            )
