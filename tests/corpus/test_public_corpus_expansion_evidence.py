from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "data" / "v2" / "public" / "corpus_expansion_v2"


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def rewrite_checksums(package: Path) -> None:
    content_files = (
        "README.md",
        "manifest.json",
        "index_manifest.json",
        "quality.json",
        "retrieval_dev_summary.json",
        "retrieval_test_summary.json",
        "verify.py",
    )
    rows = [
        f"{hashlib.sha256((package / name).read_bytes()).hexdigest()}  {name}"
        for name in content_files
    ]
    (package / "checksums.sha256").write_text(
        "\n".join(rows) + "\n",
        encoding="utf-8",
    )


def run_verifier(package: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(package / "verify.py"),
            "--package",
            str(package),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_public_corpus_expansion_evidence_verifies() -> None:
    result = run_verifier(PACKAGE)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report == {
        "profile_id": "expanded",
        "verified": True,
    }


def test_public_evidence_source_files_match_frozen_manifest() -> None:
    manifest = json.loads(
        (PACKAGE / "manifest.json").read_text(encoding="utf-8")
    )

    for section in ("facts", "profile"):
        source = ROOT / manifest[section]["path"]
        assert source.is_file()
        assert hashlib.sha256(source.read_bytes()).hexdigest() == (
            manifest[section]["file_sha256"]
        )


def test_public_corpus_expansion_evidence_rejects_tampering(
    tmp_path: Path,
) -> None:
    package = tmp_path / "corpus_expansion_v2"
    shutil.copytree(PACKAGE, package)
    quality_path = package / "quality.json"
    quality_path.write_text(
        quality_path.read_text(encoding="utf-8").replace(
            '"document_count": 240',
            '"document_count": 241',
        ),
        encoding="utf-8",
    )

    result = run_verifier(package)

    assert result.returncode == 1
    assert "checksum mismatch" in result.stderr


def test_public_evidence_rejects_semantic_tampering_after_rehash(
    tmp_path: Path,
) -> None:
    package = tmp_path / "corpus_expansion_v2"
    shutil.copytree(PACKAGE, package)
    quality_path = package / "quality.json"
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality["release_pass"] = False
    write_json(quality_path, quality)
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["quality"]["sha256"] = hashlib.sha256(
        quality_path.read_bytes()
    ).hexdigest()
    write_json(manifest_path, manifest)
    rewrite_checksums(package)

    result = run_verifier(package)

    assert result.returncode == 1
    assert "frozen release contract" in result.stderr


def test_public_evidence_rejects_unknown_fields_after_rehash(
    tmp_path: Path,
) -> None:
    package = tmp_path / "corpus_expansion_v2"
    shutil.copytree(PACKAGE, package)
    quality_path = package / "quality.json"
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality["unreviewed_metric"] = 1
    write_json(quality_path, quality)
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["quality"]["sha256"] = hashlib.sha256(
        quality_path.read_bytes()
    ).hexdigest()
    write_json(manifest_path, manifest)
    rewrite_checksums(package)

    result = run_verifier(package)

    assert result.returncode == 1
    assert "frozen release contract" in result.stderr
