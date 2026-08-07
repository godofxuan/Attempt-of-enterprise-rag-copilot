from __future__ import annotations

import json
from pathlib import Path

from scripts.audit_finqa_service_wiring_v2 import run_audit


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "external_datasets" / "evidence"


def test_e19_public_evidence_is_reproducible_and_passes_all_checks() -> None:
    expected = json.loads(
        (EVIDENCE / "finqa_service_wiring_public_v2.json").read_text(
            encoding="ascii"
        )
    )
    actual = run_audit(
        protocol_path=EVIDENCE / "finqa_service_wiring_protocol_v2.json"
    )

    assert actual == expected
    assert all(actual["gate_checks"].values())
    assert actual["public_content_findings"] == 0
