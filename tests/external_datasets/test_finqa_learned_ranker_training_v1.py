from __future__ import annotations

import pytest

from app.external_datasets.finqa_learned_ranker_training_v1 import (
    assign_company_folds_v1,
    finqa_company_id,
)


def test_company_id_uses_only_safe_finqa_path_prefix() -> None:
    assert finqa_company_id("AAPL/2019/page_10.pdf") == "AAPL"
    assert finqa_company_id("AAPL\\2019\\page_10.pdf") == "AAPL"

    with pytest.raises(ValueError, match="safe company"):
        finqa_company_id("../2019/page_10.pdf")


def test_weighted_company_folds_are_deterministic_disjoint_and_balanced() -> None:
    counts = {"A": 8, "B": 7, "C": 6, "D": 5, "E": 4, "F": 3}

    first = assign_company_folds_v1(counts, fold_count=3, seed="fixed")
    second = assign_company_folds_v1(counts, fold_count=3, seed="fixed")

    assert first == second
    assert set(first) == set(counts)
    fold_rows = [
        sum(count for company, count in counts.items() if first[company] == fold)
        for fold in range(3)
    ]
    assert max(fold_rows) - min(fold_rows) <= max(counts.values())
