from __future__ import annotations

from app.external_datasets.wixqa import WixQAQuestion
from scripts.analyze_wixqa_candidate_ceiling import cutoff_metrics


def test_candidate_ceiling_separates_hit_recall_and_multi_article_completion() -> None:
    question = WixQAQuestion(
        question_id="wixqa:simulated:" + "a" * 24,
        cohort="simulated",
        source_row=1,
        question="question",
        answer="answer",
        article_ids=["a", "b"],
        raw_record_sha256="b" * 64,
    )
    metrics = cutoff_metrics(
        question,
        ["x", "a", "y", "z", "q", "r", "b"] + [f"n-{index}" for index in range(20)],
    )
    assert metrics["hit_at_5"] == 1.0
    assert metrics["recall_at_5"] == 0.5
    assert metrics["complete_at_5"] == 0.0
    assert metrics["recall_at_10"] == 1.0
    assert metrics["complete_at_10"] == 1.0
