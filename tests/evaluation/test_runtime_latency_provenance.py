import pytest

from scripts.measure_wixqa_raw_chunk_online_latency import _quality_rule_passed


def artifact(delta):
    keys = ("article_recall_at_5", "ndcg_at_5", "mrr_at_5", "multi_article_completeness_at_5")
    return {
        "arms": {
            "A2_RAW20_GUARD_ON": {"metrics": dict.fromkeys(keys, 0.5)},
            "A4_RAW50_GUARD_ON": {"metrics": dict.fromkeys(keys, 0.5 + delta)},
        }
    }


def test_quality_gate_is_computed_not_assumed():
    assert _quality_rule_passed(artifact(0.02))
    assert not _quality_rule_passed(artifact(0))
    assert not _quality_rule_passed(artifact(-0.02))


def test_nonfinite_quality_is_rejected():
    with pytest.raises(ValueError):
        _quality_rule_passed(artifact(float("nan")))
