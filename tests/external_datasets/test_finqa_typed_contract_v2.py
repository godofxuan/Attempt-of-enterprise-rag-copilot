from __future__ import annotations

import hashlib
import json
from decimal import Decimal

import pytest

from app.external_datasets import finqa_typed_program
from app.external_datasets.finqa_typed_contract_v2 import (
    FinancialQuestionIntentV2,
    allowed_outputs_for_family,
    compile_and_execute_typed_program_v2,
)
from app.external_datasets.finqa_typed_planner import (
    extract_financial_question_intent,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    LocalFinQATypedProgramPlannerV2,
    compile_typed_program_sketch_v2,
    extract_financial_question_intent_v2,
    parse_typed_program_sketch_v2,
    question_conditioned_candidate_shortlist_v2,
    typed_program_sketch_response_format_v2,
)
from app.external_datasets.finqa_typed_program import (
    NumericCandidate,
    ProvenanceSpan,
    TypedProgramValidationError,
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
    evidence_id: str | None = None,
) -> NumericCandidate:
    raw_text = value
    source_id = f"report-{seed}.pdf"
    evidence_id = evidence_id or f"table-{seed}"
    provenance = ProvenanceSpan(
        start=0,
        end=len(raw_text),
        text_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )
    decimal = Decimal(value)
    sign = -1 if decimal < 0 else (1 if decimal > 0 else 0)
    candidate_id = finqa_typed_program._candidate_identity(
        source_id=source_id,
        evidence_id=evidence_id,
        source_kind="table_cell",
        table_id="table-main",
        row_header=metric,
        column_header=period,
        provenance_span=provenance,
        normalized_value=decimal,
        unit=unit,
        scale="one",
        sign=sign,
        role="operand",
    )
    return NumericCandidate(
        candidate_id=candidate_id,
        raw_text=raw_text,
        normalized_value=decimal,
        metric=metric,
        entity=entity,
        period=period,
        fiscal_year=fiscal_year,
        unit=unit,
        scale="one",
        sign=sign,
        source_id=source_id,
        evidence_id=evidence_id,
        source_kind="table_cell",
        table_id="table-main",
        row_header=metric,
        column_header=period,
        provenance_span=provenance,
        role="operand",
    )


def _intent(
    family: str,
    *,
    target_period: str | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
    requested_unit: str = "unknown",
    requested_scale: str = "one",
    direction: str = "none",
    metric: str | None = None,
    entity: str | None = None,
    allow_composition: bool = False,
) -> FinancialQuestionIntentV2:
    return FinancialQuestionIntentV2(
        operation_family=family,
        allowed_output_operations=allowed_outputs_for_family(family),
        metric=metric,
        entity=entity,
        target_period=target_period,
        start_period=start_period,
        end_period=end_period,
        requested_unit=requested_unit,
        requested_scale=requested_scale,
        direction=direction,
        allow_additive_metric_composition=allow_composition,
    )


def _single_step(
    operation: str,
    candidates: list[NumericCandidate],
) -> dict:
    return {
        "dsl_version": "finqa_typed_financial_dsl_v1",
        "steps": [
            {
                "step_id": "step-01",
                "operation": operation,
                "arguments": [
                    {"candidate_id": item.candidate_id}
                    for item in candidates
                ],
            }
        ],
        "output_step_id": "step-01",
    }


def _run(payload, candidates, intent):
    return compile_and_execute_typed_program_v2(
        planner_payload=payload,
        candidates=candidates,
        admitted_evidence_ids={
            candidate.evidence_id for candidate in candidates
        },
        intent=intent,
    )


def test_v2_represents_unspecified_intent_without_rejecting_pre_model() -> None:
    question = "What amount was reported for the financing activity?"

    with pytest.raises(TypedProgramValidationError) as v1_error:
        extract_financial_question_intent(question)
    v2_intent = extract_financial_question_intent_v2(question)

    assert v1_error.value.reason == "ambiguous_intent"
    assert v2_intent.operation_family == "unspecified"
    assert set(v2_intent.allowed_output_operations) == {
        "ADD",
        "SUB",
        "MUL",
        "DIV",
        "PERCENT_CHANGE",
        "RATIO",
        "AVERAGE",
    }


