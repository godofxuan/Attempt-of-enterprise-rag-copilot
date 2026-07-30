from __future__ import annotations

import json

from scripts.audit_finqa_numeric_evidence import DEFAULT_PUBLIC_OUTPUT
from scripts.verify_finqa_numeric_evidence_public import (
    _FORBIDDEN_KEYS,
    _walk_keys,
    verify_public_evidence,
)


def test_committed_numeric_evidence_public_artifact_is_valid():
    summary = verify_public_evidence(DEFAULT_PUBLIC_OUTPUT)

    assert summary.decision == "INPUT_GATE_PASSED"
    assert summary.views["v2_closure_post"].complete_case_count == 58
    assert summary.model_call_count == 0


def test_public_summary_contains_no_case_level_keys():
    payload = json.loads(DEFAULT_PUBLIC_OUTPUT.read_text(encoding="utf-8"))

    assert not (_walk_keys(payload["summary"]) & _FORBIDDEN_KEYS)
