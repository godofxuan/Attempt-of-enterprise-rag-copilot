import json
from pathlib import Path

import pytest

from app.corpus.artifacts import _rename_with_retry, load_manifest, write_corpus
from app.corpus.generator import load_facts, load_profile


ROOT = Path(__file__).resolve().parents[2]
FACTS_PATH = ROOT / "data" / "v2" / "facts" / "company_facts_v1.json"
PROFILE_PATH = ROOT / "data" / "v2" / "config" / "demo.json"


def inputs():
    return load_facts(FACTS_PATH), load_profile(PROFILE_PATH)


def test_transient_windows_directory_lock_is_retried(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    original_rename = Path.rename
    attempts = 0

    def flaky_rename(path: Path, destination: Path):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            error = PermissionError("transient directory lock")
            error.winerror = 5
            raise error
        return original_rename(path, destination)

    monkeypatch.setattr(Path, "rename", flaky_rename)

    _rename_with_retry(source, target, delays=(0.0,))

    assert attempts >= 2
    assert target.is_dir()


def test_same_seed_writes_byte_identical_manifests(tmp_path: Path) -> None:
    facts, profile = inputs()
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first = write_corpus(first_dir, facts, profile, seed=20260716)
    second = write_corpus(second_dir, facts, profile, seed=20260716)

    assert first == second
    assert (first_dir / "manifest.json").read_bytes() == (
        second_dir / "manifest.json"
    ).read_bytes()
    assert first.document_count == 72
    assert len(first.documents) == 72
    assert len(list((first_dir / "documents").iterdir())) == 72
    assert (first_dir / "eval" / "dev.json").is_file()
    assert (first_dir / "eval" / "test.json").is_file()
    assert (first_dir / "eval" / "test_manifest.sha256").is_file()


def test_manifest_records_content_hashes_and_full_governance_metadata(
    tmp_path: Path,
) -> None:
    facts, profile = inputs()
    output_dir = tmp_path / "corpus"

    manifest = write_corpus(output_dir, facts, profile)
    loaded = load_manifest(output_dir / "manifest.json")
    first = loaded.documents[0]
    payload = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))

    assert loaded == manifest
    assert len(manifest.facts_sha256) == 64
    assert len(manifest.profile_sha256) == 64
    assert len(first.sha256) == 64
    assert first.path.startswith("documents/")
    assert first.metadata.actual_department
    assert first.metadata.tenant == "starbridge-cn"
    assert first.metadata.acl_groups
    assert "created_at" not in payload
    assert str(output_dir) not in (output_dir / "manifest.json").read_text(
        encoding="utf-8"
    )


def test_existing_output_is_not_overwritten_without_force(tmp_path: Path) -> None:
    facts, profile = inputs()
    output_dir = tmp_path / "corpus"
    write_corpus(output_dir, facts, profile)

    with pytest.raises(FileExistsError, match="already exists"):
        write_corpus(output_dir, facts, profile)


def test_force_refuses_to_delete_an_unmarked_directory(tmp_path: Path) -> None:
    facts, profile = inputs()
    output_dir = tmp_path / "user-files"
    output_dir.mkdir()
    user_file = output_dir / "keep-me.txt"
    user_file.write_text("personal", encoding="utf-8")

    with pytest.raises(PermissionError, match="not a generated corpus"):
        write_corpus(output_dir, facts, profile, force=True)

    assert user_file.read_text(encoding="utf-8") == "personal"


def test_force_replaces_only_a_marked_generated_corpus(tmp_path: Path) -> None:
    facts, profile = inputs()
    output_dir = tmp_path / "corpus"
    first = write_corpus(output_dir, facts, profile, seed=20260716)

    second = write_corpus(output_dir, facts, profile, seed=20260717, force=True)

    assert second.seed == 20260717
    assert first != second
    assert load_manifest(output_dir / "manifest.json") == second
