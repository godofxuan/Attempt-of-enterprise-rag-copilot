from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs" / "review" / "P1_INTEGRITY_EVIDENCE_MANIFEST.json"
IMPLEMENTATION_COMMIT = "730f58e2988f981780a76ca66a878c675d873f50"


def test_p1_integrity_manifest_binds_exact_implementation_artifacts() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "p1-integrity-evidence-manifest/1.0"
    assert manifest["source_commit"] == IMPLEMENTATION_COMMIT
    assert manifest["remote_ci"]["head_sha"] == IMPLEMENTATION_COMMIT
    assert manifest["remote_ci"]["conclusion"] == "success"

    for artifact in manifest["artifacts"]:
        path = ROOT / artifact["path"]
        content = path.read_bytes()
        assert path.is_file(), artifact["path"]
        assert len(content) == artifact["size"], artifact["path"]
        assert hashlib.sha256(content).hexdigest() == artifact["sha256"], artifact["path"]


def test_p1_integrity_manifest_records_all_required_ci_jobs() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    jobs = {job["name"]: job["conclusion"] for job in manifest["remote_ci"]["jobs"]}

    assert jobs == {
        "postgres-checkpointer-integration": "success",
        "deterministic-windows-latest": "success",
        "deterministic-ubuntu-latest": "success",
        "linux-container-contract": "success",
    }
