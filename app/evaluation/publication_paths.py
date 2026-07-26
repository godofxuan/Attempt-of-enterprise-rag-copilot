from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
from pathlib import Path

from app.filesystem import atomic_directory_move


_REPARSE_POINT_ATTRIBUTE = getattr(
    stat,
    "FILE_ATTRIBUTE_REPARSE_POINT",
    0x400,
)


def _validated_publication_root(path: Path, label: str) -> Path:
    lexical_path = Path(path)
    try:
        observed = lexical_path.lstat()
    except FileNotFoundError:
        lexical_path.mkdir(parents=True, exist_ok=True)
        try:
            observed = lexical_path.lstat()
        except OSError as exc:
            raise ValueError(
                f"{label} could not be validated: {lexical_path}"
            ) from exc
    except OSError as exc:
        raise ValueError(
            f"{label} could not be validated: {lexical_path}"
        ) from exc
    if _is_redirecting_path(observed):
        raise ValueError(
            f"{label} cannot be a symlink or redirecting reparse point"
        )
    if not stat.S_ISDIR(observed.st_mode):
        raise NotADirectoryError(
            f"{label} is not a directory: {lexical_path}"
        )
    return lexical_path.resolve()


def _validated_absent_publication_target(
    output_root: Path,
    name: str,
    label: str,
    boundary_error: str,
) -> Path:
    target = output_root / name
    if target.parent != output_root:
        raise ValueError(boundary_error)
    try:
        observed = target.lstat()
    except FileNotFoundError:
        return target
    except OSError as exc:
        raise FileExistsError(
            f"{label} final component could not be validated: {target}"
        ) from exc
    if _is_redirecting_path(observed):
        raise FileExistsError(
            f"{label} already exists as a redirecting final component: {target}"
        )
    raise FileExistsError(f"{label} already exists: {target}")


def _atomic_publish_no_replace(stage: Path, target: Path) -> None:
    if os.name == "nt":
        atomic_directory_move(stage, target)
        return

    if sys.platform == "linux":
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise OSError(
                errno.ENOTSUP,
                os.strerror(errno.ENOTSUP),
                str(target),
            )
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        if renameat2(
            -100,
            os.fsencode(stage),
            -100,
            os.fsencode(target),
            1,
        ) == 0:
            return
        error_code = ctypes.get_errno()
        if error_code in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(
                errno.EEXIST,
                os.strerror(errno.EEXIST),
                str(target),
            )
        unsupported_errors = {
            errno.EINVAL,
            errno.ENOSYS,
            errno.ENOTSUP,
            getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
        }
        if error_code in unsupported_errors:
            raise OSError(
                errno.ENOTSUP,
                os.strerror(errno.ENOTSUP),
                str(target),
            )
        raise OSError(error_code, os.strerror(error_code), str(target))

    raise OSError(
        errno.ENOTSUP,
        os.strerror(errno.ENOTSUP),
        str(target),
    )


def _is_redirecting_path(value) -> bool:
    return stat.S_ISLNK(value.st_mode) or bool(
        getattr(value, "st_file_attributes", 0)
        & _REPARSE_POINT_ATTRIBUTE
    )


__all__ = [
    "_atomic_publish_no_replace",
    "_validated_absent_publication_target",
    "_validated_publication_root",
]
