from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

_METRICS = (
    "recall_at_5",
    "ndcg_at_5",
    "reciprocal_rank_at_5",
    "hit_at_1",
)


def summarize_wixqa_reranker_pair(
    details_path: Path,
    *,
    expected_case_count: int,
    bootstrap_iterations: int = 10_000,
    seed: int = 20_260_902,
) -> dict[str, Any]:
    if expected_case_count < 1:
        raise ValueError("expected_case_count must be positive")
    if bootstrap_iterations < 1:
        raise ValueError("bootstrap_iterations must be positive")
    details_path = Path(details_path)
    rows = [json.loads(line) for line in details_path.read_text(encoding="utf-8").splitlines()]
    paired: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("WixQA detail row must be an object")
        question_id = row.get("question_id")
        arm = row.get("arm")
        if not isinstance(question_id, str) or not question_id:
            raise ValueError("WixQA detail row is missing question_id")
        if arm not in {"dense", "dense_cross_encoder"}:
            continue
        case = paired.setdefault(question_id, {})
        if arm in case:
            raise ValueError(f"duplicate {arm} row for one WixQA case")
        case[arm] = row
    if len(paired) != expected_case_count:
        raise ValueError("WixQA paired case count mismatch")
    if any(set(case) != {"dense", "dense_cross_encoder"} for case in paired.values()):
        raise ValueError("every WixQA case must contain dense and reranker rows")

    ordered = [paired[key] for key in sorted(paired)]
    rng = np.random.default_rng(seed)
    sample_indexes = rng.integers(
        0,
        expected_case_count,
        size=(bootstrap_iterations, expected_case_count),
    )
    metrics: dict[str, dict[str, Any]] = {}
    for metric in _METRICS:
        baseline = np.asarray(
            [_metric_value(case["dense"], metric) for case in ordered], dtype=np.float64
        )
        candidate = np.asarray(
            [_metric_value(case["dense_cross_encoder"], metric) for case in ordered],
            dtype=np.float64,
        )
        delta = candidate - baseline
        bootstrapped = delta[sample_indexes].mean(axis=1)
        metrics[metric] = {
            "baseline": float(baseline.mean()),
            "candidate": float(candidate.mean()),
            "delta": float(delta.mean()),
            "ci95": {
                "high": float(np.quantile(bootstrapped, 0.975)),
                "low": float(np.quantile(bootstrapped, 0.025)),
                "method": "paired_percentile_bootstrap",
            },
            "losses": int(np.count_nonzero(delta < 0)),
            "ties": int(np.count_nonzero(delta == 0)),
            "wins": int(np.count_nonzero(delta > 0)),
        }

    dense_latency = np.asarray(
        [_metric_value(case["dense"], "latency_ms") for case in ordered], dtype=np.float64
    )
    candidate_latency = np.asarray(
        [_metric_value(case["dense_cross_encoder"], "latency_ms") for case in ordered],
        dtype=np.float64,
    )
    dense_p95 = float(np.quantile(dense_latency, 0.95))
    candidate_p95 = float(np.quantile(candidate_latency, 0.95))
    return {
        "bootstrap": {"iterations": bootstrap_iterations, "seed": seed},
        "case_count": expected_case_count,
        "details_sha256": hashlib.sha256(details_path.read_bytes()).hexdigest(),
        "latency_ms": {
            "baseline_mean": float(dense_latency.mean()),
            "baseline_p95": dense_p95,
            "candidate_mean": float(candidate_latency.mean()),
            "candidate_p95": candidate_p95,
            "p95_delta": candidate_p95 - dense_p95,
            "p95_multiplier": candidate_p95 / dense_p95,
        },
        "metrics": metrics,
        "payload_granularity": "aggregate_only",
        "schema_version": "wixqa_paired_reranker_summary_v1",
    }


def _metric_value(row: dict[str, Any], key: str) -> float:
    value = row.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"WixQA detail metric must be numeric: {key}")
    number = float(value)
    if not np.isfinite(number):
        raise ValueError(f"WixQA detail metric must be finite: {key}")
    return number
