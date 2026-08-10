from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.verify_wixqa_multidoc_attribution import verify_public_evidence


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = REPOSITORY_ROOT / "docs" / "multidoc_attribution" / "evidence"
DIAGNOSTIC_SHA = "122bef3672dac07bc76e6686ce0f4e67b14b16b9"


def test_committed_multidoc_attribution_evidence_verifies() -> None:
    result = verify_public_evidence(
        EVIDENCE_DIR,
        expected_code_revision=DIAGNOSTIC_SHA,
    )
    assert result["status"] == "VERIFIED"
    assert result["case_count"] == 20
    assert result["unknown_count"] == 0


def test_multidoc_attribution_verifier_rejects_tampered_aggregate(
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_DIR, evidence_dir)
    aggregate_path = evidence_dir / "aggregate_v1.json"
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["ledger_false_completeness_count"] -= 1
    aggregate_path.write_text(json.dumps(aggregate), encoding="utf-8")

    with pytest.raises(ValueError, match="does not recompute"):
        verify_public_evidence(evidence_dir)


def test_multidoc_attribution_verifier_rejects_private_question_text(
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_DIR, evidence_dir)
    case_path = evidence_dir / "case_matrix_v1.json"
    case_payload = json.loads(case_path.read_text(encoding="utf-8"))
    case_payload["cases"][0]["question"] = "private text"
    case_path.write_text(json.dumps(case_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden public keys"):
        verify_public_evidence(evidence_dir)
