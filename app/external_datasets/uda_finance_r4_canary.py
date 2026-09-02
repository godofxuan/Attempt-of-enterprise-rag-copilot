from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.uda_finance_page_eval import UdaFinancePageCaseResult
from app.external_datasets.uda_finance_r4_public import R4PublicEvidence


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PairedInterval(_StrictModel):
    estimate: float
    lower_95: float
    upper_95: float


class R4PairedOutcomes(_StrictModel):
    case_count: int = Field(ge=1)
    both_hit: int = Field(ge=0)
    candidate_only_hit: int = Field(ge=0)
    baseline_only_hit: int = Field(ge=0)
    both_miss: int = Field(ge=0)
    baseline_misses: int = Field(ge=0)
    candidate_misses: int = Field(ge=0)
    relative_miss_reduction: float
    exact_mcnemar_two_sided_p: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_counts(self) -> R4PairedOutcomes:
        if (
            self.both_hit + self.candidate_only_hit + self.baseline_only_hit + self.both_miss
            != self.case_count
        ):
            raise ValueError("paired outcome counts do not sum to the case count")
        return self


class R4CanaryChecks(_StrictModel):
    observed_hit_non_decreasing: bool
    candidate_rescues_exceed_regressions: bool
    ndcg_bootstrap_lower_bound_positive: bool
    p95_latency_multiplier_at_most_1_10: bool

    @property
    def passed(self) -> bool:
        return all(self.model_dump().values())


class R4CanaryEvidence(_StrictModel):
    schema_version: Literal["uda_finance_r4_canary_review_v1"] = "uda_finance_r4_canary_review_v1"
    review_type: Literal["POST_HOC_EXPLORATORY_ENGINEERING_REVIEW"] = (
        "POST_HOC_EXPLORATORY_ENGINEERING_REVIEW"
    )
    dataset: Literal["UDA-QA/FinHybrid"] = "UDA-QA/FinHybrid"
    evaluation_scope: Literal["known_report_page_localization"] = "known_report_page_localization"
    source_public_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_validation_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bootstrap_seed: int
    bootstrap_iterations: int = Field(ge=1_000)
    paired_outcomes: R4PairedOutcomes
    page_hit_at_5_delta: PairedInterval
    page_ndcg_at_5_delta: PairedInterval
    p95_latency_multiplier: float = Field(ge=0)
    canary_checks: R4CanaryChecks
    original_gate_decision: Literal["VALIDATION_REJECTED_TEST_FORBIDDEN"]
    frozen_test_status: Literal["NOT_RUN_ORIGINAL_GATE_FORBIDS"]
    promotion_decision: Literal["LIMITED_CANARY_APPROVED"]
    runtime_profile: Literal["finance_known_report_page_fusion_v1"]
    activation: Literal["EXPLICIT_OPT_IN_ONLY"]
    exit_requirement: Literal["FRESH_COMPANY_DISJOINT_COHORT_REQUIRED"]
    claim_boundary: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_decision(self) -> R4CanaryEvidence:
        if not self.canary_checks.passed:
            raise ValueError("limited canary requires every exploratory rollout check")
        if self.page_hit_at_5_delta.estimate < 0:
            raise ValueError("limited canary cannot reduce observed Hit@5")
        return self


