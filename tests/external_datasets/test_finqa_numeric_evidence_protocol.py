from pathlib import Path

from app.external_datasets.finqa_numeric_evidence_protocol_erratum import (
    FinQANumericEvidenceProtocolErratum,
)
from app.external_datasets.finqa_numeric_evidence_protocol import (
    load_numeric_evidence_protocol,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_numeric_evidence_protocol_v1.json"
)
ERRATUM_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_numeric_evidence_protocol_erratum_v1.json"
)


def test_tracked_gate_e3_protocol_is_frozen_and_reconciled():
    protocol, digest = load_numeric_evidence_protocol(PROTOCOL_PATH)

    assert len(digest) == 64
    assert protocol.calibration_case_count == 60
    assert protocol.internal_validation_case_count == 40
    assert protocol.internal_validation_status == "NOT_RUN"
    assert protocol.frozen_test_status == "UNTOUCHED"
    assert protocol.baseline.gold_operand_count == 154
    assert protocol.baseline.runtime_input_complete_case_count == 49
    assert protocol.baseline.gold_evidence_complete_case_count == 58
    assert protocol.baseline.normalized_only_complete_case_count == 25
    assert protocol.gates.require_no_gold_runtime_input
    assert protocol.gates.require_added_evidence_guard_scan


def test_gate_e3_protocol_keeps_closure_and_shortlist_bounded():
    protocol, _ = load_numeric_evidence_protocol(PROTOCOL_PATH)

    assert protocol.budgets.max_added_evidence_units == 24
    assert protocol.budgets.max_total_evidence_units == 32
    assert protocol.budgets.max_total_evidence_chars == 8000
    assert protocol.budgets.max_candidates_before_shortlist == 128
    assert protocol.budgets.max_candidates_after_shortlist == 24


def test_gate_e3_erratum_corrects_runtime_input_to_post_shortlist():
    erratum = FinQANumericEvidenceProtocolErratum.model_validate_json(
        ERRATUM_PATH.read_bytes()
    )

    assert erratum.original_value == 49
    assert erratum.post_shortlist_complete_case_count == 48
    assert erratum.complete_cases_lost_by_shortlist == 1
    assert erratum.shortlist_error_count == 0
    assert erratum.internal_validation_status == "NOT_RUN"
