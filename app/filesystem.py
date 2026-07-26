from __future__ import annotations

import os
import time
from pathlib import Path

_WINDOWS_DIRECTORY_MOVE_ATTEMPTS = 8
_WINDOWS_DIRECTORY_MOVE_BASE_DELAY_SECONDS = 0.01


def _move_once(source: Path, destination: Path, *, replace: bool) -> None:
    operation = os.replace if replace else os.rename
    operation(source, destination)


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
