from app.eval_metrics import (
    coverage_at_k,
    hit_at_k,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def src(source: str, section: str) -> dict:
    return {"source": source, "section": section}


def test_hit_at_k():
    gold = [src("a.md", "A")]
    retrieved = [src("b.md", "B"), src("a.md", "A")]
    assert hit_at_k(retrieved, gold, 1) == 0
    assert hit_at_k(retrieved, gold, 2) == 1


def test_recall_and_coverage_with_multiple_gold_sources():
    gold = [src("a.md", "A"), src("b.md", "B")]
    retrieved = [src("a.md", "A"), src("c.md", "C")]
    assert recall_at_k(retrieved, gold, 2) == 0.5
    assert coverage_at_k(retrieved, gold, 2) == 0

    retrieved.append(src("b.md", "B"))
    assert recall_at_k(retrieved, gold, 3) == 1.0
    assert coverage_at_k(retrieved, gold, 3) == 1


def test_precision_at_k_uses_k_denominator():
    gold = [src("a.md", "A")]
    retrieved = [src("a.md", "A")]
    assert precision_at_k(retrieved, gold, 3) == 1 / 3


def test_mrr():
    gold = [src("a.md", "A")]
    retrieved = [src("x.md", "X"), src("a.md", "A")]
    assert mrr(retrieved, gold) == 0.5


def test_ndcg_at_k_binary_relevance():
    gold = [src("a.md", "A")]
    ideal = [src("a.md", "A"), src("x.md", "X")]
    delayed = [src("x.md", "X"), src("a.md", "A")]
    assert ndcg_at_k(ideal, gold, 2) == 1.0
    assert 0 < ndcg_at_k(delayed, gold, 2) < 1.0


def test_empty_gold_returns_none_for_ordinary_metrics():
    assert hit_at_k([src("a.md", "A")], [], 1) is None
    assert recall_at_k([src("a.md", "A")], [], 1) is None
    assert coverage_at_k([src("a.md", "A")], [], 1) is None
    assert precision_at_k([src("a.md", "A")], [], 1) is None
    assert mrr([src("a.md", "A")], []) is None
    assert ndcg_at_k([src("a.md", "A")], [], 1) is None
