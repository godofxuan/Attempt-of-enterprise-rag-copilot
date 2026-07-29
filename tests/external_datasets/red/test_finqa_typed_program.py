from __future__ import annotations

import hashlib
from decimal import Decimal
from importlib import import_module

import pytest


def _typed_program_api():
    try:
        return import_module("app.external_datasets.finqa_typed_program")
    except ModuleNotFoundError:
        pytest.fail(
            "Gate A RED: app.external_datasets.finqa_typed_program "
            "does not exist until Gate B/C is approved",
            pytrace=False,
        )


def _candidate_id(seed: str) -> str:
    return "num-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def _candidate(
    api,
    *,
    seed: str,
    value: str,
    raw_text: str | None = None,
    metric: str = "revenue",
    entity: str = "company",
    period: str | None = "2020",
    fiscal_year: int | None = 2020,
    unit: str = "usd",
    scale: str = "one",
    source_id: str = "report.pdf",
    evidence_id: str = "table_1",
):
    text = raw_text or value
    return api.NumericCandidate(
        candidate_id=_candidate_id(seed),
        raw_text=text,
        normalized_value=Decimal(value),
        metric=metric,
        entity=entity,
        period=period,
        fiscal_year=fiscal_year,
        unit=unit,
        scale=scale,
        sign=-1 if Decimal(value) < 0 else (1 if Decimal(value) > 0 else 0),
        source_id=source_id,
        evidence_id=evidence_id,
        table_id="table-main",
        row_header=metric,
        column_header=period,
        provenance_span=api.ProvenanceSpan(
            start=0,
            end=len(text),
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        ),
        role="operand",
        extraction_version="finqa_numeric_candidate_v1",
    )


def _intent(
    api,
    *,
    operation: str,
    metric: str | None = "revenue",
    target_period: str | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
    direction: str = "none",
    requested_unit: str = "usd",
):
    return api.FinancialQuestionIntent(
        operation_intent=operation,
        metric=metric,
        entity="company",
        target_period=target_period,
        start_period=start_period,
        end_period=end_period,
        requested_unit=requested_unit,
        requested_scale="one",
        direction=direction,
        intent_version="finqa_financial_question_intent_v1",
    )


def _program(operation: str, arguments: list[dict]) -> dict:
    return {
        "dsl_version": "finqa_typed_financial_dsl_v1",
        "steps": [
            {
                "step_id": "step-01",
                "operation": operation,
                "arguments": arguments,
            }
        ],
        "output_step_id": "step-01",
    }


def _run(api, payload, candidates, intent, admitted=None):
    return api.compile_and_execute_typed_program(
        planner_payload=payload,
        candidates=candidates,
        admitted_evidence_ids=(
            set(admitted)
            if admitted is not None
            else {candidate.evidence_id for candidate in candidates}
        ),
        intent=intent,
    )


def test_adjacent_year_operand_is_rejected() -> None:
    api = _typed_program_api()
    revenue_2019 = _candidate(
        api,
        seed="revenue-2019",
        value="90",
        period="2019",
        fiscal_year=2019,
        evidence_id="table_2019",
    )
    revenue_2020 = _candidate(
        api,
        seed="revenue-2020",
        value="100",
        period="2020",
        fiscal_year=2020,
        evidence_id="table_2020",
    )
    payload = _program(
        "ADD",
        [
            {"candidate_id": revenue_2019.candidate_id},
            {"candidate_id": revenue_2020.candidate_id},
        ],
    )

    with pytest.raises(api.TypedProgramValidationError) as error:
        _run(
            api,
            payload,
            [revenue_2019, revenue_2020],
            _intent(
                api,
                operation="ADD",
                target_period="2020",
            ),
        )

    assert error.value.reason == "temporal_mismatch"


def test_same_year_different_metric_is_rejected() -> None:
    api = _typed_program_api()
    revenue = _candidate(api, seed="revenue", value="120")
    headcount = _candidate(
        api,
        seed="headcount",
        value="120",
        metric="headcount",
        unit="count",
        evidence_id="table_headcount",
    )
    payload = _program(
        "ADD",
        [
            {"candidate_id": revenue.candidate_id},
            {"candidate_id": headcount.candidate_id},
        ],
    )

    with pytest.raises(api.TypedProgramValidationError) as error:
        _run(
            api,
            payload,
            [revenue, headcount],
            _intent(
                api,
                operation="ADD",
                target_period="2020",
            ),
        )

    assert error.value.reason == "metric_mismatch"


