from __future__ import annotations

import ast
import hashlib
import inspect
from decimal import Decimal

import pytest

from app.external_datasets import finqa_typed_program
from app.external_datasets.finqa_typed_program import (
    FinancialQuestionIntent,
    NumericCandidate,
    ProvenanceSpan,
    TypedProgramValidationError,
    compile_and_execute_typed_program,
    validate_typed_program,
)


def _candidate(
    seed: str,
    value: str,
    *,
    metric: str | None = "revenue",
    entity: str | None = "company",
    period: str | None = "2020",
    fiscal_year: int | None = 2020,
    unit: str = "usd",
    scale: str = "one",
    role: str = "operand",
    evidence_id: str = "table-1",
) -> NumericCandidate:
    raw_text = value
    source_id = f"report-{seed}.pdf"
    provenance_span = ProvenanceSpan(
        start=0,
        end=len(raw_text),
        text_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )
    sign = -1 if Decimal(value) < 0 else (1 if Decimal(value) > 0 else 0)
    candidate_id = finqa_typed_program._candidate_identity(
        source_id=source_id,
        evidence_id=evidence_id,
        source_kind="table_cell",
        table_id="table-main",
        row_header=metric,
        column_header=period,
        provenance_span=provenance_span,
        normalized_value=Decimal(value),
        unit=unit,
        scale=scale,
        sign=sign,
        role=role,
    )
    return NumericCandidate(
        candidate_id=candidate_id,
        raw_text=raw_text,
        normalized_value=Decimal(value),
        metric=metric,
        entity=entity,
        period=period,
        fiscal_year=fiscal_year,
        unit=unit,
        scale=scale,
        sign=sign,
        source_id=source_id,
        evidence_id=evidence_id,
        source_kind="table_cell",
        table_id="table-main",
        row_header=metric,
        column_header=period,
        provenance_span=provenance_span,
        role=role,
    )


def _intent(
    operation: str,
    *,
    metric: str | None = "revenue",
    target_period: str | None = "2020",
    start_period: str | None = None,
    end_period: str | None = None,
    requested_unit: str = "usd",
    direction: str = "none",
) -> FinancialQuestionIntent:
    return FinancialQuestionIntent(
        operation_intent=operation,
        metric=metric,
        entity="company",
        target_period=target_period,
        start_period=start_period,
        end_period=end_period,
        requested_unit=requested_unit,
        requested_scale="one",
        direction=direction,
    )


def _program(operation: str, arguments: list[object]) -> dict:
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


def _run(
    payload: object,
    candidates: list[NumericCandidate],
    intent: FinancialQuestionIntent,
    *,
    admitted: set[str] | None = None,
):
    return compile_and_execute_typed_program(
        planner_payload=payload,
        candidates=candidates,
        admitted_evidence_ids=(
            admitted
            if admitted is not None
            else {candidate.evidence_id for candidate in candidates}
        ),
        intent=intent,
    )


@pytest.mark.parametrize(
    "forbidden_argument",
    [
        {"literal": "100"},
        {"value": "100"},
        100,
        "100",
    ],
)
def test_all_literal_operand_shapes_fail_closed(
    forbidden_argument: object,
) -> None:
    candidate = _candidate("literal", "120")

    with pytest.raises(TypedProgramValidationError) as error:
        _run(
            _program(
                "DIV",
                [
                    {"candidate_id": candidate.candidate_id},
                    forbidden_argument,
                ],
            ),
            [candidate],
            _intent("DIV", requested_unit="ratio"),
        )

    assert error.value.reason == "literal_only_operand"


