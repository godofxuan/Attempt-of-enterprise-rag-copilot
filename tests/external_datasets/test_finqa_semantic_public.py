from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.external_datasets.finqa_typed_retrospective import (
    canonical_json_bytes,
)
from scripts.verify_finqa_semantic_planning_public import (
    DEFAULT_OUTPUT,
    verify_public_evidence,
)


def test_committed_semantic_evidence_verifies_public_only() -> None:
    evidence = verify_public_evidence(DEFAULT_OUTPUT, private_root=None)
    demos = evidence.summary.candidates["B4_ROLE_DYNAMIC_DEMOS"]

    assert evidence.summary.decision == "CALIBRATION_REJECTED"
    assert evidence.summary.internal_validation_status == "NOT_RUN"
    assert evidence.summary.frozen_test_status == "UNTOUCHED"
    assert demos.metrics.execution_accuracy == 13 / 60
    assert demos.metrics.grounded_execution_accuracy == 12 / 60
    assert evidence.diagnostics.answered_wrong_counts[
        "B4_ROLE_DYNAMIC_DEMOS"
    ] == 31
    assert evidence.diagnostics.unique_demo_payload_count == 59


def test_semantic_public_evidence_rejects_inconsistent_diagnostics(
    tmp_path: Path,
) -> None:
    raw = json.loads(DEFAULT_OUTPUT.read_bytes())
    raw["diagnostics"]["answered_wrong_counts"][
        "B4_ROLE_DYNAMIC_DEMOS"
    ] = 30
    tampered = tmp_path / "evidence.json"
    tampered.write_bytes(canonical_json_bytes(raw, newline=True))

    with pytest.raises(ValueError, match="conditional accuracy"):
        verify_public_evidence(tampered, private_root=None)
