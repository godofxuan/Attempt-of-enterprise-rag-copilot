import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_cli(*args: str):
    return subprocess.run(
        [sys.executable, "-m", "scripts.generate_enterprise_corpus", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_help_exits_without_writing(tmp_path: Path) -> None:
    output_dir = tmp_path / "must-not-exist"

    result = run_cli("--output-dir", str(output_dir), "--help")

    assert result.returncode == 0
    assert "--dry-run" in result.stdout
    assert "--force" in result.stdout
    assert not output_dir.exists()


def test_dry_run_reports_measured_counts_without_writing(tmp_path: Path) -> None:
    output_dir = tmp_path / "must-not-exist"

    result = run_cli(
        "--profile",
        "demo",
        "--seed",
        "20260716",
        "--output-dir",
        str(output_dir),
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["profile_id"] == "demo"
    assert summary["document_count"] == 72
    assert summary["eval_dev_count"] == 24
    assert summary["eval_test_count"] == 28
    assert summary["written"] is False
    assert not output_dir.exists()


def test_cli_writes_corpus_and_refuses_implicit_overwrite(tmp_path: Path) -> None:
    output_dir = tmp_path / "demo"
    args = (
        "--profile",
        "demo",
        "--seed",
        "20260716",
        "--output-dir",
        str(output_dir),
    )

    first = run_cli(*args)
    second = run_cli(*args)

    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["written"] is True
    assert (output_dir / "manifest.json").is_file()
    assert second.returncode != 0
    assert "already exists" in second.stderr
