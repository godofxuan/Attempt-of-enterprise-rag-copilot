from __future__ import annotations

import math
import random
from collections.abc import Iterable, Sequence

from app.evaluation.contracts import ConfidenceInterval, RateMetric


def unique_ranked_doc_ids(doc_ids: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for doc_id in doc_ids:
        if doc_id in seen:
            continue
        seen.add(doc_id)
        result.append(doc_id)
    return result


def document_metrics(
    ranked_doc_ids: Sequence[str],
    gold_doc_ids: Sequence[str],
    *,
    cutoffs: Sequence[int] = (1, 3, 5),
) -> dict[str, float | None]:
    normalized_cutoffs = tuple(sorted(set(cutoffs)))
    if not normalized_cutoffs or any(cutoff < 1 for cutoff in normalized_cutoffs):
        raise ValueError("cutoffs must contain positive integers")
    ranked = unique_ranked_doc_ids(ranked_doc_ids)
    gold = set(gold_doc_ids)
    if len(gold) != len(gold_doc_ids):
        raise ValueError("gold document IDs must be unique")

    metrics: dict[str, float | None] = {}
    for cutoff in normalized_cutoffs:
        if not gold:
            metrics[f"hit@{cutoff}"] = None
            metrics[f"document_recall@{cutoff}"] = None
            metrics[f"full_document_recall@{cutoff}"] = None
            metrics[f"precision@{cutoff}"] = None
            metrics[f"ndcg@{cutoff}"] = None
            metrics[f"invalid_extra_documents@{cutoff}"] = None
            continue
        top = ranked[:cutoff]
        relevant = sum(doc_id in gold for doc_id in top)
        metrics[f"hit@{cutoff}"] = float(relevant > 0)
        metrics[f"document_recall@{cutoff}"] = relevant / len(gold)
        metrics[f"full_document_recall@{cutoff}"] = float(relevant == len(gold))
        metrics[f"precision@{cutoff}"] = relevant / cutoff
        metrics[f"ndcg@{cutoff}"] = _ndcg(top, gold, cutoff)
        metrics[f"invalid_extra_documents@{cutoff}"] = float(
            sum(doc_id not in gold for doc_id in top)
        )

    metrics["mrr"] = _mrr(ranked, gold) if gold else None
    return metrics


def _mrr(ranked: Sequence[str], gold: set[str]) -> float:
    for rank, doc_id in enumerate(ranked, start=1):
        if doc_id in gold:
            return 1.0 / rank
    return 0.0


def _ndcg(ranked: Sequence[str], gold: set[str], cutoff: int) -> float:
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, doc_id in enumerate(ranked[:cutoff], start=1)
        if doc_id in gold
    )
    ideal_relevant = min(len(gold), cutoff)
    idcg = sum(
        1.0 / math.log2(rank + 1)
        for rank in range(1, ideal_relevant + 1)
    )
    return 0.0 if idcg == 0 else dcg / idcg


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    if quantile < 0.0 or quantile > 1.0:
        raise ValueError("quantile must be between 0 and 1")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def bootstrap_rate_ci(
    values: Sequence[bool | int],
    *,
    iterations: int = 2000,
    seed: int = 20260716,
    level: float = 0.95,
) -> ConfidenceInterval | None:
    if len(values) < 2:
        return None
    if iterations < 1:
        raise ValueError("bootstrap iterations must be positive")
    if level <= 0.0 or level >= 1.0:
        raise ValueError("confidence level must be between 0 and 1")
    numeric = [1.0 if bool(value) else 0.0 for value in values]
    rng = random.Random(seed)
    estimates = [
        sum(rng.choice(numeric) for _ in numeric) / len(numeric)
        for _ in range(iterations)
    ]
    alpha = (1.0 - level) / 2.0
    return ConfidenceInterval(
        low=percentile(estimates, alpha),
        high=percentile(estimates, 1.0 - alpha),
        level=level,
        iterations=iterations,
        seed=seed,
    )


def rate_metric(
    values: Sequence[bool | int],
    *,
    bootstrap_iterations: int = 0,
    bootstrap_seed: int = 20260716,
) -> RateMetric:
    total = len(values)
    passed = sum(bool(value) for value in values)
    ci = None
    if bootstrap_iterations and total >= 2:
        ci = bootstrap_rate_ci(
            values,
            iterations=bootstrap_iterations,
            seed=bootstrap_seed,
        )
    return RateMetric(
        passed=passed,
        total=total,
        rate=None if total == 0 else passed / total,
        ci=ci,
    )


__all__ = [
    "bootstrap_rate_ci",
    "document_metrics",
    "percentile",
    "rate_metric",
    "unique_ranked_doc_ids",
]