def test_percent_change_no_longer_requires_two_question_years() -> None:
    intent = extract_financial_question_intent_v2(
        "What was the growth rate in net revenue in 2007?"
    )

    assert intent.operation_family == "percent_change"
    assert intent.target_period is None
    assert intent.start_period is None
    assert intent.direction == "none"


def test_metric_words_do_not_override_change_or_total_return_semantics() -> None:
    weighted_average_change = extract_financial_question_intent_v2(
        "What was the change in weighted average shares from 2020 to 2021?"
    )
    total_return = extract_financial_question_intent_v2(
        "What was the total return from 2019 to 2020?"
    )

    assert weighted_average_change.operation_family == "unspecified"
    assert total_return.operation_family == "percent_change"


def test_question_conditioned_shortlist_is_bounded_and_period_aware() -> None:
    relevant = _candidate(
        "relevant",
        "120",
        metric="current assets",
        evidence_id="table-relevant",
    )
    period_conflict = _candidate(
        "conflict",
        "999",
        metric="current assets",
        period="2019",
        fiscal_year=2019,
        evidence_id="table-conflict",
    )
    noise = [
        _candidate(
            f"noise-{index}",
            str(index + 1),
            metric=f"unrelated metric {index}",
            period=None,
            fiscal_year=None,
            evidence_id=f"table-noise-{index}",
        )
        for index in range(30)
    ]
    candidates = [*noise, period_conflict, relevant]
    intent = _intent("exact_add", target_period="2020")

    shortlisted = question_conditioned_candidate_shortlist_v2(
        question="What were total current assets in 2020?",
        candidates=candidates,
        admitted_evidence_ids={
            candidate.evidence_id for candidate in candidates
        },
        intent=intent,
        evidence_context_by_id={
            relevant.evidence_id: "Current assets in 2020",
            **{
                candidate.evidence_id: "Unrelated disclosure"
                for candidate in noise
            },
            period_conflict.evidence_id: "Current assets in 2019",
        },
    )

    assert len(shortlisted) == 24
    assert shortlisted[0].candidate_id == relevant.candidate_id
    assert period_conflict.candidate_id not in {
        candidate.candidate_id for candidate in shortlisted
    }


def test_unknown_metadata_is_admitted_when_no_known_conflict_exists() -> None:
    known = _candidate("known", "120")
    unknown = _candidate(
        "unknown",
        "100",
        metric=None,
        entity=None,
        period=None,
        fiscal_year=None,
        unit="unknown",
    )

    result = _run(
        _single_step("SUB", [known, unknown]),
        [known, unknown],
        _intent(
            "exact_subtract",
            target_period="2020",
            requested_unit="usd",
            metric="revenue",
            entity="company",
        ),
    )

    assert result.value == Decimal("20")
    assert result.unit == "usd"


def test_known_period_and_unit_conflicts_still_fail_closed() -> None:
    current = _candidate("current", "120", period="2020", fiscal_year=2020)
    old = _candidate("old", "100", period="2019", fiscal_year=2019)
    with pytest.raises(TypedProgramValidationError) as period_error:
        _run(
            _single_step("SUB", [current, old]),
            [current, old],
            _intent(
                "exact_subtract",
                target_period="2020",
                requested_unit="usd",
            ),
        )
    assert period_error.value.reason == "temporal_mismatch"

    euros = _candidate("euros", "100", unit="eur")
    with pytest.raises(TypedProgramValidationError) as unit_error:
        _run(
            _single_step("ADD", [current, euros]),
            [current, euros],
            _intent(
                "exact_add",
                allow_composition=True,
            ),
        )
    assert unit_error.value.reason == "unit_mismatch"


