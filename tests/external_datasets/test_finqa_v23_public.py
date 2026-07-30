from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.external_datasets.finqa_typed_retrospective import (
    canonical_json_bytes,
)
from scripts.verify_finqa_v23_calibration_public import (
    DEFAULT_OUTPUT,
    verify_public_evidence,
)


def test_committed_v23_public_evidence_verifies_without_private_data() -> None:
    evidence = verify_public_evidence(DEFAULT_OUTPUT, private_root=None)

    assert evidence.summary.decision == "CALIBRATION_REJECTED"
    assert evidence.summary.b1_v23_intervention.execution_accuracy == 0.2
    assert evidence.diagnostics.input_complete_case_count == 58
    assert evidence.diagnostics.answered_wrong_count == 32
    assert evidence.diagnostics.protocol_error_count == 16
    assert evidence.diagnostics.gold_multi_step_count == 28


def test_v23_public_evidence_rejects_inconsistent_diagnostics(
    tmp_path: Path,
) -> None:
    raw = json.loads(DEFAULT_OUTPUT.read_bytes())
    raw["diagnostics"]["answered_wrong_count"] = 31
    tampered = tmp_path / "evidence.json"
    tampered.write_bytes(canonical_json_bytes(raw, newline=True))

    with pytest.raises(ValueError, match="diagnostic totals"):
        verify_public_evidence(tampered, private_root=None)