def test_unknown_operation_and_extra_fields_are_rejected() -> None:
    first = _candidate("schema-a", "120")
    second = _candidate("schema-b", "100")
    arguments = [
        {"candidate_id": first.candidate_id},
        {"candidate_id": second.candidate_id},
    ]

    with pytest.raises(TypedProgramValidationError) as unsupported:
        _run(
            _program("POW", arguments),
            [first, second],
            _intent("ADD"),
        )
    assert unsupported.value.reason == "unsupported_operation"

    payload = _program("ADD", arguments)
    payload["steps"][0]["comment"] = "not admitted"
    with pytest.raises(TypedProgramValidationError) as schema:
        _run(payload, [first, second], _intent("ADD"))
    assert schema.value.reason == "invalid_program_schema"


def test_missing_and_duplicate_candidates_are_rejected() -> None:
    candidate = _candidate("candidate-a", "120")
    unknown_id = "num-" + "f" * 20

    with pytest.raises(TypedProgramValidationError) as missing:
        _run(
            _program(
                "ADD",
                [
                    {"candidate_id": candidate.candidate_id},
                    {"candidate_id": unknown_id},
                ],
            ),
            [candidate],
            _intent("ADD"),
        )
    assert missing.value.reason == "missing_candidate"

    with pytest.raises(TypedProgramValidationError) as duplicate:
        _run(
            _program(
                "ADD",
                [
                    {"candidate_id": candidate.candidate_id},
                    {"candidate_id": candidate.candidate_id},
                ],
            ),
            [candidate, candidate],
            _intent("ADD"),
        )
    assert duplicate.value.reason == "duplicate_candidate"

    alias = candidate.model_copy(
        update={"candidate_id": "num-" + "e" * 20}
    )
    with pytest.raises(TypedProgramValidationError) as semantic_duplicate:
        _run(
            _program(
                "ADD",
                [
                    {"candidate_id": candidate.candidate_id},
                    {"candidate_id": alias.candidate_id},
                ],
            ),
            [candidate, alias],
            _intent("ADD"),
        )
    assert semantic_duplicate.value.reason == "duplicate_candidate"

    with pytest.raises(TypedProgramValidationError) as identity_mismatch:
        _run(
            _program(
                "ADD",
                [
                    {"candidate_id": alias.candidate_id},
                    {"candidate_id": alias.candidate_id},
                ],
            ),
            [alias],
            _intent("ADD"),
        )
    assert identity_mismatch.value.reason == "missing_provenance"


def test_provenance_and_sign_tampering_are_rejected_before_execution() -> None:
    candidate = _candidate("provenance", "120")
    bad_provenance = candidate.model_copy(
        update={
            "provenance_span": ProvenanceSpan(
                start=0,
                end=3,
                text_sha256="0" * 64,
            )
        }
    )
    payload = _program(
        "ADD",
        [
            {"candidate_id": candidate.candidate_id},
            {"candidate_id": candidate.candidate_id},
        ],
    )

    with pytest.raises(TypedProgramValidationError) as provenance:
        _run(payload, [bad_provenance], _intent("ADD"))
    assert provenance.value.reason == "missing_provenance"

    bad_sign = candidate.model_copy(update={"sign": -1})
    with pytest.raises(TypedProgramValidationError) as sign:
        _run(payload, [bad_sign], _intent("ADD"))
    assert sign.value.reason == "sign_mismatch"

    bad_value = candidate.model_copy(
        update={"normalized_value": Decimal("121")}
    )
    with pytest.raises(TypedProgramValidationError) as value:
        _run(payload, [bad_value], _intent("ADD"))
    assert value.value.reason == "missing_provenance"


def test_non_operand_unknown_period_and_unknown_metric_fail_closed() -> None:
    period_label = _candidate("period-role", "2020", role="period_label")
    payload = _program(
        "ADD",
        [
            {"candidate_id": period_label.candidate_id},
            {"candidate_id": period_label.candidate_id},
        ],
    )
    with pytest.raises(TypedProgramValidationError) as role:
        _run(payload, [period_label], _intent("ADD"))
    assert role.value.reason == "invalid_candidate_role"

    no_period = _candidate(
        "no-period",
        "120",
        period=None,
        fiscal_year=None,
    )
    payload = _program(
        "ADD",
        [
            {"candidate_id": no_period.candidate_id},
            {"candidate_id": no_period.candidate_id},
        ],
    )
    with pytest.raises(TypedProgramValidationError) as period:
        _run(payload, [no_period], _intent("ADD"))
    assert period.value.reason == "ambiguous_intent"

    no_metric = _candidate("no-metric", "120", metric=None)
    payload = _program(
        "ADD",
        [
            {"candidate_id": no_metric.candidate_id},
            {"candidate_id": no_metric.candidate_id},
        ],
    )
    with pytest.raises(TypedProgramValidationError) as metric:
        _run(payload, [no_metric], _intent("ADD"))
    assert metric.value.reason == "ambiguous_intent"