def test_explicit_additive_composition_supports_multiple_metrics_and_arity() -> None:
    candidates = [
        _candidate("a", "10", metric="current debt"),
        _candidate("b", "20", metric="long-term debt"),
        _candidate("c", "30", metric="lease debt"),
    ]

    result = _run(
        _single_step("ADD", candidates),
        candidates,
        _intent(
            "exact_add",
            requested_unit="usd",
            allow_composition=True,
        ),
    )

    assert result.value == Decimal("60")
    assert result.diagnostics.step_count == 1

    with pytest.raises(TypedProgramValidationError) as strict_error:
        _run(
            _single_step("ADD", candidates),
            candidates,
            _intent(
                "exact_add",
                requested_unit="usd",
                allow_composition=False,
            ),
        )
    assert strict_error.value.reason == "metric_mismatch"


def test_percent_change_division_must_reuse_the_old_operand() -> None:
    new = _candidate("new", "120", period="2020", fiscal_year=2020)
    old = _candidate("old", "100", period="2019", fiscal_year=2019)
    unrelated = _candidate(
        "other",
        "80",
        period="2019",
        fiscal_year=2019,
    )
    valid = {
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
    intent = _intent(
        "percent_change",
        start_period="2019",
        end_period="2020",
        requested_unit="ratio",
        direction="new_over_old",
    )

    result = _run(valid, [new, old], intent)
    assert result.value == Decimal("0.2")

    invalid = json.loads(json.dumps(valid))
    invalid["steps"][1]["arguments"][1] = {
        "candidate_id": unrelated.candidate_id
    }
    with pytest.raises(TypedProgramValidationError) as error:
        _run(invalid, [new, old, unrelated], intent)
    assert error.value.reason == "direction_mismatch"


def test_basis_point_presentation_is_host_compiled() -> None:
    current = _candidate("ratio-new", "0.05", unit="ratio")
    old = _candidate("ratio-old", "0.04", unit="ratio")

    result = _run(
        _single_step("SUB", [current, old]),
        [current, old],
        _intent(
            "exact_subtract",
            requested_unit="ratio",
            requested_scale="basis_point",
        ),
    )

    assert result.canonical_value == Decimal("0.01")
    assert result.value == Decimal("1E+2")
    assert result.diagnostics.presentation_scale_applied is True


def test_v2_rejects_duplicate_unreferenced_and_overlong_programs() -> None:
    candidates = [
        _candidate(f"structure-{index}", str(index + 1))
        for index in range(7)
    ]
    duplicate_operand = _single_step(
        "ADD",
        [candidates[0], candidates[0]],
    )
    with pytest.raises(TypedProgramValidationError) as duplicate:
        _run(
            duplicate_operand,
            candidates,
            _intent("exact_add", allow_composition=True),
        )
    assert duplicate.value.reason == "invalid_program_schema"

    unreferenced = {
        "dsl_version": "finqa_typed_financial_dsl_v1",
        "steps": [
            _single_step("ADD", candidates[:2])["steps"][0],
            {
                "step_id": "step-02",
                "operation": "ADD",
                "arguments": [
                    {"candidate_id": candidates[2].candidate_id},
                    {"candidate_id": candidates[3].candidate_id},
                ],
            },
        ],
        "output_step_id": "step-02",
    }
    with pytest.raises(TypedProgramValidationError) as dead_step:
        _run(
            unreferenced,
            candidates,
            _intent("exact_add", allow_composition=True),
        )
    assert dead_step.value.reason == "invalid_program_schema"

    steps = [
        {
            "step_id": "step-01",
            "operation": "ADD",
            "arguments": [
                {"candidate_id": candidates[0].candidate_id},
                {"candidate_id": candidates[1].candidate_id},
            ],
        }
    ]
    for index in range(2, 7):
        steps.append(
            {
                "step_id": f"step-{index:02d}",
                "operation": "ADD",
                "arguments": [
                    {"step_id": f"step-{index - 1:02d}"},
                    {"candidate_id": candidates[index].candidate_id},
                ],
            }
        )
    with pytest.raises(TypedProgramValidationError) as budget:
        _run(
            {
                "dsl_version": "finqa_typed_financial_dsl_v1",
                "steps": steps,
                "output_step_id": "step-06",
            },
            candidates,
            _intent("exact_add", allow_composition=True),
        )
    assert budget.value.reason == "budget_exceeded"


@pytest.mark.parametrize(
    "forbidden",
    [{"literal": "100"}, {"value": "100"}, 100, "100"],
)
def test_v2_keeps_model_generated_numeric_literals_forbidden(
    forbidden: object,
) -> None:
    numerator = _candidate("literal", "120")
    payload = {
        "dsl_version": "finqa_typed_financial_dsl_v1",
        "steps": [
            {
                "step_id": "step-01",
                "operation": "DIV",
                "arguments": [
                    {"candidate_id": numerator.candidate_id},
                    forbidden,
                ],
            }
        ],
        "output_step_id": "step-01",
    }

    with pytest.raises(TypedProgramValidationError) as error:
        _run(
            payload,
            [numerator],
            _intent("exact_divide"),
        )
    assert error.value.reason == "literal_only_operand"


def test_v2_planner_executes_unspecified_intent_with_fake_model() -> None:
    first = _candidate("planner-a", "120")
    second = _candidate("planner-b", "100")

    def fake_chat(_model, messages, *, response_format=None, think=None):
        assert think is False
        assert response_format["type"] == "object"
        intent = json.loads(messages[1]["content"])["intent"]
        assert intent["operation_family"] == "unspecified"
        return json.dumps(
            {
                "template": "SUB",
                "operand_candidate_ids": [
                    first.candidate_id,
                    second.candidate_id,
                ],
            }
        )

    planner = LocalFinQATypedProgramPlannerV2(
        model="fake",
        chat_fn=fake_chat,
        max_attempts=1,
    )
    result = planner.plan_and_execute(
        question="What amount remained after the adjustment?",
        candidates=[first, second],
        admitted_evidence_ids={first.evidence_id, second.evidence_id},
        evidence_context_by_id={
            first.evidence_id: "current amount",
            second.evidence_id: "adjustment",
        },
    )

    assert result.execution.value == Decimal("20")
    assert result.intent.operation_family == "unspecified"
    assert result.planner_version == "finqa_typed_planner_v2_2"


def test_sketch_contract_is_reference_only_and_host_compiled() -> None:
    first = _candidate("sketch-a", "120")
    second = _candidate("sketch-b", "100")
    candidate_ids = [first.candidate_id, second.candidate_id]
    intent = _intent("exact_subtract")
    schema = typed_program_sketch_response_format_v2(
        candidate_ids=candidate_ids,
        intent=intent,
    )
    sketch = parse_typed_program_sketch_v2(
        json.dumps(
            {
                "template": "SUB",
                "operand_candidate_ids": candidate_ids,
            }
        ),
        candidate_ids=candidate_ids,
        intent=intent,
    )
    program = compile_typed_program_sketch_v2(sketch)

    assert set(schema["properties"]) == {
        "template",
        "operand_candidate_ids",
    }
    assert program == _single_step("SUB", [first, second])

    with pytest.raises(ValueError, match="schema"):
        parse_typed_program_sketch_v2(
            json.dumps(
                {
                    "template": "SUB",
                    "operand_candidate_ids": candidate_ids,
                    "literal": 100,
                }
            ),
            candidate_ids=candidate_ids,
            intent=intent,
        )
    with pytest.raises(ValueError, match="unique"):
        parse_typed_program_sketch_v2(
            json.dumps(
                {
                    "template": "SUB",
                    "operand_candidate_ids": [
                        first.candidate_id,
                        first.candidate_id,
                    ],
                }
            ),
            candidate_ids=candidate_ids,
            intent=intent,
        )
