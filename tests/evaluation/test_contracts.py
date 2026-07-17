from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.evaluation.contracts import (
    AblationRow,
    ConfidenceInterval,
    EvaluationCaseResult,
    FailureSignal,
    LayerResult,
    RateMetric,
)


def test_rate_metric_preserves_numerator_denominator_and_ci_method() -> None:
    metric = RateMetric(
        passed=2,
        total=3,
        rate=2 / 3,
        ci=ConfidenceInterval(
            low=0.1,
            high=1.0,
            level=0.95,
            method="percentile_bootstrap",
            iterations=2000,
            seed=20260716,
        ),
    )

    assert metric.passed == 2
    assert metric.total == 3
    assert metric.ci is not None
    assert metric.ci.method == "percentile_bootstrap"


def test_rate_metric_requires_none_rate_and_ci_when_denominator_is_zero() -> None:
    metric = RateMetric(passed=0, total=0, rate=None)

    assert metric.rate is None
    assert metric.ci is None
    with pytest.raises(ValidationError, match="rate must be None"):
        RateMetric(passed=0, total=0, rate=0.0)


def test_rate_metric_rejects_inconsistent_fraction() -> None:
    with pytest.raises(ValidationError, match="passed / total"):
        RateMetric(passed=1, total=2, rate=0.75)


def test_layer_result_requires_failure_signal_when_applicable_check_fails() -> None:
    with pytest.raises(ValidationError, match="failed applicable layer"):
        LayerResult(
            layer="retrieval",
            applicable=True,
            passed=False,
            metrics={},
            failures=[],
        )

    signal = FailureSignal(
        stage="retrieval",
        code="gold_document_missing",
        message="No gold document was visible in the evaluated cutoff.",
    )
    result = LayerResult(
        layer="retrieval",
        applicable=True,
        passed=False,
        metrics={"hit@5": 0.0},
        failures=[signal],
    )
    assert result.failures == [signal]


def test_layer_result_rejects_failures_for_passed_or_not_applicable_layer() -> None:
    signal = FailureSignal(
        stage="acl",
        code="unauthorized_exposure",
        message="An unauthorized result was exposed.",
    )
    with pytest.raises(ValidationError, match="passed layer"):
        LayerResult(
            layer="security",
            applicable=True,
            passed=True,
            metrics={},
            failures=[signal],
        )
    with pytest.raises(ValidationError, match="not-applicable layer"):
        LayerResult(
            layer="retrieval",
            applicable=False,
            passed=True,
            metrics={},
            failures=[signal],
        )


def test_case_result_rejects_duplicate_visible_docs_and_forbidden_output_fields() -> None:
    layer = LayerResult(
        layer="retrieval",
        applicable=True,
        passed=True,
        metrics={"hit@5": 1.0},
    )
    with pytest.raises(ValidationError, match="visible document IDs"):
        EvaluationCaseResult(
            case_id="case-1",
            task_type="fact_lookup",
            expected_mode="answered",
            actual_mode="answered",
            passed=True,
            visible_doc_ids=["doc-a", "doc-a"],
            layers=[layer],
            latency_ms=1.0,
            model_calls=0,
            tool_calls=1,
            context_chars=50,
        )

    with pytest.raises(ValidationError, match="Extra inputs"):
        EvaluationCaseResult.model_validate(
            {
                "case_id": "case-1",
                "task_type": "fact_lookup",
                "expected_mode": "answered",
                "actual_mode": "answered",
                "passed": True,
                "visible_doc_ids": ["doc-a"],
                "layers": [layer.model_dump()],
                "latency_ms": 1.0,
                "model_calls": 0,
                "tool_calls": 1,
                "context_chars": 50,
                "forbidden_doc_ids": ["must-never-be-persisted"],
            }
        )


def test_ablation_not_run_row_requires_reason_and_no_fake_metrics() -> None:
    row = AblationRow(
        variant="hybrid_optional_reranker",
        family="retrieval",
        status="not_run",
        reason="no_admitted_reranker",
        case_count=0,
        metrics={},
        latency_ms_avg=None,
        model_calls=0,
        tool_calls=0,
        context_chars=0,
    )
    assert row.status == "not_run"

    with pytest.raises(ValidationError, match="not_run row requires reason"):
        AblationRow(
            variant="hybrid_optional_reranker",
            family="retrieval",
            status="not_run",
            case_count=0,
            metrics={},
            model_calls=0,
            tool_calls=0,
            context_chars=0,
        )