def test_percent_change_rejects_reversed_2019_2020_direction() -> None:
    api = _typed_program_api()
    old = _candidate(
        api,
        seed="old-2019",
        value="100",
        period="2019",
        fiscal_year=2019,
        evidence_id="table_2019",
    )
    new = _candidate(
        api,
        seed="new-2020",
        value="120",
        period="2020",
        fiscal_year=2020,
        evidence_id="table_2020",
    )
    reversed_payload = _program(
        "PERCENT_CHANGE",
        [
            {"candidate_id": old.candidate_id},
            {"candidate_id": new.candidate_id},
        ],
    )

    with pytest.raises(api.TypedProgramValidationError) as error:
        _run(
            api,
            reversed_payload,
            [old, new],
            _intent(
                api,
                operation="PERCENT_CHANGE",
                start_period="2019",
                end_period="2020",
                direction="new_over_old",
                requested_unit="ratio",
            ),
        )

    assert error.value.reason == "direction_mismatch"


def test_thousand_and_million_values_use_canonical_scale() -> None:
    api = _typed_program_api()
    million = api.extract_numeric_candidates(
        source_id="report.pdf",
        evidence_id="table_1",
        text="$2.5 million",
        kind="table_cell",
        table_id="table-main",
        row_header="revenue",
        column_header="2020",
        unit_hint="usd",
    )[0]
    thousand = api.extract_numeric_candidates(
        source_id="report.pdf",
        evidence_id="table_2",
        text="$300 thousand",
        kind="table_cell",
        table_id="table-main",
        row_header="revenue",
        column_header="2020",
        unit_hint="usd",
    )[0]
    payload = _program(
        "ADD",
        [
            {"candidate_id": million.candidate_id},
            {"candidate_id": thousand.candidate_id},
        ],
    )

    result = _run(
        api,
        payload,
        [million, thousand],
        _intent(api, operation="ADD", target_period="2020"),
    )

    assert million.normalized_value == Decimal("2500000")
    assert thousand.normalized_value == Decimal("300000")
    assert result.value == Decimal("2800000")
    assert result.unit == "usd"


def test_percent_and_decimal_ratio_normalize_consistently() -> None:
    api = _typed_program_api()
    percent = api.extract_numeric_candidates(
        source_id="report.pdf",
        evidence_id="text_1",
        text="12%",
        kind="text",
        unit_hint="ratio",
    )[0]
    decimal_ratio = api.extract_numeric_candidates(
        source_id="report.pdf",
        evidence_id="text_2",
        text="0.08",
        kind="text",
        unit_hint="ratio",
    )[0]
    payload = _program(
        "ADD",
        [
            {"candidate_id": percent.candidate_id},
            {"candidate_id": decimal_ratio.candidate_id},
        ],
    )

    result = _run(
        api,
        payload,
        [percent, decimal_ratio],
        _intent(
            api,
            operation="ADD",
            metric=None,
            requested_unit="ratio",
        ),
    )

    assert percent.normalized_value == Decimal("0.12")
    assert decimal_ratio.normalized_value == Decimal("0.08")
    assert result.value == Decimal("0.20")


def test_parenthesized_number_preserves_negative_sign() -> None:
    api = _typed_program_api()

    candidate = api.extract_numeric_candidates(
        source_id="report.pdf",
        evidence_id="table_1",
        text="(120)",
        kind="table_cell",
        table_id="table-main",
        row_header="net income",
        column_header="2020",
        unit_hint="usd",
    )[0]

    assert candidate.normalized_value == Decimal("-120")
    assert candidate.sign == -1
    assert candidate.provenance_span.text_sha256 == hashlib.sha256(
        b"(120)"
    ).hexdigest()


def test_model_generated_literal_is_rejected() -> None:
    api = _typed_program_api()
    revenue = _candidate(api, seed="literal-revenue", value="120")
    payload = _program(
        "DIV",
        [
            {"candidate_id": revenue.candidate_id},
            {"literal": "100"},
        ],
    )

    with pytest.raises(api.TypedProgramValidationError) as error:
        _run(
            api,
            payload,
            [revenue],
            _intent(
                api,
                operation="DIV",
                target_period="2020",
                requested_unit="ratio",
            ),
        )

    assert error.value.reason == "literal_only_operand"


