from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluation.wixqa_paired_reranker import summarize_wixqa_reranker_pair


def _write_rows(path: Path, *, omit_candidate: bool = False) -> None:
    rows = []
    for index, (dense, candidate) in enumerate(((0.0, 1.0), (1.0, 1.0)), start=1):
        common = {
            "hit_at_1": dense,
            "latency_ms": 10.0 * index,
            "ndcg_at_5": dense,
            "question_id": f"private-{index}",
            "recall_at_5": dense,
            "reciprocal_rank_at_5": dense,
        }
        rows.append({**common, "arm": "dense"})
        if not (omit_candidate and index == 2):
            rows.append(
                {
                    **common,
                    "arm": "dense_cross_encoder",
                    "hit_at_1": candidate,
                    "latency_ms": 30.0 * index,
                    "ndcg_at_5": candidate,
                    "recall_at_5": candidate,
                    "reciprocal_rank_at_5": candidate,
                }
            )
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_wixqa_paired_summary_is_deterministic_and_aggregate_only(tmp_path: Path) -> None:
    details = tmp_path / "details.jsonl"
    _write_rows(details)

    first = summarize_wixqa_reranker_pair(
        details, expected_case_count=2, bootstrap_iterations=100, seed=7
    )
    second = summarize_wixqa_reranker_pair(
        details, expected_case_count=2, bootstrap_iterations=100, seed=7
    )

    assert first == second
    assert first["metrics"]["recall_at_5"]["delta"] == 0.5
    assert first["metrics"]["recall_at_5"]["wins"] == 1
    assert first["metrics"]["recall_at_5"]["ties"] == 1
    assert first["latency_ms"]["candidate_mean"] == 45.0
    serialized = json.dumps(first)
    assert "private-1" not in serialized
    assert "question_id" not in serialized


def test_wixqa_paired_summary_requires_both_arms(tmp_path: Path) -> None:
    details = tmp_path / "details.jsonl"
    _write_rows(details, omit_candidate=True)

    with pytest.raises(ValueError, match="dense and reranker"):
        summarize_wixqa_reranker_pair(details, expected_case_count=2)
