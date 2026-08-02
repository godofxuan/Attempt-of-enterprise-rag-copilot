from __future__ import annotations

from decimal import Decimal

import pytest

from app.external_datasets.finqa_controlled_program import (
    CONTROLLED_CONSTANT_VALUES,
    compile_and_execute_controlled_program,
)
from app.external_datasets.finqa_numeric_evidence_v2 import (
    NumericCandidateV2,
    extract_numeric_candidates_v2,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)
from app.external_datasets.finqa_typed_program import (
    TypedProgramValidationError,
)


def _candidate(
    text: str = "120",
    evidence_id: str = "table_1",
) -> NumericCandidateV2:
    return extract_numeric_candidates_v2(
        source_id="report.pdf",
        evidence_id=evidence_id,
        text=text,
        kind="table_cell",
        table_id="table-main",
        row_header="Revenue",
        column_header="2020",
    )[0]


def _divide_by_two_payload(candidate: NumericCandidateV2) -> dict:
    return {
        "dsl_version": "finqa_controlled_financial_dsl_v1",
        "steps": [
            {
                "step_id": "step-01",
                "operation": "DIV",
                "arguments": [
                    {"candidate_id": candidate.candidate_id},
                    {"constant_id": "const_2"},
                ],
            }
        ],
        "output_step_id": "step-01",
    }


def _run(
    *,
    payload: dict,
    candidates: tuple[NumericCandidateV2, ...],
    admitted_evidence_ids: set[str],
):
    return compile_and_execute_controlled_program(
        planner_payload=payload,
        candidates=candidates,
        admitted_evidence_ids=admitted_evidence_ids,
        intent=extract_financial_question_intent_v2(
            "What was revenue in 2020 divided by two?"
        ),
    )


def test_controlled_constant_executes_without_fake_evidence() -> None:
    candidate = _candidate()

    result = _run(
        payload=_divide_by_two_payload(candidate),
        candidates=(candidate,),
        admitted_evidence_ids={candidate.evidence_id},
    )

    assert result.value == Decimal("60")
    assert result.candidate_ids == (candidate.candidate_id,)
    assert result.evidence_ids == (candidate.evidence_id,)
    assert result.controlled_constant_ids == ("const_2",)
    assert result.diagnostics.controlled_constant_count == 1
    assert CONTROLLED_CONSTANT_VALUES["const_1000"] == Decimal("1000")


def test_unknown_constant_is_rejected_by_strict_schema() -> None:
    candidate = _candidate()
    payload = _divide_by_two_payload(candidate)
    payload["steps"][0]["arguments"][1] = {"constant_id": "const_7"}

    with pytest.raises(TypedProgramValidationError) as error:
        _run(
            payload=payload,
            candidates=(candidate,),
            admitted_evidence_ids={candidate.evidence_id},
        )

    assert error.value.reason == "invalid_program_schema"


def test_controlled_program_still_enforces_admitted_evidence() -> None:
    candidate = _candidate()

    with pytest.raises(TypedProgramValidationError) as error:
        _run(
            payload=_divide_by_two_payload(candidate),
            candidates=(candidate,),
            admitted_evidence_ids=set(),
        )

    assert error.value.reason == "unadmitted_source"


def test_controlled_program_still_enforces_source_bound_identity() -> None:
    candidate = _candidate()
    tampered = candidate.model_copy(
        update={"candidate_id": f"num-{'a' * 20}"}
    )

    with pytest.raises(TypedProgramValidationError) as error:
        _run(
            payload=_divide_by_two_payload(tampered),
            candidates=(tampered,),
            admitted_evidence_ids={tampered.evidence_id},
        )

    assert error.value.reason == "missing_provenance"


def test_controlled_program_rejects_dead_steps() -> None:
    candidate = _candidate()
    payload = _divide_by_two_payload(candidate)
    payload["steps"].append(
        {
            "step_id": "step-02",
            "operation": "DIV",
            "arguments": [
                {"candidate_id": candidate.candidate_id},
                {"constant_id": "const_3"},
            ],
        }
    )
    payload["output_step_id"] = "step-02"

    with pytest.raises(TypedProgramValidationError) as error:
        _run(
            payload=payload,
            candidates=(candidate,),
            admitted_evidence_ids={candidate.evidence_id},
        )

    assert error.value.reason == "invalid_program_schema"
