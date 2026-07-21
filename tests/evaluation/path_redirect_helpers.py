from __future__ import annotations

import os
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest


REPARSE_POINT_ATTRIBUTE = getattr(
    stat,
    "FILE_ATTRIBUTE_REPARSE_POINT",
    0x400,
)


@contextmanager
def directory_redirect(
    link: Path,
    target: Path,
    *,
    windows_junction_only: bool = False,
) -> Iterator[str]:
    link = Path(link).absolute()
    target = Path(target).absolute()
    if link.exists() or os.path.lexists(link):
        raise AssertionError(f"redirect path already exists: {link}")
    if not target.is_dir():
        raise AssertionError(f"redirect target is not a directory: {target}")

    if os.name == "nt":
        command = [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d",
            "/c",
            "mklink",
            "/J",
            str(link),
            str(target),
        ]
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if completed.returncode != 0:
            pytest.skip(
                "Windows junction creation is unavailable: "
                + completed.stderr.strip()
            )
        primitive = "junction"
    else:
        if windows_junction_only:
            pytest.skip("Windows junction regression requires Windows")
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"directory symlink creation is unavailable: {exc}")
        primitive = "symlink"

    try:
        yield primitive
    finally:
        if os.path.lexists(link):
            if os.name == "nt":
                os.rmdir(link)
            else:
                link.unlink()
        assert not os.path.lexists(link)
        assert target.is_dir()


def with_reparse_point_attribute(value: os.stat_result) -> SimpleNamespace:
    return SimpleNamespace(
        st_dev=value.st_dev,
        st_ino=value.st_ino,
        st_mode=value.st_mode,
        st_size=value.st_size,
        st_mtime_ns=value.st_mtime_ns,
        st_ctime_ns=value.st_ctime_ns,
        st_file_attributes=(
            getattr(value, "st_file_attributes", 0)
            | REPARSE_POINT_ATTRIBUTE
        ),
    )
