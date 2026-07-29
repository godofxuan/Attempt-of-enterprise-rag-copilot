from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa import (
    FinQACase,
    stable_sample_finqa_cases,
)
from app.external_datasets.finqa_adjudication import (
    FinQAAdjudicationCaseEvaluation,
)
from app.external_datasets.finqa_eval import FinQASummary, summarize_finqa_cases
from app.external_datasets.finqa_review import FINQA_REVIEW_PROMPT_VERSION
from app.external_datasets.finqa_uncertainty import (
    FINQA_UNCERTAINTY_ALGORITHM_VERSION,
    FinQARuntimeUncertainty,
    FinQAUncertaintyCaseEvaluation,
    FinQAUncertaintySummary,
    evaluate_finqa_uncertainty_case,
    summarize_finqa_uncertainty_cases,
)
from app.filesystem import atomic_directory_move


FINQA_SELECTIVE_PIPELINE_VERSION = "finqa_selective_execution_v1"
_SELECTIVE_ARTIFACTS = {"details.jsonl", "summary.json"}

FinQASelectiveRoute = Literal[
    "baseline",
    "reviewed_kept",
    "adjudicated",
]


class FinQASelectiveExclusionSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=200)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_case_count: int = Field(ge=1)


class FinQASelectiveModelIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FinQASelectiveSuccessGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selective_strict_at_least_baseline: Literal[True] = True
    selective_grounded_strict_at_least_baseline: Literal[True] = True
    correct_to_wrong_max: int = Field(ge=0)
    trigger_rate_max: float = Field(gt=0, le=1)
    generation_call_reduction_min: float = Field(ge=0, lt=1)
    calculator_call_reduction_min: float = Field(ge=0, lt=1)
    exact_mcnemar_p_value_max: float = Field(gt=0, le=1)
    observed_selective_latency_required: Literal[True] = True
    normal_cuda_required_for_latency_claim: Literal[True] = True


class FinQASelectiveReviewRuntimeOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    num_gpu: Literal[5]
    num_ctx: Literal[4096]
    num_batch: Literal[512]


class FinQASelectiveExecutionProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["finqa_selective_execution_protocol_v2"] = (
        "finqa_selective_execution_protocol_v2"
    )
    status: Literal["FROZEN_BEFORE_EXECUTION"]
    frozen_at_utc: str = Field(
        pattern=(
            r"^\d{4}-\d{2}-\d{2}T"
            r"\d{2}:\d{2}:\d{2}Z$"
        )
    )
    freeze_parent_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    dataset_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    split: Literal["dev"]
    split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_seed: str = Field(min_length=1, max_length=200)
    sample_count: int = Field(ge=1)
    selected_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    excluded_case_count: int = Field(ge=1)
    excluded_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    overlap_with_excluded_case_count: Literal[0] = 0
    exclusion_sources: list[FinQASelectiveExclusionSource] = Field(
        min_length=1
    )
    retrieval_mode: Literal["hybrid"]
    top_k: int = Field(ge=1, le=20)
    answer_strategy: Literal["program"]
    answer_model: FinQASelectiveModelIdentity
    review_model: FinQASelectiveModelIdentity
    adjudicator_model: FinQASelectiveModelIdentity
    embedding_model: FinQASelectiveModelIdentity
    review_prompt_version: Literal["finqa_plan_review_v2"]
    review_runtime_options: FinQASelectiveReviewRuntimeOptions
    uncertainty_algorithm_version: Literal[
        "finqa_runtime_uncertainty_v1"
    ]
    pipeline_version: Literal["finqa_selective_execution_v1"]
    timeout_seconds: float = Field(gt=0, le=300)
    max_attempts: int = Field(ge=1, le=3)
    shadow_full_strategy: Literal[True] = True
    runtime_backend_requirement: Literal["normal_cuda_no_vulkan"]
    success_gate: FinQASelectiveSuccessGate
    source_sha256: dict[str, str] = Field(min_length=1)
    public_content_boundary: Literal[
        "aggregate_metrics_hashes_and_versions_only"
    ]

    @model_validator(mode="after")
    def validate_sources(self) -> FinQASelectiveExecutionProtocol:
        run_ids = [source.run_id for source in self.exclusion_sources]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError(
                "FinQA selective exclusion sources must be unique"
            )
        if any(
            re.fullmatch(r"[0-9a-f]{64}", digest) is None
            for digest in self.source_sha256.values()
        ):
            raise ValueError("FinQA selective source hash is invalid")
        return self


class FinQASelectiveCaseEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    signal: FinQARuntimeUncertainty
    full_strategy_execution: FinQAAdjudicationCaseEvaluation
    policy: FinQAUncertaintyCaseEvaluation
    route: FinQASelectiveRoute
    production_review_executed: bool
    production_adjudication_executed: bool
    shadow_review_executed: bool
    shadow_adjudication_executed: bool
    observed_selective_latency_ms: float = Field(ge=0)
    observed_shadow_latency_ms: float = Field(ge=0)
    observed_experiment_latency_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_execution_boundaries(
        self,
    ) -> FinQASelectiveCaseEvaluation:
        execution = self.full_strategy_execution
        if not (
            self.case_id
            == self.signal.case_id
            == execution.case_id
            == self.policy.case_id
        ):
            raise ValueError("FinQA selective case IDs do not match")
        expected_policy = evaluate_finqa_uncertainty_case(
            execution,
            self.signal,
        )
        if self.policy != expected_policy:
            raise ValueError("FinQA selective policy result is inconsistent")

        eligible = self.signal.eligible_for_plan_review
        triggered = self.signal.triggered
        if triggered and not eligible:
            raise ValueError("ineligible FinQA case cannot trigger review")
        expected_production_review = triggered
        expected_shadow_review = eligible and not triggered
        revised = execution.proposal_review_status == "revised"
        expected_production_adjudication = triggered and revised
        expected_shadow_adjudication = (
            eligible and not triggered and revised
        )
        if (
            self.production_review_executed
            != expected_production_review
            or self.shadow_review_executed != expected_shadow_review
            or self.production_adjudication_executed
            != expected_production_adjudication
            or self.shadow_adjudication_executed
            != expected_shadow_adjudication
        ):
            raise ValueError(
                "FinQA selective production/shadow flags are invalid"
            )

        expected_route: FinQASelectiveRoute
        if not triggered:
            expected_route = "baseline"
        elif revised:
            expected_route = "adjudicated"
        else:
            expected_route = "reviewed_kept"
        if self.route != expected_route:
            raise ValueError("FinQA selective route is invalid")
        if abs(
            self.observed_experiment_latency_ms
            - self.observed_selective_latency_ms
            - self.observed_shadow_latency_ms
        ) > 1e-3:
            raise ValueError("FinQA selective observed latency is inconsistent")
        if triggered and self.observed_shadow_latency_ms != 0:
            raise ValueError("triggered FinQA case cannot execute shadow work")
        if not expected_shadow_review and self.observed_shadow_latency_ms != 0:
            raise ValueError(
                "FinQA case without shadow review cannot report shadow latency"
            )
        return self


class FinQASelectiveSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_count: int = Field(ge=1)
    baseline: FinQASummary
    selective: FinQASummary
    full_strategy: FinQASummary
    policy: FinQAUncertaintySummary
    route_counts: dict[FinQASelectiveRoute, int]
    production_review_case_count: int = Field(ge=0)
    production_adjudication_case_count: int = Field(ge=0)
    shadow_review_case_count: int = Field(ge=0)
    shadow_adjudication_case_count: int = Field(ge=0)
    observed_selective_latency_ms_mean: float = Field(ge=0)
    observed_selective_latency_ms_p95: float = Field(ge=0)
    observed_selective_latency_ms_total: float = Field(ge=0)
    observed_shadow_latency_ms_total: float = Field(ge=0)
    observed_experiment_latency_ms_total: float = Field(ge=0)


class FinQASelectiveRunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["finqa_selective_run_v2"] = (
        "finqa_selective_run_v2"
    )
    selective_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$"
    )
    pipeline_version: Literal["finqa_selective_execution_v1"] = (
        FINQA_SELECTIVE_PIPELINE_VERSION
    )
    uncertainty_algorithm_version: Literal[
        "finqa_runtime_uncertainty_v1"
    ] = FINQA_UNCERTAINTY_ALGORITHM_VERSION
    review_prompt_version: Literal[
        "finqa_plan_review_v2"
    ] = FINQA_REVIEW_PROMPT_VERSION
    adjudication_prompt_version: Literal[
        "finqa_candidate_adjudication_v1"
    ] = "finqa_candidate_adjudication_v1"
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    split: Literal["dev"]
    split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    excluded_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    excluded_case_count: int = Field(ge=1)
    selected_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_case_count: int = Field(ge=1)
    sample_seed: str = Field(min_length=1, max_length=200)
    retrieval_mode: Literal["hybrid"]
    top_k: int = Field(ge=1, le=20)
    answer_model: str = Field(min_length=1)
    answer_model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_model: str = Field(min_length=1)
    review_model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_runtime_options: FinQASelectiveReviewRuntimeOptions
    adjudicator_model: str = Field(min_length=1)
    adjudicator_model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_model: str = Field(min_length=1)
    embedding_model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_backend: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,100}$")
    code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    timeout_seconds: float = Field(gt=0, le=300)
    max_attempts: int = Field(ge=1, le=3)
    shadow_full_strategy: Literal[True] = True
    summary: FinQASelectiveSummary
    artifacts: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_artifacts(self) -> FinQASelectiveRunManifest:
        if self.artifacts and (
            set(self.artifacts) != _SELECTIVE_ARTIFACTS
            or any(
                re.fullmatch(r"[0-9a-f]{64}", digest) is None
                for digest in self.artifacts.values()
            )
        ):
            raise ValueError("FinQA selective artifact set is invalid")
        return self


def select_finqa_cases_excluding(
    cases: Sequence[FinQACase],
    *,
    excluded_case_ids: Iterable[str],
    count: int,
    seed: str,
) -> list[FinQACase]:
    values = list(cases)
    case_ids = {case.id for case in values}
    excluded = set(excluded_case_ids)
    if not excluded:
        raise ValueError("FinQA selective exclusion set cannot be empty")
    unknown = excluded - case_ids
    if unknown:
        raise ValueError("FinQA selective exclusion references unknown cases")
    available = [case for case in values if case.id not in excluded]
    return stable_sample_finqa_cases(
        available,
        count=count,
        seed=seed,
    )


def case_ids_sha256(case_ids: Iterable[str]) -> str:
    values = list(case_ids)
    if not values or len(values) != len(set(values)):
        raise ValueError("FinQA case IDs must be non-empty and unique")
    return hashlib.sha256(
        ("\n".join(values) + "\n").encode("utf-8")
    ).hexdigest()


def unordered_case_ids_sha256(case_ids: Iterable[str]) -> str:
    return case_ids_sha256(sorted(case_ids))


def summarize_finqa_selective_cases(
    rows: Sequence[FinQASelectiveCaseEvaluation],
) -> FinQASelectiveSummary:
    values = list(rows)
    if not values:
        raise ValueError("FinQA selective summary requires cases")
    if len({row.case_id for row in values}) != len(values):
        raise ValueError("FinQA selective case IDs must be unique")
    policy_rows = [row.policy for row in values]
    selective_latencies = sorted(
        row.observed_selective_latency_ms for row in values
    )
    p95_index = max(
        0,
        int(np.ceil(len(selective_latencies) * 0.95)) - 1,
    )
    routes = Counter(row.route for row in values)
    route_names: tuple[FinQASelectiveRoute, ...] = (
        "baseline",
        "reviewed_kept",
        "adjudicated",
    )
    return FinQASelectiveSummary(
        case_count=len(values),
        baseline=summarize_finqa_cases(
            [row.policy.baseline for row in values]
        ),
        selective=summarize_finqa_cases(
            [row.policy.gated for row in values]
        ),
        full_strategy=summarize_finqa_cases(
            [row.policy.full_strategy for row in values]
        ),
        policy=summarize_finqa_uncertainty_cases(policy_rows),
        route_counts={name: routes[name] for name in route_names},
        production_review_case_count=sum(
            row.production_review_executed for row in values
        ),
        production_adjudication_case_count=sum(
            row.production_adjudication_executed for row in values
        ),
        shadow_review_case_count=sum(
            row.shadow_review_executed for row in values
        ),
        shadow_adjudication_case_count=sum(
            row.shadow_adjudication_executed for row in values
        ),
        observed_selective_latency_ms_mean=(
            sum(selective_latencies) / len(values)
        ),
        observed_selective_latency_ms_p95=(
            selective_latencies[p95_index]
        ),
        observed_selective_latency_ms_total=sum(selective_latencies),
        observed_shadow_latency_ms_total=sum(
            row.observed_shadow_latency_ms for row in values
        ),
        observed_experiment_latency_ms_total=sum(
            row.observed_experiment_latency_ms for row in values
        ),
    )


