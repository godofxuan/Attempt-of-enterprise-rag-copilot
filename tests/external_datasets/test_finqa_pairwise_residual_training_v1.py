from __future__ import annotations

import pytest

from app.external_datasets.finqa_pairwise_residual_training_v1 import (
    top_retrieved_unit_ids_v1,
)


def test_top_retrieved_units_merge_modalities_by_score_deterministically() -> None:
    text = (
        {"score": 0.9, "ind": "text_2"},
        {"score": 0.5, "ind": "text_1"},
    )
    table = (
        {"score": 0.9, "ind": "table_1"},
        {"score": 0.7, "ind": "table_2"},
    )

    selected = top_retrieved_unit_ids_v1(text, table, limit=3)

    assert selected == ("table_1", "text_2", "table_2")


def test_top_retrieved_units_reject_duplicate_or_malformed_rows() -> None:
    duplicate = (
        {"score": 0.9, "ind": "text_1"},
        {"score": 0.8, "ind": "text_1"},
    )
    with pytest.raises(ValueError, match="IDs"):
        top_retrieved_unit_ids_v1(duplicate, (), limit=1)

    with pytest.raises(ValueError, match="malformed"):
        top_retrieved_unit_ids_v1(
            ({"score": float("nan"), "ind": "text_1"},),
            (),
            limit=1,
        )


def test_top_retrieved_units_return_all_when_source_has_fewer_than_limit() -> None:
    selected = top_retrieved_unit_ids_v1(
        ({"score": 0.9, "ind": "text_1"},),
        ({"score": 0.8, "ind": "table_1"},),
        limit=10,
    )

    assert selected == ("text_1", "table_1")
