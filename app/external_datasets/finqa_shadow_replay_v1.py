from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa import FinQACase, build_finqa_evidence_units
from app.external_datasets.finqa_descriptor_retriever_v5 import (
    RETRIEVER_VERSION,
)
from app.external_datasets.finqa_descriptor_shadow_v1 import (
    FinQADescriptorShadowRuntimeV1,
)
from app.external_datasets.finqa_learned_ranker_training_v1 import (
    finqa_company_id,
    load_strict_json_array,
    normalize_empty_table_cells_v1,
    strings_sha256,
)
from app.external_datasets.finqa_numeric_evidence_v2 import (
    NumericCandidateV2,
    admit_finqa_numeric_evidence_closure_v2,
    expand_finqa_numeric_evidence_v2,
    extract_finqa_numeric_candidates_v2,
)
from app.external_datasets.finqa_pairwise_residual_training_v1 import (
    top_retrieved_unit_ids_v1,
)
from app.external_datasets.finqa_role_compatibility_audit_v2 import (
    build_oracle_semantic_program_v2,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeDescriptorCatalogV3,
    build_retrievable_safe_descriptor_catalog_v3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)
from app.external_datasets.finqa_shadow_worker_protocol_v1 import (
    FinQAShadowWorkerReplayProtocolV1,
)
from app.external_datasets.finqa_shadow_worker_v1 import (
    FinQAIsolatedShadowWorkerV1,
)
from app.observability.metrics import nearest_rank_percentile
from app.security.retrieved_content import RetrievedContentGuard


REPLAY_SUMMARY_VERSION = "finqa_shadow_operational_replay_summary_v1"
_PROGRAM_CONSTANT = re.compile(r"const_(?:m)?[0-9]+(?:\.[0-9]+)?")
_SCALE_MULTIPLIER = {
    "one": Decimal("1"),
    "thousand": Decimal("1000"),
    "million": Decimal("1000000"),
    "billion": Decimal("1000000000"),
    "trillion": Decimal("1000000000000"),
    "percent": Decimal("0.01"),
    "basis_point": Decimal("0.0001"),
    "unknown": Decimal("1"),
}


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


@dataclass(frozen=True)
class PreparedFinQAShadowReplayCaseV1:
    question: str
    skeleton: SemanticProgramSkeletonV2
    catalog: RetrievableSafeDescriptorCatalogV3
    source_candidate_count: int
    descriptor_count: int


class FinQAShadowPreparationSummaryV1(_StrictFrozenModel):
    selected_case_count: int = Field(ge=1)
    prepared_case_count: int = Field(ge=0)
    preparation_failure_count: int = Field(ge=0)
    primary_failure_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> FinQAShadowPreparationSummaryV1:
        if self.prepared_case_count + self.preparation_failure_count != (
            self.selected_case_count
        ):
            raise ValueError("E13 preparation counts do not reconcile")
        if self.primary_failure_count > self.prepared_case_count:
            raise ValueError("E13 primary failures exceed prepared cases")
        return self


class FinQAShadowObservationSummaryV1(_StrictFrozenModel):
    attempted_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    outcome_counts: dict[str, int]
    role_count: int = Field(ge=0)
    changed_role_count: int = Field(ge=0)
    common_descriptor_count_at_4: int = Field(ge=0)
    worker_restart_count: int = Field(ge=0)
    model_call_count: Literal[0]

    @model_validator(mode="after")
    def validate_observations(self) -> FinQAShadowObservationSummaryV1:
        allowed = {
            "MATCH",
            "DIVERGED",
            "INPUT_MISMATCH",
            "PAYLOAD_REJECTED",
            "WORKER_ERROR",
            "WORKER_TIMEOUT",
            "WORKER_CRASH",
        }
        if (
            not set(self.outcome_counts).issubset(allowed)
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in self.outcome_counts.values()
            )
            or sum(self.outcome_counts.values()) != self.attempted_count
            or self.completed_count
            != self.outcome_counts.get("MATCH", 0)
            + self.outcome_counts.get("DIVERGED", 0)
        ):
            raise ValueError("E13 observation counts do not reconcile")
        return self


