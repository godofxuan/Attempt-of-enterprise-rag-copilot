from __future__ import annotations

import pytest

from app.evaluation.metrics import (
    bootstrap_rate_ci,
    document_metrics,
    percentile,
    rate_metric,
    unique_ranked_doc_ids,
)


def test_unique_ranked_doc_ids_preserves_first_rank() -> None:
    assert unique_ranked_doc_ids(["a", "a", "x", "b", "x"]) == [
        "a",
        "x",
        "b",
    ]


def test_document_metrics_do_not_reward_duplicate_chunks() -> None:
    metrics = document_metrics(
        ["doc-a", "doc-a", "extra", "doc-b"],
        ["doc-a", "doc-b"],
        cutoffs=(1, 3, 5),
    )

    assert metrics["hit@1"] == 1.0
    assert metrics["hit@3"] == 1.0
    assert metrics["document_recall@1"] == 0.5
    assert metrics["document_recall@3"] == 1.0
    assert metrics["full_document_recall@3"] == 1.0
    assert metrics["precision@3"] == pytest.approx(2 / 3)
    assert metrics["invalid_extra_documents@3"] == 1.0
    assert metrics["mrr"] == 1.0
    assert 0.0 < metrics["ndcg@3"] <= 1.0


def test_document_metrics_return_none_for_no_gold_docs() -> None:
    metrics = document_metrics(["doc-a"], [], cutoffs=(1, 5))

    assert metrics["hit@1"] is None
    assert metrics["document_recall@5"] is None
    assert metrics["mrr"] is None
    assert metrics["ndcg@5"] is None


def test_bootstrap_rate_ci_is_deterministic_and_records_method() -> None:
    first = bootstrap_rate_ci(
        [True, True, False, True],
        iterations=400,
        seed=20260716,
    )
    second = bootstrap_rate_ci(
        [True, True, False, True],
        iterations=400,
        seed=20260716,
    )

    assert first == second
    assert first is not None
    assert 0.0 <= first.low <= first.high <= 1.0
    assert first.method == "percentile_bootstrap"
    assert first.iterations == 400
    assert first.seed == 20260716


def test_bootstrap_rate_ci_is_not_reported_for_fewer_than_two_values() -> None:
    assert bootstrap_rate_ci([], iterations=100, seed=1) is None
    assert bootstrap_rate_ci([True], iterations=100, seed=1) is None


def test_rate_metric_keeps_count_and_optional_ci() -> None:
    metric = rate_metric(
        [True, False, True],
        bootstrap_iterations=200,
        bootstrap_seed=7,
    )

    assert metric.passed == 2
    assert metric.total == 3
    assert metric.rate == pytest.approx(2 / 3)
    assert metric.ci is not None


def test_percentile_uses_linear_interpolation() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.0) == 1.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 1.0) == 4.0