def test_unit_and_scale_incompatibility_fail_closed() -> None:
    usd = _candidate("usd", "120")
    count = _candidate("count", "100", metric="revenue", unit="count")
    payload = _program(
        "ADD",
        [
            {"candidate_id": usd.candidate_id},
            {"candidate_id": count.candidate_id},
        ],
    )
    with pytest.raises(TypedProgramValidationError) as unit:
        _run(payload, [usd, count], _intent("ADD"))
    assert unit.value.reason == "unit_mismatch"

    unknown_scale = _candidate("scale", "120", scale="unknown")
    payload = _program(
        "ADD",
        [
            {"candidate_id": unknown_scale.candidate_id},
            {"candidate_id": unknown_scale.candidate_id},
        ],
    )
    with pytest.raises(TypedProgramValidationError) as scale:
        _run(payload, [unknown_scale], _intent("ADD"))
    assert scale.value.reason == "scale_mismatch"


def test_unicode_metric_mismatch_is_not_treated_as_unknown() -> None:
    revenue = _candidate("zh-revenue", "120", metric="收入")
    profit = _candidate("zh-profit", "100", metric="利润")
    payload = _program(
        "ADD",
        [
            {"candidate_id": revenue.candidate_id},
            {"candidate_id": profit.candidate_id},
        ],
    )
    intent = _intent("ADD", metric="收入")

    with pytest.raises(TypedProgramValidationError) as error:
        _run(payload, [revenue, profit], intent)

    assert error.value.reason == "metric_mismatch"


def test_forward_duplicate_and_missing_output_steps_are_rejected() -> None:
    first = _candidate("step-a", "120")
    second = _candidate("step-b", "100")

    forward = {
        "dsl_version": "finqa_typed_financial_dsl_v1",
        "steps": [
            {
                "step_id": "step-01",
                "operation": "ADD",
                "arguments": [
                    {"step_id": "step-02"},
                    {"candidate_id": first.candidate_id},
                ],
            },
            {
                "step_id": "step-02",
                "operation": "ADD",
                "arguments": [
                    {"candidate_id": first.candidate_id},
                    {"candidate_id": second.candidate_id},
                ],
            },
        ],
        "output_step_id": "step-02",
    }
    with pytest.raises(TypedProgramValidationError) as forward_error:
        _run(forward, [first, second], _intent("ADD"))
    assert forward_error.value.reason == "forward_step_reference"

    duplicate_step = {
        "step_id": "step-01",
        "operation": "ADD",
        "arguments": [
            {"candidate_id": first.candidate_id},
            {"candidate_id": second.candidate_id},
        ],
    }
    duplicate = {
        "dsl_version": "finqa_typed_financial_dsl_v1",
        "steps": [duplicate_step, duplicate_step],
        "output_step_id": "step-01",
    }
    with pytest.raises(TypedProgramValidationError) as duplicate_error:
        _run(duplicate, [first, second], _intent("ADD"))
    assert duplicate_error.value.reason == "duplicate_step_id"

    valid_step = {
        "step_id": "step-01",
        "operation": "ADD",
        "arguments": [
            {"candidate_id": first.candidate_id},
            {"candidate_id": second.candidate_id},
        ],
    }
    missing_output = {
        "dsl_version": "finqa_typed_financial_dsl_v1",
        "steps": [valid_step],
    }
    with pytest.raises(TypedProgramValidationError) as output_error:
        _run(missing_output, [first, second], _intent("ADD"))
    assert output_error.value.reason == "missing_output_step"