class FinQAAggregateDistributionV1(_StrictFrozenModel):
    count: int = Field(ge=0)
    p50: float | None = Field(default=None, ge=0)
    p95: float | None = Field(default=None, ge=0)
    maximum: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_empty_state(self) -> FinQAAggregateDistributionV1:
        values = (self.p50, self.p95, self.maximum)
        if (self.count == 0) != all(value is None for value in values):
            raise ValueError("E13 aggregate distribution is inconsistent")
        if self.count and any(value is None for value in values):
            raise ValueError("E13 aggregate distribution is incomplete")
        return self


class FinQAShadowOperationalReplaySummaryV1(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_shadow_operational_replay_summary_v1"
    ] = REPLAY_SUMMARY_VERSION
    preparation: FinQAShadowPreparationSummaryV1
    observations: FinQAShadowObservationSummaryV1
    latency_ms: FinQAAggregateDistributionV1
    worker_peak_rss_bytes: FinQAAggregateDistributionV1
    all_primary_results_e8: bool
    per_request_rows_persisted: Literal[0]
    quality_labels_consumed: Literal[0]

    @model_validator(mode="after")
    def validate_cross_group_accounting(
        self,
    ) -> FinQAShadowOperationalReplaySummaryV1:
        if self.observations.attempted_count != (
            self.preparation.prepared_case_count
            - self.preparation.primary_failure_count
        ):
            raise ValueError("E13 preparation and observation counts do not reconcile")
        if (
            self.latency_ms.count != self.observations.completed_count
            or self.worker_peak_rss_bytes.count
            != self.observations.completed_count
        ):
            raise ValueError("E13 completed observations lack resource samples")
        return self


def load_finqa_shadow_replay_train_v1(
    path: Path,
    *,
    expected_sha256: str,
) -> list[FinQACase]:
    payload = load_strict_json_array(path, expected_sha256=expected_sha256)
    cases: list[FinQACase] = []
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("qa"), dict):
            raise ValueError("E13 train row is not a FinQA object")
        projected = dict(item)
        qa = dict(item["qa"])
        # E13 exercises runtime mechanics, so quality labels are redacted before
        # they cross the typed input boundary. The placeholder is never read.
        qa.update(
            {
                "answer": "REDACTED",
                "exe_ans": 0,
                "gold_inds": {"text_0": "REDACTED"},
                "ann_table_rows": [],
                "ann_text_rows": [],
            }
        )
        projected["qa"] = qa
        cases.append(FinQACase.model_validate(projected))
    case_ids = tuple(case.id for case in cases)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("E13 train case IDs are duplicated")
    return cases


def select_shadow_replay_cases_v1(
    cases: list[FinQACase],
    *,
    protocol: FinQAShadowWorkerReplayProtocolV1,
) -> tuple[FinQACase, ...]:
    boundary = protocol.dataset
    if len(cases) != boundary.split_case_count:
        raise ValueError("E13 train case count changed")
    ranked = sorted(
        cases,
        key=lambda case: (
            hashlib.sha256(
                f"{boundary.selection_seed}\\0{case.id}".encode("ascii")
            ).hexdigest(),
            case.id,
        ),
    )
    selected = tuple(ranked[: boundary.selected_case_count])
    if (
        strings_sha256([case.id for case in selected])
        != boundary.selected_case_ids_sha256
        or len({finqa_company_id(case.filename) for case in selected})
        != boundary.selected_company_count
    ):
        raise ValueError("E13 selected train boundary changed")
    return selected


def _retrieved_source_bound_constant_ids(
    *,
    program: str,
    candidates: tuple[NumericCandidateV2, ...],
) -> frozenset[str]:
    source_bound: set[str] = set()
    for constant_id in set(_PROGRAM_CONSTANT.findall(program)):
        digits = constant_id.removeprefix("const_")
        if digits.startswith("m"):
            digits = f"-{digits[1:]}"
        target = Decimal(digits)
        for candidate in candidates:
            normalized_value = candidate.normalized_value
            scale = candidate.scale
            if (
                normalized_value == target
                or normalized_value / _SCALE_MULTIPLIER[scale] == target
            ):
                source_bound.add(constant_id)
                break
    return frozenset(source_bound)


