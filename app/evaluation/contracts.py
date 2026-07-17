from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EvaluationLayer = Literal["retrieval", "answer", "agent", "security"]
FailureStage = Literal[
    "parse",
    "chunking",
    "metadata",
    "retrieval",
    "ranking",
    "dedup_diversity",
    "acl",
    "query_analysis",
    "decomposition_rewrite",
    "evidence_assessment",
    "conflict_resolution",
    "generation",
    "citation_verification",
    "evaluation_label",
    "system_runtime",
]
MetricScalar: TypeAlias = int | float | bool | None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConfidenceInterval(StrictModel):
    low: float = Field(ge=0.0, le=1.0)
    high: float = Field(ge=0.0, le=1.0)
    level: float = Field(default=0.95, gt=0.0, lt=1.0)
    method: Literal["percentile_bootstrap"] = "percentile_bootstrap"
    iterations: int = Field(ge=1)
    seed: int

    @model_validator(mode="after")
    def validate_bounds(self) -> ConfidenceInterval:
        if self.low > self.high:
            raise ValueError("confidence interval low must not exceed high")
        return self


class RateMetric(StrictModel):
    passed: int = Field(ge=0)
    total: int = Field(ge=0)
    rate: float | None = Field(default=None, ge=0.0, le=1.0)
    ci: ConfidenceInterval | None = None

    @model_validator(mode="after")
    def validate_fraction(self) -> RateMetric:
        if self.passed > self.total:
            raise ValueError("passed must not exceed total")
        if self.total == 0:
            if self.rate is not None:
                raise ValueError("rate must be None when total is zero")
            if self.ci is not None:
                raise ValueError("ci must be None when total is zero")
            return self
        expected = self.passed / self.total
        if self.rate is None or abs(self.rate - expected) > 1e-12:
            raise ValueError("rate must equal passed / total")
        return self


class FailureSignal(StrictModel):
    stage: FailureStage
    code: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=500)


class LayerResult(StrictModel):
    layer: EvaluationLayer
    applicable: bool
    passed: bool
    metrics: dict[str, MetricScalar] = Field(default_factory=dict)
    failures: list[FailureSignal] = Field(default_factory=list)

    @field_validator("failures")
    @classmethod
    def validate_unique_failures(
        cls, values: list[FailureSignal]
    ) -> list[FailureSignal]:
        keys = [(value.stage, value.code) for value in values]
        if len(keys) != len(set(keys)):
            raise ValueError("layer failure signals must be unique")
        return values

    @model_validator(mode="after")
    def validate_state(self) -> LayerResult:
        if not self.applicable and self.failures:
            raise ValueError("not-applicable layer cannot contain failures")
        if self.passed and self.failures:
            raise ValueError("passed layer cannot contain failures")
        if self.applicable and not self.passed and not self.failures:
            raise ValueError("failed applicable layer requires a failure signal")
        if not self.applicable and not self.passed:
            raise ValueError("not-applicable layer must be marked passed")
        return self


class EvaluationCaseResult(StrictModel):
    case_id: str = Field(min_length=1, max_length=200)
    task_type: str = Field(min_length=1, max_length=100)
    expected_mode: str = Field(min_length=1, max_length=100)
    actual_mode: str = Field(min_length=1, max_length=100)
    passed: bool
    visible_doc_ids: list[str] = Field(default_factory=list)
    layers: list[LayerResult] = Field(min_length=1, max_length=4)
    primary_failure: FailureStage | None = None
    secondary_failures: list[FailureStage] = Field(default_factory=list)
    latency_ms: float = Field(ge=0.0)
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    context_chars: int = Field(ge=0)

    @field_validator("visible_doc_ids")
    @classmethod
    def validate_unique_visible_docs(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("visible document IDs must be unique")
        return values

    @field_validator("secondary_failures")
    @classmethod
    def validate_unique_secondary(
        cls, values: list[FailureStage]
    ) -> list[FailureStage]:
        if len(values) != len(set(values)):
            raise ValueError("secondary failure stages must be unique")
        return values

    @model_validator(mode="after")
    def validate_layers_and_pass(self) -> EvaluationCaseResult:
        names = [layer.layer for layer in self.layers]
        if len(names) != len(set(names)):
            raise ValueError("case layer results must be unique")
        expected_pass = all(layer.passed for layer in self.layers if layer.applicable)
        if self.passed != expected_pass:
            raise ValueError("case passed must match all applicable layers")
        if self.primary_failure is not None and self.primary_failure in self.secondary_failures:
            raise ValueError("primary failure cannot also be secondary")
        return self


class EvaluationRunResult(StrictModel):
    schema_version: Literal["enterprise_evaluation_result_v1"] = (
        "enterprise_evaluation_result_v1"
    )
    producer: Literal["enterprise_agentic_rag_v2"] = "enterprise_agentic_rag_v2"
    run_id: str = Field(min_length=1, max_length=200)
    suite: Literal[
        "retrieval",
        "answer",
        "agent",
        "security",
        "all",
        "ablation",
        "human_review",
    ]
    split: Literal["dev", "test", "regression"]
    mode: Literal["deterministic", "live"]
    case_count: int = Field(ge=0)
    summary: dict[str, Any] = Field(default_factory=dict)
    metrics_by_category: list[dict[str, Any]] = Field(default_factory=list)
    details: list[EvaluationCaseResult] = Field(default_factory=list)
    security_probes: list[dict[str, Any]] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_case_count(self) -> EvaluationRunResult:
        if self.case_count != len(self.details):
            raise ValueError("case_count must match details")
        return self


class AblationRow(StrictModel):
    variant: str = Field(min_length=1, max_length=200)
    family: Literal["retrieval", "workflow"]
    status: Literal["completed", "not_run", "failed"]
    reason: str | None = Field(default=None, max_length=500)
    case_count: int = Field(ge=0)
    metrics: dict[str, MetricScalar] = Field(default_factory=dict)
    latency_ms_avg: float | None = Field(default=None, ge=0.0)
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    context_chars: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_status(self) -> AblationRow:
        if self.status == "not_run":
            if not self.reason:
                raise ValueError("not_run row requires reason")
            if self.metrics:
                raise ValueError("not_run row cannot contain fake metrics")
        if self.status == "completed" and self.reason is not None:
            raise ValueError("completed row cannot contain failure reason")
        return self


__all__ = [
    "AblationRow",
    "ConfidenceInterval",
    "EvaluationCaseResult",
    "EvaluationLayer",
    "EvaluationRunResult",
    "FailureSignal",
    "FailureStage",
    "LayerResult",
    "MetricScalar",
    "RateMetric",
]
