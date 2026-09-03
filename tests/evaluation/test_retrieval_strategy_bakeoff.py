import numpy as np
import pytest

from app.evaluation.retrieval_strategy_bakeoff import (
    reciprocal_rank_fusion_scores,
    select_diverse_articles,
)
from app.external_datasets.wixqa_retrieval import reciprocal_rank_fusion
from scripts.eval_retrieval_strategy_bakeoff import select_strategy_ranking, strategy_window


def test_scored_rrf_preserves_existing_rrf_order() -> None:
    bm25 = ["b", "a", "c"]
    dense = ["a", "b", "d"]
    scored = reciprocal_rank_fusion_scores(bm25, dense)
    assert [article_id for article_id, _score in scored] == reciprocal_rank_fusion(bm25, dense)
    assert all(score > 0 for _article_id, score in scored)


def test_diversity_selector_prefers_a_nonredundant_second_item() -> None:
    selected = select_diverse_articles(
        ["a", "b", "c"],
        article_vectors={
            "a": np.asarray([1.0, 0.0]),
            "b": np.asarray([0.99, 0.01]),
            "c": np.asarray([0.0, 1.0]),
        },
        final_k=2,
        alpha=0.75,
    )
    assert selected == ["a", "c"]


def test_diversity_selector_has_stable_article_id_ties() -> None:
    selected = select_diverse_articles(
        ["b", "a"],
        article_vectors={"a": np.asarray([1.0, 0.0]), "b": np.asarray([1.0, 0.0])},
        final_k=2,
        alpha=0.0,
    )
    assert selected == ["a", "b"]


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        ("S0_BASELINE_HYBRID", 5),
        ("S1_DIVERSITY_TOP5", 20),
        ("S2_DEEPER_CANDIDATE_DIVERSITY", 40),
    ],
)
def test_strategy_windows_are_frozen(strategy: str, expected: int) -> None:
    assert strategy_window(strategy) == expected


def test_baseline_strategy_is_rrf_top_five_without_index_access() -> None:
    assert select_strategy_ranking(
        strategy="S0_BASELINE_HYBRID",
        rrf_article_ids=["a", "b", "c", "d", "e", "f"],
        index=None,
        query_vector=None,
    ) == ["a", "b", "c", "d", "e"]
