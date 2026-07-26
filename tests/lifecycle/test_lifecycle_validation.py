from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app.lifecycle.validation import (
    LifecycleHandoff,
    validate_lifecycle_repository,
)


def test_repository_validation_checks_cross_file_references(
    lifecycle_repository: Path,
) -> None:
    report = validate_lifecycle_repository(
        lifecycle_repository,
        run_public_audit=False,
    )

    assert report.traceability_rows == 1
    assert report.append_only_anchors == 6
    assert report.failures == 1

    traceability = (
        lifecycle_repository / "docs" / "lifecycle" / "TRACEABILITY.csv"
    )
    with traceability.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows[0]["design_id"] = "ADR-LC-999"
    with traceability.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(ValueError, match="unknown decision ADR-LC-999"):
        validate_lifecycle_repository(
            lifecycle_repository,
            run_public_audit=False,
        )


def test_handoff_open_failures_must_match_failure_records(
    lifecycle_repository: Path,
) -> None:
    handoff_path = (
        lifecycle_repository / "docs" / "lifecycle" / "CODEX_HANDOFF.json"
    )
    payload = json.loads(handoff_path.read_text(encoding="utf-8"))
    payload["open_failures"] = ["FAIL-LC-001"]
    handoff_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="open_failures"):
        validate_lifecycle_repository(
            lifecycle_repository,
            run_public_audit=False,
        )


def test_handoff_rejects_unknown_fields(lifecycle_repository: Path) -> None:
    handoff_path = (
        lifecycle_repository / "docs" / "lifecycle" / "CODEX_HANDOFF.json"
    )
    payload = json.loads(handoff_path.read_text(encoding="utf-8"))
    payload["unreviewed_claim"] = "production ready"

    with pytest.raises(Exception, match="unreviewed_claim"):
        LifecycleHandoff.model_validate(payload)


def test_traceability_rejects_symlinked_implementation_parent(
    lifecycle_repository: Path,
) -> None:
    linked = lifecycle_repository / "linked-implementation"
    try:
        linked.symlink_to(
            lifecycle_repository / "app" / "lifecycle",
            target_is_directory=True,
        )
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")

    traceability = (
        lifecycle_repository / "docs" / "lifecycle" / "TRACEABILITY.csv"
    )
    with traceability.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows[0]["implementation_paths"] = "linked-implementation/validation.py"
    with traceability.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(ValueError, match="symlink"):
        validate_lifecycle_repository(
            lifecycle_repository,
            run_public_audit=False,
        )


def test_lifecycle_validation_cli_emits_bounded_summary(
    lifecycle_repository: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.validate_lifecycle_evidence import main

    exit_code = main(
        [
            "--root",
            str(lifecycle_repository),
            "--skip-public-audit",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "lifecycle_evidence_validation_v1"
    assert output["failures"] == 1
    assert "root" not in output
    assert "content" not in json.dumps(output).lower()