def analyze_r4_pairs(
    baseline: Sequence[UdaFinancePageCaseResult],
    candidate: Sequence[UdaFinancePageCaseResult],
    *,
    bootstrap_seed: int = 20260902,
    bootstrap_iterations: int = 100_000,
) -> tuple[R4PairedOutcomes, PairedInterval, PairedInterval]:
    if bootstrap_iterations < 1_000:
        raise ValueError("paired bootstrap requires at least 1000 iterations")
    baseline_by_id = _unique_by_case_id(baseline)
    candidate_by_id = _unique_by_case_id(candidate)
    if baseline_by_id.keys() != candidate_by_id.keys():
        raise ValueError("baseline and candidate case IDs must match exactly")

    paired_values: list[tuple[float, float]] = []
    both_hit = candidate_only = baseline_only = both_miss = 0
    for case_id in sorted(baseline_by_id):
        baseline_rank = _gold_rank_at_five(baseline_by_id[case_id])
        candidate_rank = _gold_rank_at_five(candidate_by_id[case_id])
        baseline_hit = baseline_rank is not None
        candidate_hit = candidate_rank is not None
        if baseline_hit and candidate_hit:
            both_hit += 1
        elif candidate_hit:
            candidate_only += 1
        elif baseline_hit:
            baseline_only += 1
        else:
            both_miss += 1
        paired_values.append(
            (
                float(candidate_hit) - float(baseline_hit),
                _discounted_gain(candidate_rank) - _discounted_gain(baseline_rank),
            )
        )

    case_count = len(paired_values)
    baseline_misses = candidate_only + both_miss
    candidate_misses = baseline_only + both_miss
    relative_miss_reduction = (
        (baseline_misses - candidate_misses) / baseline_misses if baseline_misses else 0.0
    )
    outcomes = R4PairedOutcomes(
        case_count=case_count,
        both_hit=both_hit,
        candidate_only_hit=candidate_only,
        baseline_only_hit=baseline_only,
        both_miss=both_miss,
        baseline_misses=baseline_misses,
        candidate_misses=candidate_misses,
        relative_miss_reduction=relative_miss_reduction,
        exact_mcnemar_two_sided_p=_exact_mcnemar_p(candidate_only, baseline_only),
    )
    hit_values = [item[0] for item in paired_values]
    ndcg_values = [item[1] for item in paired_values]
    rng = random.Random(bootstrap_seed)
    hit_samples: list[float] = []
    ndcg_samples: list[float] = []
    for _ in range(bootstrap_iterations):
        indices = [rng.randrange(case_count) for _ in range(case_count)]
        hit_samples.append(sum(hit_values[index] for index in indices) / case_count)
        ndcg_samples.append(sum(ndcg_values[index] for index in indices) / case_count)
    return (
        outcomes,
        _paired_interval(hit_values, hit_samples),
        _paired_interval(ndcg_values, ndcg_samples),
    )


def build_r4_canary_evidence(
    *,
    source_public_evidence: R4PublicEvidence,
    source_public_evidence_sha256: str,
    baseline: Sequence[UdaFinancePageCaseResult],
    candidate: Sequence[UdaFinancePageCaseResult],
    baseline_details_sha256: str,
    candidate_details_sha256: str,
    bootstrap_seed: int = 20260902,
    bootstrap_iterations: int = 100_000,
) -> R4CanaryEvidence:
    if source_public_evidence.promotion_decision != "REJECTED":
        raise ValueError("canary review must preserve the original rejected decision")
    if source_public_evidence.frozen_test_status != "NOT_RUN_VALIDATION_GATE_FORBIDS":
        raise ValueError("canary review cannot follow an executed frozen test")
    outcomes, hit_interval, ndcg_interval = analyze_r4_pairs(
        baseline,
        candidate,
        bootstrap_seed=bootstrap_seed,
        bootstrap_iterations=bootstrap_iterations,
    )
    validation = source_public_evidence.validation
    latency_multiplier = validation.p95_latency_multiplier
    checks = R4CanaryChecks(
        observed_hit_non_decreasing=hit_interval.estimate >= 0,
        candidate_rescues_exceed_regressions=(
            outcomes.candidate_only_hit > outcomes.baseline_only_hit
        ),
        ndcg_bootstrap_lower_bound_positive=ndcg_interval.lower_95 > 0,
        p95_latency_multiplier_at_most_1_10=latency_multiplier <= 1.10,
    )
    return R4CanaryEvidence(
        source_public_evidence_sha256=source_public_evidence_sha256,
        source_validation_manifest_sha256=validation.source_manifest_sha256,
        baseline_details_sha256=baseline_details_sha256,
        candidate_details_sha256=candidate_details_sha256,
        bootstrap_seed=bootstrap_seed,
        bootstrap_iterations=bootstrap_iterations,
        paired_outcomes=outcomes,
        page_hit_at_5_delta=hit_interval,
        page_ndcg_at_5_delta=ndcg_interval,
        p95_latency_multiplier=latency_multiplier,
        canary_checks=checks,
        original_gate_decision="VALIDATION_REJECTED_TEST_FORBIDDEN",
        frozen_test_status="NOT_RUN_ORIGINAL_GATE_FORBIDS",
        promotion_decision="LIMITED_CANARY_APPROVED",
        runtime_profile="finance_known_report_page_fusion_v1",
        activation="EXPLICIT_OPT_IN_ONLY",
        exit_requirement="FRESH_COMPANY_DISJOINT_COHORT_REQUIRED",
        claim_boundary=[
            "Post-hoc exploratory rollout decision; not a replacement for the preregistered gate.",
            "External public-label company-disjoint validation; not a blind benchmark.",
            "Known-report page localization only; not document discovery or answer accuracy.",
            "Hit@5 uncertainty includes zero; the profile is limited canary, not global default.",
            "Runtime activation requires an operator-owned policy ID allowlist.",
            "The original frozen test remains unexecuted and cannot be claimed.",
            "Questions, company identifiers, source paths, and case IDs are excluded.",
        ],
    )