def test_candidate_from_non_admitted_evidence_is_rejected() -> None:
    api = _typed_program_api()
    admitted = _candidate(
        api,
        seed="admitted",
        value="120",
        evidence_id="table_admitted",
    )
    blocked = _candidate(
        api,
        seed="blocked",
        value="100",
        evidence_id="table_blocked",
    )
    payload = _program(
        "SUB",
        [
            {"candidate_id": admitted.candidate_id},
            {"candidate_id": blocked.candidate_id},
        ],
    )

    with pytest.raises(api.TypedProgramValidationError) as error:
        _run(
            api,
            payload,
            [admitted, blocked],
            _intent(api, operation="SUB", target_period="2020"),
            admitted={"table_admitted"},
        )

    assert error.value.reason == "unadmitted_source"


def test_equal_values_from_different_sources_have_distinct_ids() -> None:
    api = _typed_program_api()
    first = api.extract_numeric_candidates(
        source_id="report-a.pdf",
        evidence_id="table_1",
        text="100",
        kind="table_cell",
        table_id="table-a",
        row_header="revenue",
        column_header="2020",
        unit_hint="usd",
    )[0]
    second = api.extract_numeric_candidates(
        source_id="report-b.pdf",
        evidence_id="table_1",
        text="100",
        kind="table_cell",
        table_id="table-b",
        row_header="revenue",
        column_header="2020",
        unit_hint="usd",
    )[0]

    assert first.normalized_value == second.normalized_value
    assert first.candidate_id != second.candidate_id
    assert first.provenance_span.text_sha256 == (
        second.provenance_span.text_sha256
    )


def test_previous_step_reference_executes_multistep_program() -> None:
    api = _typed_program_api()
    new = _candidate(api, seed="step-new", value="120")
    old = _candidate(api, seed="step-old", value="100")
    payload = {
        "dsl_version": "finqa_typed_financial_dsl_v1",
        "steps": [
            {
                "step_id": "step-01",
                "operation": "SUB",
                "arguments": [
                    {"candidate_id": new.candidate_id},
                    {"candidate_id": old.candidate_id},
                ],
            },
            {
                "step_id": "step-02",
                "operation": "DIV",
                "arguments": [
                    {"step_id": "step-01"},
                    {"candidate_id": old.candidate_id},
                ],
            },
        ],
        "output_step_id": "step-02",
    }

    result = _run(
        api,
        payload,
        [new, old],
        _intent(
            api,
            operation="DIV",
            target_period="2020",
            requested_unit="ratio",
        ),
    )

    assert result.step_values["step-01"] == Decimal("20")
    assert result.value == Decimal("0.2")


def test_divide_by_zero_fails_closed() -> None:
    api = _typed_program_api()
    numerator = _candidate(api, seed="numerator", value="120")
    zero = _candidate(api, seed="zero", value="0")
    payload = _program(
        "DIV",
        [
            {"candidate_id": numerator.candidate_id},
            {"candidate_id": zero.candidate_id},
        ],
    )

    with pytest.raises(api.TypedProgramValidationError) as error:
        _run(
            api,
            payload,
            [numerator, zero],
            _intent(
                api,
                operation="DIV",
                target_period="2020",
                requested_unit="ratio",
            ),
        )

    assert error.value.reason == "divide_by_zero"


def test_equivalent_commutative_programs_are_both_valid() -> None:
    api = _typed_program_api()
    first = _candidate(api, seed="equivalent-a", value="10")
    second = _candidate(api, seed="equivalent-b", value="20")
    forward = _program(
        "ADD",
        [
            {"candidate_id": first.candidate_id},
            {"candidate_id": second.candidate_id},
        ],
    )
    reverse = _program(
        "ADD",
        [
            {"candidate_id": second.candidate_id},
            {"candidate_id": first.candidate_id},
        ],
    )
    intent = _intent(api, operation="ADD", target_period="2020")

    forward_result = _run(api, forward, [first, second], intent)
    reverse_result = _run(api, reverse, [first, second], intent)

    assert forward_result.value == reverse_result.value == Decimal("30")
    assert set(forward_result.candidate_ids) == set(
        reverse_result.candidate_ids
    )
