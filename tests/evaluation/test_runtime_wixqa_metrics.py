import pytest

from scripts.eval_runtime_wixqa import metrics


def test_recall_is_macro_gold_coverage_not_hit():
    result = metrics(["a", "b"], ["a", "c"])
    assert result["macro_article_recall_at_5"] == 0.5
    assert result["hit_at_5"] == 1
    assert result["all_gold_at_5"] == 0


def test_duplicates_cannot_inflate_ndcg():
    assert metrics(["a"], ["a", "a", "a"])["ndcg_at_5"] == pytest.approx(1)


def test_failed_empty_ranking_scores_zero():
    assert set(metrics(["a"], []).values()) == {0}