def verify_r4_canary_evidence(
    evidence_path: Path,
    *,
    source_public_evidence_path: Path,
) -> R4CanaryEvidence:
    evidence = R4CanaryEvidence.model_validate_json(Path(evidence_path).read_bytes())
    source_bytes = Path(source_public_evidence_path).read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != evidence.source_public_evidence_sha256:
        raise ValueError("R4 canary source public evidence hash mismatch")
    source = R4PublicEvidence.model_validate_json(source_bytes)
    if source.promotion_decision != "REJECTED":
        raise ValueError("R4 canary source no longer preserves the original rejection")
    if source.validation.source_manifest_sha256 != evidence.source_validation_manifest_sha256:
        raise ValueError("R4 canary validation manifest binding mismatch")
    return evidence


def canonical_json_bytes(value: BaseModel) -> bytes:
    return (
        json.dumps(
            value.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _unique_by_case_id(
    rows: Sequence[UdaFinancePageCaseResult],
) -> dict[str, UdaFinancePageCaseResult]:
    result = {row.case_id: row for row in rows}
    if not result or len(result) != len(rows):
        raise ValueError("paired rows must be non-empty and have unique case IDs")
    return result


def _gold_rank_at_five(row: UdaFinancePageCaseResult) -> int | None:
    return next(
        (
            page.first_hit_rank
            for page in row.score.ranked_pages
            if page.doc_id == row.gold_doc_id
            and page.page_number == row.gold_page_number
            and page.first_hit_rank <= 5
        ),
        None,
    )


def _discounted_gain(rank: int | None) -> float:
    return 0.0 if rank is None else 1.0 / math.log2(rank + 1)


def _exact_mcnemar_p(candidate_only: int, baseline_only: int) -> float:
    discordant = candidate_only + baseline_only
    if discordant == 0:
        return 1.0
    tail = sum(
        math.comb(discordant, value) for value in range(min(candidate_only, baseline_only) + 1)
    ) / (2**discordant)
    return min(1.0, 2.0 * tail)


def _paired_interval(values: Sequence[float], samples: list[float]) -> PairedInterval:
    samples.sort()
    lower_index = int(0.025 * len(samples))
    upper_index = max(lower_index, int(0.975 * len(samples)) - 1)
    return PairedInterval(
        estimate=sum(values) / len(values),
        lower_95=samples[lower_index],
        upper_95=samples[upper_index],
    )


__all__ = [
    "R4CanaryEvidence",
    "analyze_r4_pairs",
    "build_r4_canary_evidence",
    "canonical_json_bytes",
    "verify_r4_canary_evidence",
]