def test_arity_payload_and_magnitude_budgets_are_enforced() -> None:
    candidate = _candidate("budget", "120")
    with pytest.raises(TypedProgramValidationError) as arity:
        _run(
            _program(
                "ADD",
                [{"candidate_id": candidate.candidate_id}],
            ),
            [candidate],
            _intent("ADD"),
        )
    assert arity.value.reason == "invalid_arity"

    oversized = _program(
        "ADD",
        [
            {"candidate_id": candidate.candidate_id},
            {"candidate_id": candidate.candidate_id},
        ],
    )
    oversized["padding"] = "x" * 17_000
    with pytest.raises(TypedProgramValidationError) as payload:
        _run(oversized, [candidate], _intent("ADD"))
    assert payload.value.reason == "budget_exceeded"

    large = _candidate(
        "large",
        "100000000000000000000",
        unit="usd",
    )
    ratio = _candidate(
        "large-ratio",
        "100000000000000000000",
        metric=None,
        entity=None,
        unit="ratio",
    )
    with pytest.raises(TypedProgramValidationError) as magnitude:
        _run(
            _program(
                "MUL",
                [
                    {"candidate_id": large.candidate_id},
                    {"candidate_id": ratio.candidate_id},
                ],
            ),
            [large, ratio],
            _intent("MUL", metric=None),
        )
    assert magnitude.value.reason == "budget_exceeded"


@pytest.mark.parametrize(
    ("operation", "expected", "expected_unit"),
    [
        ("ADD", "220", "usd"),
        ("SUB", "20", "usd"),
        ("DIV", "1.2", "ratio"),
        ("RATIO", "1.2", "ratio"),
        ("AVERAGE", "110", "usd"),
    ],
)
def test_compiler_matches_independent_decimal_reference(
    operation: str,
    expected: str,
    expected_unit: str,
) -> None:
    first = _candidate(f"{operation}-a", "120")
    second = _candidate(f"{operation}-b", "100")
    result = _run(
        _program(
            operation,
            [
                {"candidate_id": first.candidate_id},
                {"candidate_id": second.candidate_id},
            ],
        ),
        [first, second],
        _intent(operation, requested_unit=expected_unit),
    )

    assert result.value == Decimal(expected)
    assert result.unit == expected_unit


def test_percent_change_and_multiplication_preserve_units() -> None:
    new = _candidate("percent-new", "120", period="2020", fiscal_year=2020)
    old = _candidate("percent-old", "100", period="2019", fiscal_year=2019)
    percent = _run(
        _program(
            "PERCENT_CHANGE",
            [
                {"candidate_id": new.candidate_id},
                {"candidate_id": old.candidate_id},
            ],
        ),
        [new, old],
        _intent(
            "PERCENT_CHANGE",
            target_period=None,
            start_period="2019",
            end_period="2020",
            requested_unit="ratio",
            direction="new_over_old",
        ),
    )
    assert percent.value == Decimal("0.2")
    assert percent.unit == "ratio"

    ratio = _candidate(
        "multiplier",
        "0.5",
        metric=None,
        entity=None,
        unit="ratio",
    )
    amount = _candidate("amount", "120")
    multiplied = _run(
        _program(
            "MUL",
            [
                {"candidate_id": amount.candidate_id},
                {"candidate_id": ratio.candidate_id},
            ],
        ),
        [amount, ratio],
        _intent("MUL", metric=None),
    )
    assert multiplied.value == Decimal("60")
    assert multiplied.unit == "usd"


