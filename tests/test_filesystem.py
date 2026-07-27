from __future__ import annotations

import os
from pathlib import Path

import pytest

from app import filesystem as filesystem_module
from app.evaluation.publication_paths import _atomic_publish_no_replace
from app.filesystem import atomic_directory_move


def _sharing_denial() -> PermissionError:
    error = PermissionError(13, "synthetic sharing denial")
    error.winerror = 5
    return error


@pytest.mark.skipif(os.name != "nt", reason="Windows publication retry")
def test_atomic_directory_move_retries_transient_windows_denial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "stage"
    target = tmp_path / "target"
    source.mkdir()
    original_move = filesystem_module._move_once
    attempts = 0

    def deny_twice(
        source_path: Path,
        destination_path: Path,
        *,
        replace: bool,
    ) -> None:
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise _sharing_denial()
        original_move(source_path, destination_path, replace=replace)

    monkeypatch.setattr(filesystem_module, "_move_once", deny_twice)
    monkeypatch.setattr(filesystem_module.time, "sleep", lambda _: None)

    atomic_directory_move(source, target)

    assert 3 <= attempts <= filesystem_module._WINDOWS_DIRECTORY_MOVE_ATTEMPTS
    assert target.is_dir()
    assert not source.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows publication retry")
def test_evaluation_publication_uses_shared_windows_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "stage"
    target = tmp_path / "target"
    source.mkdir()
    original_move = filesystem_module._move_once
    attempts = 0

    def deny_twice(
        source_path: Path,
        destination_path: Path,
        *,
        replace: bool,
    ) -> None:
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise _sharing_denial()
        original_move(source_path, destination_path, replace=replace)

    monkeypatch.setattr(filesystem_module, "_move_once", deny_twice)
    monkeypatch.setattr(filesystem_module.time, "sleep", lambda _: None)

    _atomic_publish_no_replace(source, target)

    assert attempts == 3
    assert target.is_dir()
    assert not source.exists()


def test_atomic_directory_move_does_not_retry_other_permission_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "stage"
    target = tmp_path / "target"
    source.mkdir()
    attempts = 0

    def deny(
        source_path: Path,
        destination_path: Path,
        *,
        replace: bool,
    ) -> None:
        nonlocal attempts
        del source_path, destination_path, replace
        attempts += 1
        error = PermissionError(13, "permanent denial")
        error.winerror = 32
        raise error

    monkeypatch.setattr(filesystem_module, "_move_once", deny)

    with pytest.raises(PermissionError):
        atomic_directory_move(source, target)

    assert attempts == 1
    assert source.is_dir()
    assert not target.exists()


def test_atomic_directory_move_does_not_hide_target_collision(
    tmp_path: Path,
) -> None:
    source = tmp_path / "stage"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()

    with pytest.raises(FileExistsError):
        atomic_directory_move(source, target)

    assert source.is_dir()
    assert target.is_dir()
