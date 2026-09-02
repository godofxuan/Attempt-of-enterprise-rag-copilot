from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.uda_finance_page_eval import (
    UdaFinancePageCaseResult,
    UdaFinancePageSummary,
)
from app.external_datasets.uda_finance_r4_canary import R4PairedOutcomes
from app.external_datasets.uda_finance_r5 import UdaFinanceR5Protocol


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class R5Interval(_StrictModel):
    estimate: float
    lower_95: float
    upper_95: float


class R5MacroMetrics(_StrictModel):
    company_count: int = Field(ge=1)
    baseline_page_hit_at_5: float = Field(ge=0, le=1)
    candidate_page_hit_at_5: float = Field(ge=0, le=1)
    page_hit_at_5_delta: float
    baseline_page_ndcg_at_5: float = Field(ge=0, le=1)
    candidate_page_ndcg_at_5: float = Field(ge=0, le=1)
    page_ndcg_at_5_delta: float


class R5GateChecks(_StrictModel):
    minimum_hit_delta: bool
    minimum_ndcg_delta: bool
    hit_cluster_bootstrap_lower_bound_positive: bool
    ndcg_cluster_bootstrap_lower_bound_positive: bool
    candidate_rescues_exceed_regressions: bool
    p95_latency_within_budget: bool
    one_embedding_per_case_per_arm: bool

    @property
    def passed(self) -> bool:
        return all(self.model_dump().values())


class R5PublicEvidence(_StrictModel):
    schema_version: Literal["uda_finance_r5_public_v1"] = "uda_finance_r5_public_v1"
    dataset: Literal["UDA-QA/FinHybrid"] = "UDA-QA/FinHybrid"
    evaluation_scope: Literal["fresh_known_report_page_localization"] = (
        "fresh_known_report_page_localization"
    )
    code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    index_run_id: str = Field(min_length=1)
    index_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_model: str = Field(min_length=1)
    baseline: UdaFinancePageSummary
    candidate: UdaFinancePageSummary
    baseline_details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    paired_outcomes: R4PairedOutcomes
    company_macro: R5MacroMetrics
    page_hit_at_5_cluster_interval: R5Interval
    page_ndcg_at_5_cluster_interval: R5Interval
    p95_latency_multiplier: float = Field(ge=0)
    gate_checks: R5GateChecks
    decision: Literal[
        "PROMOTED_FINANCE_KNOWN_REPORT_DEFAULT",
        "CONFIRMATION_FAILED_RETAIN_LIMITED_CANARY",
    ]
    bootstrap_seed: int
    bootstrap_iterations: int = Field(ge=10_000)
    claim_boundary: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_decision(self) -> R5PublicEvidence:
        expected = (
            "PROMOTED_FINANCE_KNOWN_REPORT_DEFAULT"
            if self.gate_checks.passed
            else "CONFIRMATION_FAILED_RETAIN_LIMITED_CANARY"
        )
        if self.decision != expected:
            raise ValueError("R5 decision does not match its frozen gates")
        return self


