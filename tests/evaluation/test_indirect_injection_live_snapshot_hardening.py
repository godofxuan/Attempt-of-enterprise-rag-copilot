from __future__ import annotations

import os
import stat
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.evaluation import indirect_injection_live_writer as live_writer
from tests.evaluation import test_indirect_injection_live_writer as live_fixtures


@pytest.fixture(scope="module")
def writer_v3_inputs(tmp_path_factory: pytest.TempPathFactory):
    return live_fixtures.writer_v3_inputs.__wrapped__(tmp_path_factory)


def _publish_v3(tmp_path: Path, writer_v3_inputs) -> Path:
    bundle, built, result = writer_v3_inputs
    return live_writer.publish_live_security_run(
        tmp_path / "runs",
        live_fixtures._manifest_v3(bundle, built, result),
        result,
        paired_evidence="safe",
        commands="safe",
        test_output="safe",
        forbidden_texts=live_fixtures._forbidden_texts(bundle),
    )


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _changed_stat(observed: os.stat_result, *, redirect: bool = False) -> object:
    mode = observed.st_mode
    if redirect:
        mode = stat.S_IFLNK | stat.S_IMODE(mode)
    return SimpleNamespace(
        st_dev=observed.st_dev,
        st_ino=observed.st_ino + 1,
        st_mode=mode,
        st_size=observed.st_size,
        st_mtime_ns=observed.st_mtime_ns,
        st_ctime_ns=observed.st_ctime_ns,
        st_file_attributes=getattr(observed, "st_file_attributes", 0),
    )


def test_v3_snapshot_reads_each_exact_file_once_without_path_reopen(
    tmp_path: Path,
    writer_v3_inputs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _publish_v3(tmp_path, writer_v3_inputs)
    expected_names = {*live_writer._ARTIFACT_NAMES, "manifest.json"}
    calls: Counter[str] = Counter()
    real_snapshot_read = live_writer._read_regular_file_snapshot
    real_read_bytes = Path.read_bytes
    real_read_text = Path.read_text

    def counted_snapshot_read(path: Path, label: str):
        calls[path.name] += 1
        return real_snapshot_read(path, label)

    def reject_run_read_bytes(path: Path) -> bytes:
        if _absolute(path).parent == _absolute(target):
            raise AssertionError("verified run file was reopened with Path.read_bytes")
        return real_read_bytes(path)

    def reject_run_read_text(path: Path, *args, **kwargs) -> str:
        if _absolute(path).parent == _absolute(target):
            raise AssertionError("verified run file was reopened with Path.read_text")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(
        live_writer,
        "_read_regular_file_snapshot",
        counted_snapshot_read,
    )
    monkeypatch.setattr(Path, "read_bytes", reject_run_read_bytes)
    monkeypatch.setattr(Path, "read_text", reject_run_read_text)

    snapshot = live_writer.load_verified_live_security_run_snapshot(target)

    assert calls == Counter({name: 1 for name in expected_names})
    assert snapshot.artifact_bytes("summary.json").startswith(b"{\n")
    with pytest.raises(KeyError, match="unknown live security artifact"):
        snapshot.artifact_bytes("not-in-the-package.txt")


def test_descriptor_snapshot_rejects_coordinated_a_b_a_file_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_path = tmp_path / "selected.txt"
    replacement_path = tmp_path / "replacement.txt"
    selected_path.write_bytes(b"AAAA")
    replacement_path.write_bytes(b"BBBB")
    real_open = os.open

    def coordinated_open(path, flags, *args, **kwargs):
        if _absolute(Path(path)) == _absolute(selected_path):
            return real_open(replacement_path, flags, *args, **kwargs)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", coordinated_open)

    with pytest.raises(ValueError, match="identity changed before descriptor read"):
        live_writer._read_regular_file_snapshot(
            selected_path,
            "coordinated replacement fixture",
        )


def test_v3_snapshot_rejects_redirecting_lexical_parent_component(
    tmp_path: Path,
    writer_v3_inputs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _publish_v3(tmp_path, writer_v3_inputs)
    redirected_parent = _absolute(target.parent)
    real_lstat = Path.lstat

    def redirected_lstat(path: Path):
        observed = real_lstat(path)
        if _absolute(path) == redirected_parent:
            return _changed_stat(observed, redirect=True)
        return observed

    monkeypatch.setattr(Path, "lstat", redirected_lstat)

    with pytest.raises(ValueError, match="redirecting"):
        live_writer.load_verified_live_security_run_snapshot(target)


def test_v3_snapshot_detects_parent_identity_replacement_after_capture(
    tmp_path: Path,
    writer_v3_inputs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _publish_v3(tmp_path, writer_v3_inputs)
    snapshot = live_writer.load_verified_live_security_run_snapshot(target)
    replaced_parent = _absolute(target.parent)
    real_lstat = Path.lstat

    def replaced_lstat(path: Path):
        observed = real_lstat(path)
        if _absolute(path) == replaced_parent:
            return _changed_stat(observed)
        return observed

    monkeypatch.setattr(Path, "lstat", replaced_lstat)

    with pytest.raises(ValueError, match="directory identity changed"):
        snapshot.assert_unchanged()


def test_v3_snapshot_retains_bytes_and_detects_artifact_replacement(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    target = _publish_v3(tmp_path, writer_v3_inputs)
    snapshot = live_writer.load_verified_live_security_run_snapshot(target)
    captured = snapshot.artifact_bytes("summary.json")
    replacement = tmp_path / "replacement-summary.json"
    replacement.write_bytes(captured + b" ")
    os.replace(replacement, target / "summary.json")

    assert snapshot.artifact_bytes("summary.json") == captured
    with pytest.raises(ValueError, match="artifact changed"):
        snapshot.assert_unchanged()
    with pytest.raises(ValueError, match="artifact changed"):
        snapshot.assert_manifest_unchanged()
