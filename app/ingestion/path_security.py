from __future__ import annotations

import os
import stat
from pathlib import Path


def stat_is_redirect(metadata: os.stat_result) -> bool:
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)


def absolute_path_has_redirect(path: Path) -> bool:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError("redirect checks require an absolute path")
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            break
        if stat_is_redirect(metadata):
            return True
    return False


__all__ = ["absolute_path_has_redirect", "stat_is_redirect"]
