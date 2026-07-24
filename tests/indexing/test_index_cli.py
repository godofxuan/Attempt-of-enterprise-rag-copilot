from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.corpus.artifacts import write_corpus
from app.corpus.generator import load_facts, load_profile
from scripts import build_indexes_v2


ROOT = Path(__file__).resolve().parents[2]
FACTS = ROOT / "data" / "v2" / "facts" / "company_facts_v1.json"
PROFILE = ROOT / "data" / "v2" / "config" / "demo.json"


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, text: str) -> list[float]:
        self.calls.append(text)
        total = sum(ord(character) for character in text)
        return [
            float((total % 97) + 1),
            float((len(text) % 31) + 1),
            float((total % 17) + 1),
            1.0,
        ]


@pytest.fixture(scope="module")
def corpus_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("index-cli-corpus") / "corpus"
    write_corpus(path, load_facts(FACTS), load_profile(PROFILE))
    return path


def run_cli(*args: str):
    return subprocess.run(
        [sys.executable, "-m", "scripts.build_indexes_v2", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def build_args(corpus_dir: Path, output_dir: Path, run_id: str) -> list[str]:
    return [
        "--input-dir",
        str(corpus_dir),
        "--output-dir",
        str(output_dir),
        "--profile",
        "demo",
        "--run-id",
        run_id,
        "--chunker",
        "fixed",
    ]


def test_help_exits_without_writing(tmp_path: Path) -> None:
    output_dir = tmp_path / "must-not-exist"

    result = run_cli("--output-dir", str(output_dir), "--help")

    assert result.returncode == 0
    assert "--dry-run" in result.stdout
    assert "--activate-existing" in result.stdout
    assert "--chunker" in result.stdout
    assert not output_dir.exists()


def test_required_paths_fail_before_any_output(tmp_path: Path) -> None:
    result = run_cli("--run-id", "run-one")

    assert result.returncode != 0
    assert "--input-dir" in result.stderr
    assert not (tmp_path / "indexes-v2").exists()


@pytest.mark.parametrize("profile", ["expanded", "expanded_benchmark"])
def test_index_cli_accepts_expanded_corpus_profiles(profile: str) -> None:
    args = build_indexes_v2.build_parser().parse_args(
        [
            "--input-dir",
            "generated-corpus",
            "--profile",
            profile,
            "--dry-run",
        ]
    )

    assert args.profile == profile


def test_dry_run_measures_without_embedding_or_writing(
    tmp_path: Path,
    corpus_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "must-not-exist"
    embedder = FakeEmbedder()

    exit_code = build_indexes_v2.main(
        [
            "--input-dir",
            str(corpus_dir),
            "--output-dir",
            str(output_dir),
            "--profile",
            "demo",
            "--chunker",
            "fixed",
            "--dry-run",
        ],
        embed_text=embedder,
    )
    captured = capsys.readouterr()
    summary = json.loads(captured.out)

    assert exit_code == 0, captured.err
    assert summary["action"] == "preview"
    assert summary["source_document_count"] == 72
    assert summary["canonical_document_count"] == 64
    assert summary["indexed_chunk_count"] == 64
    assert summary["written"] is False
    assert embedder.calls == []
    assert not output_dir.exists()


def test_index_cli_rejects_a_corpus_manifest_that_is_not_from_its_preset(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = tmp_path / "drifted-corpus"
    write_corpus(corpus, load_facts(FACTS), load_profile(PROFILE))
    manifest_path = corpus / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["facts_sha256"] = "f" * 64
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )

    exit_code = build_indexes_v2.main(
        [
            "--input-dir",
            str(corpus),
            "--profile",
            "demo",
            "--chunker",
            "fixed",
            "--dry-run",
        ],
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "does not match preset" in captured.err


@pytest.mark.parametrize(
    "run_id, output_dir_factory",
    [
        ("../escape", lambda tmp_path: tmp_path / "indexes-v2"),
        ("run-one", lambda tmp_path: Path(tmp_path.anchor)),
    ],
)
def test_unsafe_run_id_or_output_root_fails_before_embedding(
    tmp_path: Path,
    corpus_dir: Path,
    capsys: pytest.CaptureFixture[str],
    run_id: str,
    output_dir_factory,
) -> None:
    output_dir = output_dir_factory(tmp_path)
    embedder = FakeEmbedder()

    exit_code = build_indexes_v2.main(
        build_args(corpus_dir, output_dir, run_id),
        embed_text=embedder,
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "error:" in captured.err
    assert embedder.calls == []
    assert not (tmp_path / "escape").exists()


def test_build_overwrite_force_and_activate_existing_lifecycle(
    tmp_path: Path,
    corpus_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "中文索引"
    first_embedder = FakeEmbedder()
    first_code = build_indexes_v2.main(
        build_args(corpus_dir, output_dir, "run-one"),
        embed_text=first_embedder,
    )
    first_output = capsys.readouterr()
    first_summary = json.loads(first_output.out)

    assert first_code == 0, first_output.err
    assert first_summary["action"] == "build_and_activate"
    assert first_summary["run_id"] == "run-one"
    assert first_summary["written"] is True
    assert first_summary["activated"] is True
    assert "中文索引" in first_output.out
    assert len(first_embedder.calls) == 64

    refused_embedder = FakeEmbedder()
    refused_code = build_indexes_v2.main(
        build_args(corpus_dir, output_dir, "run-one"),
        embed_text=refused_embedder,
    )
    refused_output = capsys.readouterr()
    assert refused_code == 2
    assert "already exists" in refused_output.err
    assert refused_embedder.calls == []

    second_code = build_indexes_v2.main(
        build_args(corpus_dir, output_dir, "run-two"),
        embed_text=FakeEmbedder(),
    )
    second_output = capsys.readouterr()
    assert second_code == 0, second_output.err
    assert json.loads(second_output.out)["run_id"] == "run-two"

    force_args = build_args(corpus_dir, output_dir, "run-one") + ["--force"]
    force_code = build_indexes_v2.main(force_args, embed_text=FakeEmbedder())
    force_output = capsys.readouterr()
    assert force_code == 0, force_output.err
    assert json.loads(force_output.out)["run_id"] == "run-one"

    rollback_embedder = FakeEmbedder()
    rollback_code = build_indexes_v2.main(
        [
            "--output-dir",
            str(output_dir),
            "--activate-existing",
            "run-two",
        ],
        embed_text=rollback_embedder,
    )
    rollback_output = capsys.readouterr()
    rollback_summary = json.loads(rollback_output.out)
    pointer = json.loads((output_dir / "active.json").read_text(encoding="utf-8"))
    assert rollback_code == 0, rollback_output.err
    assert rollback_summary["action"] == "activate_existing"
    assert rollback_summary["run_id"] == pointer["run_id"] == "run-two"
    assert rollback_summary["written"] is False
    assert rollback_embedder.calls == []