def publish_finqa_selective_run(
    *,
    root: Path,
    manifest: FinQASelectiveRunManifest,
    details: Sequence[FinQASelectiveCaseEvaluation],
) -> Path:
    rows = list(details)
    if manifest.artifacts:
        raise ValueError(
            "FinQA selective artifacts are assigned during publication"
        )
    _validate_run_rows(rows, manifest)
    if summarize_finqa_selective_cases(rows) != manifest.summary:
        raise ValueError("FinQA selective summary does not match details")

    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    final = root / manifest.selective_run_id
    if final.exists():
        raise FileExistsError(
            f"FinQA selective run already exists: {manifest.selective_run_id}"
        )
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{manifest.selective_run_id}.staging-",
            dir=root,
        )
    )
    try:
        details_bytes = b"".join(
            _canonical_json_bytes(row.model_dump(mode="json"))
            for row in rows
        )
        summary_bytes = _canonical_json_bytes(
            manifest.summary.model_dump(mode="json")
        )
        artifact_bytes = {
            "details.jsonl": details_bytes,
            "summary.json": summary_bytes,
        }
        artifacts = {
            name: hashlib.sha256(content).hexdigest()
            for name, content in artifact_bytes.items()
        }
        final_manifest = manifest.model_copy(update={"artifacts": artifacts})
        for name, content in artifact_bytes.items():
            (staging / name).write_bytes(content)
        (staging / "manifest.json").write_bytes(
            _canonical_json_bytes(final_manifest.model_dump(mode="json"))
        )
        verify_finqa_selective_run(staging)
        atomic_directory_move(staging, final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    verify_finqa_selective_run(final)
    return final


def verify_finqa_selective_run(
    run_dir: Path,
) -> FinQASelectiveRunManifest:
    run_dir = Path(run_dir).resolve()
    expected_files = {*_SELECTIVE_ARTIFACTS, "manifest.json"}
    actual_files = {
        child.name for child in run_dir.iterdir() if child.is_file()
    }
    if actual_files != expected_files:
        raise ValueError(
            "FinQA selective run has an unexpected artifact set"
        )
    manifest = FinQASelectiveRunManifest.model_validate_json(
        (run_dir / "manifest.json").read_bytes()
    )
    if (
        manifest.selective_run_id != run_dir.name
        and ".staging-" not in run_dir.name
    ):
        raise ValueError(
            "FinQA selective directory does not match manifest ID"
        )
    for name, expected_sha256 in manifest.artifacts.items():
        actual_sha256 = hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(f"FinQA selective artifact mismatch: {name}")
    details = [
        FinQASelectiveCaseEvaluation.model_validate(
            json.loads(line, object_pairs_hook=_unique_object)
        )
        for line in (run_dir / "details.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    _validate_run_rows(details, manifest)
    summary = FinQASelectiveSummary.model_validate_json(
        (run_dir / "summary.json").read_bytes()
    )
    if summary != manifest.summary:
        raise ValueError("FinQA selective manifest summary does not match")
    if summarize_finqa_selective_cases(details) != summary:
        raise ValueError("FinQA selective summary cannot be reproduced")
    return manifest


def _validate_run_rows(
    rows: Sequence[FinQASelectiveCaseEvaluation],
    manifest: FinQASelectiveRunManifest,
) -> None:
    if len(rows) != manifest.selected_case_count:
        raise ValueError("FinQA selective case count mismatch")
    if (
        case_ids_sha256(row.case_id for row in rows)
        != manifest.selected_case_ids_sha256
    ):
        raise ValueError("FinQA selective selected case hash mismatch")
    if any(
        row.policy.baseline.retrieval_mode != manifest.retrieval_mode
        for row in rows
    ):
        raise ValueError("FinQA selective retrieval mode mismatch")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


__all__ = [
    "FINQA_SELECTIVE_PIPELINE_VERSION",
    "FinQASelectiveCaseEvaluation",
    "FinQASelectiveExecutionProtocol",
    "FinQASelectiveRunManifest",
    "FinQASelectiveSummary",
    "case_ids_sha256",
    "publish_finqa_selective_run",
    "select_finqa_cases_excluding",
    "summarize_finqa_selective_cases",
    "unordered_case_ids_sha256",
    "verify_finqa_selective_run",
]