def test_multi_step_value_ratio_then_add_preserves_metadata() -> None:
    amount = _candidate("multi-amount", "100")
    ratio = _candidate("multi-ratio", "0.5", unit="ratio")
    remainder = _candidate("multi-remainder", "25")
    payload = {
        "dsl_version": "finqa_typed_financial_dsl_v1",
        "steps": [
            {
                "step_id": "step-01",
                "operation": "MUL",
                "arguments": [
                    {"candidate_id": amount.candidate_id},
                    {"candidate_id": ratio.candidate_id},
                ],
            },
            {
                "step_id": "step-02",
                "operation": "ADD",
                "arguments": [
                    {"step_id": "step-01"},
                    {"candidate_id": remainder.candidate_id},
                ],
            },
        ],
        "output_step_id": "step-02",
    }

    result = _run(
        payload,
        [amount, ratio, remainder],
        _intent("ADD"),
    )

    assert result.value == Decimal("75")
    assert result.unit == "usd"
    assert result.step_values == {
        "step-01": Decimal("50.0"),
        "step-02": Decimal("75.0"),
    }
    assert result.candidate_ids == (
        amount.candidate_id,
        ratio.candidate_id,
        remainder.candidate_id,
    )


def test_validation_and_result_hashes_are_stable_and_close_provenance() -> None:
    first = _candidate("hash-a", "120", evidence_id="table-a")
    second = _candidate("hash-b", "100", evidence_id="table-b")
    payload = _program(
        "ADD",
        [
            {"candidate_id": first.candidate_id},
            {"candidate_id": second.candidate_id},
        ],
    )
    intent = _intent("ADD")
    admitted = {"table-a", "table-b"}

    validated_first = validate_typed_program(
        planner_payload=payload,
        candidates=[first, second],
        admitted_evidence_ids=admitted,
        intent=intent,
    )
    validated_second = validate_typed_program(
        planner_payload=payload,
        candidates=[first, second],
        admitted_evidence_ids=admitted,
        intent=intent,
    )
    result_first = _run(payload, [first, second], intent, admitted=admitted)
    result_second = _run(payload, [first, second], intent, admitted=admitted)

    assert validated_first.validation_sha256 == (
        validated_second.validation_sha256
    )
    assert result_first.program_sha256 == result_second.program_sha256
    assert result_first.candidate_ids == (
        first.candidate_id,
        second.candidate_id,
    )
    assert result_first.evidence_ids == ("table-a", "table-b")
    assert result_first.step_values == {"step-01": Decimal("220")}
    assert result_first.diagnostics.validation_sha256 == (
        validated_first.validation_sha256
    )
    assert result_first.diagnostics.step_count == 1
    assert result_first.diagnostics.candidate_count == 2
    with pytest.raises(TypeError):
        result_first.step_values["step-01"] = Decimal("999")  # type: ignore[index]


def test_generated_programs_match_independent_decimal_calculations() -> None:
    pairs = [
        ("1.25", "0.5"),
        ("120", "100"),
        ("-12.5", "2.5"),
        ("999999.99", "3"),
    ]
    operations = {
        "ADD": lambda left, right: left + right,
        "SUB": lambda left, right: left - right,
        "DIV": lambda left, right: left / right,
        "AVERAGE": lambda left, right: (left + right) / Decimal("2"),
    }
    for pair_index, (left_text, right_text) in enumerate(pairs):
        left = _candidate(f"generated-{pair_index}-a", left_text)
        right = _candidate(f"generated-{pair_index}-b", right_text)
        for operation, reference in operations.items():
            requested_unit = "ratio" if operation == "DIV" else "usd"
            result = _run(
                _program(
                    operation,
                    [
                        {"candidate_id": left.candidate_id},
                        {"candidate_id": right.candidate_id},
                    ],
                ),
                [left, right],
                _intent(operation, requested_unit=requested_unit),
            )
            assert result.value == reference(
                Decimal(left_text),
                Decimal(right_text),
            )


def test_compiler_source_contains_no_eval_or_exec_calls() -> None:
    tree = ast.parse(inspect.getsource(finqa_typed_program))
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert called_names.isdisjoint({"eval", "exec"})