def prepare_finqa_shadow_replay_case_v1(
    case: FinQACase,
    *,
    guard: RetrievedContentGuard,
    selected_unit_limit: int,
) -> PreparedFinQAShadowReplayCaseV1:
    selected_ids = top_retrieved_unit_ids_v1(
        case.text_retrieved_all,
        case.table_retrieved_all,
        limit=selected_unit_limit,
    )
    extraction_case, _ = normalize_empty_table_cells_v1(case)
    closure = expand_finqa_numeric_evidence_v2(
        case,
        selected_unit_ids=selected_ids,
    )
    admission = admit_finqa_numeric_evidence_closure_v2(
        case,
        closure=closure,
        guard=guard,
    )
    admitted_ids = set(admission.admitted_unit_ids)
    candidates = tuple(
        candidate
        for candidate in extract_finqa_numeric_candidates_v2(
            extraction_case,
            admitted_evidence_ids=admitted_ids,
        ).candidates
        if candidate.role == "operand"
    )
    oracle = build_oracle_semantic_program_v2(
        question=case.qa.question,
        program=case.qa.program,
        source_bound_constant_ids=_retrieved_source_bound_constant_ids(
            program=case.qa.program,
            candidates=candidates,
        ),
    )
    if oracle.skeleton is None:
        raise ValueError("E13 case did not produce a typed skeleton")
    units = {unit.unit_id: unit for unit in build_finqa_evidence_units(case)}
    catalog_build = build_retrievable_safe_descriptor_catalog_v3(
        candidates=candidates,
        admitted_evidence_ids=admitted_ids,
        evidence_context_by_id={
            unit_id: units[unit_id].text
            for unit_id in admission.admitted_unit_ids
        },
        guard=guard,
    )
    return PreparedFinQAShadowReplayCaseV1(
        question=case.qa.question,
        skeleton=oracle.skeleton,
        catalog=catalog_build.catalog,
        source_candidate_count=len(candidates),
        descriptor_count=catalog_build.catalog.descriptor_count,
    )


def _distribution(values: list[float]) -> FinQAAggregateDistributionV1:
    if not values:
        return FinQAAggregateDistributionV1(count=0)
    return FinQAAggregateDistributionV1(
        count=len(values),
        p50=nearest_rank_percentile(values, 0.5),
        p95=nearest_rank_percentile(values, 0.95),
        maximum=max(values),
    )


