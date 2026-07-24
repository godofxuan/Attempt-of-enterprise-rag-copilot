from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "data" / "v2" / "public" / "corpus_expansion_v2"


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