def analyze_company_cluster_pairs(
    baseline: Sequence[UdaFinancePageCaseResult],
    candidate: Sequence[UdaFinancePageCaseResult],
    *,
    bootstrap_seed: int,
    bootstrap_iterations: int,
) -> tuple[R4PairedOutcomes, R5MacroMetrics, R5Interval, R5Interval]:
    if bootstrap_iterations < 10_000:
        raise ValueError("R5 cluster bootstrap requires at least 10000 iterations")
    baseline_by_id = _unique_by_case_id(baseline)
    candidate_by_id = _unique_by_case_id(candidate)
    if baseline_by_id.keys() != candidate_by_id.keys():
        raise ValueError("R5 paired case IDs must match exactly")
    by_company: dict[str, list[tuple[float, float, float, float]]] = defaultdict(list)
    both_hit = candidate_only = baseline_only = both_miss = 0
    for case_id in sorted(baseline_by_id):
        baseline_row = baseline_by_id[case_id]
        candidate_row = candidate_by_id[case_id]
        if baseline_row.gold_doc_id != candidate_row.gold_doc_id:
            raise ValueError("R5 paired rows disagree on document identity")
        baseline_rank = _gold_rank_at_five(baseline_row)
        candidate_rank = _gold_rank_at_five(candidate_row)
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
        by_company[baseline_row.gold_doc_id].append(
            (
                float(baseline_hit),
                float(candidate_hit),
                _discounted_gain(baseline_rank),
                _discounted_gain(candidate_rank),
            )
        )
    case_count = len(baseline_by_id)
    baseline_misses = candidate_only + both_miss
    candidate_misses = baseline_only + both_miss
    outcomes = R4PairedOutcomes(
        case_count=case_count,
        both_hit=both_hit,
        candidate_only_hit=candidate_only,
        baseline_only_hit=baseline_only,
        both_miss=both_miss,
        baseline_misses=baseline_misses,
        candidate_misses=candidate_misses,
        relative_miss_reduction=(
            (baseline_misses - candidate_misses) / baseline_misses if baseline_misses else 0.0
        ),
        exact_mcnemar_two_sided_p=_exact_mcnemar_p(candidate_only, baseline_only),
    )
    company_values = []
    for rows in by_company.values():
        count = len(rows)
        company_values.append(
            (
                sum(row[0] for row in rows) / count,
                sum(row[1] for row in rows) / count,
                sum(row[2] for row in rows) / count,
                sum(row[3] for row in rows) / count,
                rows,
            )
        )
    macro = R5MacroMetrics(
        company_count=len(company_values),
        baseline_page_hit_at_5=_mean(item[0] for item in company_values),
        candidate_page_hit_at_5=_mean(item[1] for item in company_values),
        page_hit_at_5_delta=_mean(item[1] - item[0] for item in company_values),
        baseline_page_ndcg_at_5=_mean(item[2] for item in company_values),
        candidate_page_ndcg_at_5=_mean(item[3] for item in company_values),
        page_ndcg_at_5_delta=_mean(item[3] - item[2] for item in company_values),
    )
    rng = random.Random(bootstrap_seed)
    hit_samples: list[float] = []
    ndcg_samples: list[float] = []
    company_count = len(company_values)
    for _ in range(bootstrap_iterations):
        sampled = [company_values[rng.randrange(company_count)] for _ in range(company_count)]
        flattened = [row for company in sampled for row in company[4]]
        hit_samples.append(_mean(row[1] - row[0] for row in flattened))
        ndcg_samples.append(_mean(row[3] - row[2] for row in flattened))
    hit_estimate = _mean(
        float(_gold_rank_at_five(candidate_by_id[key]) is not None)
        - float(_gold_rank_at_five(baseline_by_id[key]) is not None)
        for key in baseline_by_id
    )
    ndcg_estimate = _mean(
        _discounted_gain(_gold_rank_at_five(candidate_by_id[key]))
        - _discounted_gain(_gold_rank_at_five(baseline_by_id[key]))
        for key in baseline_by_id
    )
    return (
        outcomes,
        macro,
        _interval(hit_estimate, hit_samples),
        _interval(ndcg_estimate, ndcg_samples),
    )