def run_finqa_shadow_operational_replay_v1(
    cases: list[FinQACase],
    *,
    protocol: FinQAShadowWorkerReplayProtocolV1,
    worker: FinQAIsolatedShadowWorkerV1,
    guard: RetrievedContentGuard | None = None,
) -> FinQAShadowOperationalReplaySummaryV1:
    selected = select_shadow_replay_cases_v1(cases, protocol=protocol)
    content_guard = guard or RetrievedContentGuard()
    primary_runtime = FinQADescriptorShadowRuntimeV1()
    preparation_failures = 0
    primary_failures = 0
    prepared_count = 0
    attempted_count = 0
    completed_count = 0
    outcomes: Counter[str] = Counter()
    role_count = 0
    changed_role_count = 0
    common_count = 0
    latencies: list[float] = []
    rss_values: list[float] = []
    all_primary_e8 = True
    initial_restart_count = worker.diagnostics().restart_count

    for case in selected:
        try:
            prepared = prepare_finqa_shadow_replay_case_v1(
                case,
                guard=content_guard,
                selected_unit_limit=protocol.dataset.max_selected_units_per_case,
            )
            prepared_count += 1
        except Exception:
            preparation_failures += 1
            continue
        try:
            primary = primary_runtime.select_primary(
                question=prepared.question,
                skeleton=prepared.skeleton,
                catalog=prepared.catalog,
            )
        except Exception:
            primary_failures += 1
            all_primary_e8 = False
            continue
        all_primary_e8 = all_primary_e8 and (
            primary.result.retriever_version == RETRIEVER_VERSION
            and primary.result.generation_calls == 0
        )
        observation = worker.observe(
            primary=primary,
            question=prepared.question,
            skeleton=prepared.skeleton,
            catalog=prepared.catalog,
        )
        attempted_count += 1
        outcomes[observation.outcome] += 1
        if observation.outcome in {"MATCH", "DIVERGED"}:
            completed_count += 1
            role_count += observation.role_count
            changed_role_count += observation.changed_role_count
            common_count += observation.common_descriptor_count_at_4
            latencies.append(observation.latency_ms)
            if observation.worker_peak_rss_bytes is not None:
                rss_values.append(float(observation.worker_peak_rss_bytes))

    return FinQAShadowOperationalReplaySummaryV1(
        preparation=FinQAShadowPreparationSummaryV1(
            selected_case_count=len(selected),
            prepared_case_count=prepared_count,
            preparation_failure_count=preparation_failures,
            primary_failure_count=primary_failures,
        ),
        observations=FinQAShadowObservationSummaryV1(
            attempted_count=attempted_count,
            completed_count=completed_count,
            outcome_counts=dict(sorted(outcomes.items())),
            role_count=role_count,
            changed_role_count=changed_role_count,
            common_descriptor_count_at_4=common_count,
            worker_restart_count=(
                worker.diagnostics().restart_count - initial_restart_count
            ),
            model_call_count=0,
        ),
        latency_ms=_distribution(latencies),
        worker_peak_rss_bytes=_distribution(rss_values),
        all_primary_results_e8=all_primary_e8,
        per_request_rows_persisted=0,
        quality_labels_consumed=0,
    )


def evaluate_shadow_replay_gates_v1(
    summary: FinQAShadowOperationalReplaySummaryV1,
    *,
    protocol: FinQAShadowWorkerReplayProtocolV1,
) -> dict[str, bool]:
    preparation = summary.preparation
    observations = summary.observations
    prepared = preparation.prepared_case_count
    selected = preparation.selected_case_count
    attempted = observations.attempted_count
    gates = protocol.replay_gates
    worker_errors = (
        observations.outcome_counts.get("WORKER_ERROR", 0)
        + observations.outcome_counts.get("WORKER_CRASH", 0)
        + observations.outcome_counts.get("PAYLOAD_REJECTED", 0)
        + observations.outcome_counts.get("INPUT_MISMATCH", 0)
    )
    return {
        "preparation_success_rate": prepared / selected
        >= gates.min_preparation_success_rate,
        "observation_completion_rate": (
            observations.completed_count / attempted if attempted else 0.0
        )
        >= gates.min_observation_completion_rate,
        "worker_error_count": worker_errors <= gates.max_worker_error_count,
        "worker_timeout_count": observations.outcome_counts.get(
            "WORKER_TIMEOUT", 0
        )
        <= gates.max_worker_timeout_count,
        "observation_latency_p95": (
            summary.latency_ms.p95 is not None
            and summary.latency_ms.p95 <= gates.max_observation_latency_p95_ms
        ),
        "worker_peak_rss": (
            summary.worker_peak_rss_bytes.count == observations.completed_count
            and summary.worker_peak_rss_bytes.maximum is not None
            and summary.worker_peak_rss_bytes.maximum
            <= gates.max_worker_peak_rss_bytes
        ),
        "all_primary_results_e8": summary.all_primary_results_e8,
        "zero_model_calls": observations.model_call_count == 0,
        "aggregate_only_output": summary.per_request_rows_persisted == 0,
        "no_quality_labels_or_scores": summary.quality_labels_consumed == 0,
    }


__all__ = [
    "FinQAShadowOperationalReplaySummaryV1",
    "PreparedFinQAShadowReplayCaseV1",
    "evaluate_shadow_replay_gates_v1",
    "load_finqa_shadow_replay_train_v1",
    "prepare_finqa_shadow_replay_case_v1",
    "run_finqa_shadow_operational_replay_v1",
    "select_shadow_replay_cases_v1",
]
