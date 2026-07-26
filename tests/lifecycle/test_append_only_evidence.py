from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.lifecycle.evidence import (
    create_prefix_anchor,
    hash_evidence_artifacts,
    validate_prefix_anchor,
)


def test_accepted_prefix_detects_mutation_and_allows_suffix(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    journal = root / "docs" / "lifecycle" / "01_ENGINEERING_JOURNAL.md"
    journal.parent.mkdir(parents=True)
    journal.write_text(
        "# Journal\n\n## EVID-LC-001\n\nAccepted observation.\n",
        encoding="utf-8",
    )
    anchor = create_prefix_anchor(
        root,
        "docs/lifecycle/01_ENGINEERING_JOURNAL.md",
        accepted_at_gate="G0",
    )

    with journal.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write("\n## EVID-LC-002\n\nNew suffix.\n")
    validate_prefix_anchor(root, anchor)

    content = journal.read_text(encoding="utf-8")
    journal.write_text(
        content.replace("Accepted observation.", "Rewritten observation."),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ValueError, match="accepted prefix hash mismatch"):
        validate_prefix_anchor(root, anchor)


def test_accepted_prefix_detects_truncation(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    failures = root / "docs" / "lifecycle" / "FAILURES.jsonl"
    failures.parent.mkdir(parents=True)
    failures.write_text('{"failure_id":"FAIL-LC-001"}\n', encoding="utf-8")
    anchor = create_prefix_anchor(
        root,
        "docs/lifecycle/FAILURES.jsonl",
        accepted_at_gate="G0",
    )

    failures.write_bytes(b"")

    with pytest.raises(ValueError, match="shorter than accepted prefix"):
        validate_prefix_anchor(root, anchor)


def test_artifact_hash_manifest_is_deterministic_and_bounded(
    tmp_path: Path,
) -> None:
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "b.json").write_bytes(b"second")
    (root / "a.json").write_bytes(b"first")

    manifest = hash_evidence_artifacts(root, ["b.json", "a.json"])

    assert [item.path for item in manifest] == ["a.json", "b.json"]
    assert manifest[0].byte_count == 5
    assert manifest[0].sha256 == hashlib.sha256(b"first").hexdigest()

    with pytest.raises(ValueError, match="repository-relative"):
        hash_evidence_artifacts(root, ["../outside.json"])


def test_artifact_hash_manifest_rejects_duplicate_and_symlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / "evidence"
    root.mkdir()
    artifact = root / "result.json"
    artifact.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate evidence artifact path"):
        hash_evidence_artifacts(root, ["result.json", "result.json"])

    link = root / "linked.json"
    try:
        link.symlink_to(artifact)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")
    with pytest.raises(ValueError, match="symlink"):
        hash_evidence_artifacts(root, ["linked.json"])
