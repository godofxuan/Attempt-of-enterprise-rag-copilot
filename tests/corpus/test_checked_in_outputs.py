from pathlib import Path

import pytest

from app.corpus.artifacts import (
    load_smoke_manifest,
    write_canonical_eval,
    write_smoke_fixture,
)
from app.corpus.generator import load_facts, load_profile


ROOT = Path(__file__).resolve().parents[2]
FACTS_PATH = ROOT / "data" / "v2" / "facts" / "company_facts_v1.json"
PROFILE_PATH = ROOT / "data" / "v2" / "config" / "demo.json"
CHECKED_EVAL_DIR = ROOT / "data" / "v2" / "eval"
CHECKED_SMOKE_DIR = ROOT / "data" / "v2" / "fixtures" / "smoke"


def inputs():
    return load_facts(FACTS_PATH), load_profile(PROFILE_PATH)


def relative_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_canonical_eval_writer_freezes_three_files_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    facts, profile = inputs()
    output_dir = tmp_path / "eval"

    result = write_canonical_eval(output_dir, facts, profile)

    assert set(relative_files(output_dir)) == {
        "dev.json",
        "test.json",
        "test_manifest.sha256",
    }
    assert result["dev_count"] == 24
    assert result["test_count"] == 28
    assert len(result["test_sha256"]) == 64
    with pytest.raises(FileExistsError, match="frozen eval directory"):
        write_canonical_eval(output_dir, facts, profile)


def test_smoke_fixture_contains_one_document_per_format_and_multiple_sources(
    tmp_path: Path,
) -> None:
    facts, profile = inputs()
    output_dir = tmp_path / "smoke"

    manifest = write_smoke_fixture(output_dir, facts, profile)
    loaded = load_smoke_manifest(output_dir / "manifest.json")

    assert loaded == manifest
    assert len(manifest.documents) == 5
    assert {document.format for document in manifest.documents} == {
        "md",
        "txt",
        "html",
        "csv",
        "jsonl",
    }
    assert len({document.source_type for document in manifest.documents}) == 5
    assert len(list((output_dir / "documents").iterdir())) == 5


def test_checked_in_eval_bundle_is_exact_generator_output(tmp_path: Path) -> None:
    facts, profile = inputs()
    regenerated = tmp_path / "eval"
    write_canonical_eval(regenerated, facts, profile)

    assert relative_files(CHECKED_EVAL_DIR) == relative_files(regenerated)


def test_checked_in_smoke_fixture_is_exact_generator_output(tmp_path: Path) -> None:
    facts, profile = inputs()
    regenerated = tmp_path / "smoke"
    write_smoke_fixture(regenerated, facts, profile)

    assert relative_files(CHECKED_SMOKE_DIR) == relative_files(regenerated)
