import json
import re
from pathlib import Path

from app.eval_metrics import retrieval_metrics

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DOCS_DIR = DATA_DIR / "raw_docs"
EVAL_DIR = DATA_DIR / "eval"
REQUIRED_KEYS = {
    "id",
    "question",
    "type",
    "answerable",
    "gold_answer",
    "gold_sources",
    "must_include",
    "must_not_include",
    "difficulty",
    "tags",
}


def load_json(name: str):
    with (EVAL_DIR / name).open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_sections(text: str) -> set[str]:
    return {m.group(2).strip() for m in re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", text)}


def test_eval_files_exist():
    expected = [
        "rag_eval_questions.json",
        "retrieval_dev.json",
        "retrieval_test.json",
        "answer_dev.json",
        "answer_test.json",
        "adversarial_test.json",
    ]
    for name in expected:
        assert (EVAL_DIR / name).exists(), name


def test_schema_and_unique_ids():
    rows = load_json("rag_eval_questions.json")
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))
    for row in rows:
        assert REQUIRED_KEYS.issubset(row), row.get("id")
        assert isinstance(row["gold_sources"], list)
        assert isinstance(row["must_include"], list)
        assert isinstance(row["must_not_include"], list)
        assert isinstance(row["tags"], list)


def test_split_files_have_required_schema():
    for name in [
        "retrieval_dev.json",
        "retrieval_test.json",
        "answer_dev.json",
        "answer_test.json",
        "adversarial_test.json",
    ]:
        for row in load_json(name):
            assert REQUIRED_KEYS.issubset(row), (name, row.get("id"))


def test_sources_and_sections_exist():
    docs = {p.name: p.read_text(encoding="utf-8") for p in RAW_DOCS_DIR.glob("*.md")}
    sections = {name: parse_sections(text) for name, text in docs.items()}
    for row in load_json("rag_eval_questions.json"):
        for source in row["gold_sources"]:
            src = source["source"]
            assert src in docs, (row["id"], src)
            assert source["section"] in sections[src], (row["id"], src, source["section"])


def test_split_disjointness():
    retrieval_dev = {r["id"] for r in load_json("retrieval_dev.json")}
    retrieval_test = {r["id"] for r in load_json("retrieval_test.json")}
    answer_dev = {r["id"] for r in load_json("answer_dev.json")}
    answer_test = {r["id"] for r in load_json("answer_test.json")}
    assert retrieval_dev.isdisjoint(retrieval_test)
    assert answer_dev.isdisjoint(answer_test)


def test_no_answer_has_no_gold_sources():
    for row in load_json("rag_eval_questions.json"):
        if row["type"] == "no_answer":
            assert row["answerable"] is False
            assert row["gold_sources"] == []


def test_no_answer_is_not_scored_by_retrieval_metrics():
    no_answer_rows = [
        row for row in load_json("rag_eval_questions.json") if row["type"] == "no_answer"
    ]
    assert no_answer_rows
    for row in no_answer_rows:
        metrics = retrieval_metrics(
            [{"source": "any.md", "section": "Any"}],
            row["gold_sources"],
        )
        assert all(value is None for value in metrics.values())