def build_r5_public_evidence(
    *,
    code_revision: str,
    protocol_sha256: str,
    dataset_manifest_sha256: str,
    cases_sha256: str,
    index_run_id: str,
    index_manifest_sha256: str,
    embedding_model: str,
    baseline: Sequence[UdaFinancePageCaseResult],
    candidate: Sequence[UdaFinancePageCaseResult],
    baseline_summary: UdaFinancePageSummary,
    candidate_summary: UdaFinancePageSummary,
    baseline_details_sha256: str,
    candidate_details_sha256: str,
    protocol: UdaFinanceR5Protocol,
) -> R5PublicEvidence:
    outcomes, macro, hit_interval, ndcg_interval = analyze_company_cluster_pairs(
        baseline,
        candidate,
        bootstrap_seed=protocol.bootstrap_seed,
        bootstrap_iterations=protocol.bootstrap_iterations,
    )
    latency_multiplier = candidate_summary.latency_ms_p95 / max(
        baseline_summary.latency_ms_p95, 1e-9
    )
    checks = R5GateChecks(
        minimum_hit_delta=(hit_interval.estimate >= protocol.min_page_hit_at_5_delta),
        minimum_ndcg_delta=(ndcg_interval.estimate >= protocol.min_page_ndcg_at_5_delta),
        hit_cluster_bootstrap_lower_bound_positive=hit_interval.lower_95 > 0,
        ndcg_cluster_bootstrap_lower_bound_positive=ndcg_interval.lower_95 > 0,
        candidate_rescues_exceed_regressions=(
            outcomes.candidate_only_hit > outcomes.baseline_only_hit
        ),
        p95_latency_within_budget=(latency_multiplier <= protocol.max_p95_latency_multiplier),
        one_embedding_per_case_per_arm=(
            baseline_summary.embedding_calls == baseline_summary.case_count
            and candidate_summary.embedding_calls == candidate_summary.case_count
        ),
    )
    decision: Literal[
        "PROMOTED_FINANCE_KNOWN_REPORT_DEFAULT",
        "CONFIRMATION_FAILED_RETAIN_LIMITED_CANARY",
    ] = (
        "PROMOTED_FINANCE_KNOWN_REPORT_DEFAULT"
        if checks.passed
        else "CONFIRMATION_FAILED_RETAIN_LIMITED_CANARY"
    )
    return R5PublicEvidence(
        code_revision=code_revision,
        protocol_sha256=protocol_sha256,
        dataset_manifest_sha256=dataset_manifest_sha256,
        cases_sha256=cases_sha256,
        index_run_id=index_run_id,
        index_manifest_sha256=index_manifest_sha256,
        embedding_model=embedding_model,
        baseline=baseline_summary,
        candidate=candidate_summary,
        baseline_details_sha256=baseline_details_sha256,
        candidate_details_sha256=candidate_details_sha256,
        paired_outcomes=outcomes,
        company_macro=macro,
        page_hit_at_5_cluster_interval=hit_interval,
        page_ndcg_at_5_cluster_interval=ndcg_interval,
        p95_latency_multiplier=latency_multiplier,
        gate_checks=checks,
        decision=decision,
        bootstrap_seed=protocol.bootstrap_seed,
        bootstrap_iterations=protocol.bootstrap_iterations,
        claim_boundary=[
            "One-shot confirmation on all remaining eligible UDA companies "
            "not used by prior UDA rounds.",
            "Public-label company-disjoint evidence; not a blind or third-party benchmark.",
            "Known-report page localization only; not answer accuracy or "
            "open-corpus document discovery.",
            "Confidence intervals use company-cluster bootstrap to account for "
            "questions sharing reports.",
            "Questions, answers, company IDs, document IDs, paths, and per-case "
            "failures are excluded.",
        ],
    )


def details_bytes(rows: Sequence[UdaFinancePageCaseResult]) -> bytes:
    return b"".join(_canonical_json_bytes(item.model_dump(mode="json")) for item in rows)


def verify_r5_public_evidence(
    evidence_path: Path,
    *,
    protocol_path: Path,
    private_run_dir: Path | None = None,
) -> R5PublicEvidence:
    evidence = R5PublicEvidence.model_validate_json(Path(evidence_path).read_bytes())
    if hashlib.sha256(Path(protocol_path).read_bytes()).hexdigest() != evidence.protocol_sha256:
        raise ValueError("R5 public evidence protocol hash mismatch")
    if private_run_dir is not None:
        root = Path(private_run_dir)
        for name, expected in (
            ("dense_chunk.jsonl", evidence.baseline_details_sha256),
            ("focused_page_fusion.jsonl", evidence.candidate_details_sha256),
        ):
            if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
                raise ValueError(f"R5 private detail hash mismatch: {name}")
    return evidence


def canonical_json_bytes(value: BaseModel) -> bytes:
    return _canonical_json_bytes(value.model_dump(mode="json"))


def _unique_by_case_id(
    rows: Sequence[UdaFinancePageCaseResult],
) -> dict[str, UdaFinancePageCaseResult]:
    result = {row.case_id: row for row in rows}
    if not result or len(result) != len(rows):
        raise ValueError("R5 paired rows must be non-empty and unique")
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


def _interval(estimate: float, samples: list[float]) -> R5Interval:
    samples.sort()
    lower = samples[int(0.025 * len(samples))]
    upper = samples[max(0, int(0.975 * len(samples)) - 1)]
    return R5Interval(estimate=estimate, lower_95=lower, upper_95=upper)


def _mean(values) -> float:
    materialized = list(values)
    if not materialized:
        raise ValueError("cannot calculate a mean over no values")
    return sum(materialized) / len(materialized)


def _canonical_json_bytes(value: Mapping | object) -> bytes:
    return (
        json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


__all__ = [
    "R5PublicEvidence",
    "analyze_company_cluster_pairs",
    "build_r5_public_evidence",
    "canonical_json_bytes",
    "details_bytes",
    "verify_r5_public_evidence",
]
