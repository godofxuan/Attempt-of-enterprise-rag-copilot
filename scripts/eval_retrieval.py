try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import json
from collections import defaultdict
from pathlib import Path
from pprint import pprint

from app.retriever import hybrid_search


BASE_DIR = Path(__file__).resolve().parent.parent
EVAL_PATH = BASE_DIR / "data" / "eval_questions.json"
OUTPUT_PATH = BASE_DIR / "data" / "eval_retrieval_results.json"

RETURN_K = 5


def source_key(item: dict) -> tuple[str, str]:
    return item["source"], item["section"]


def evaluate_one_question(question_item: dict) -> dict:
    question = question_item["question"]
    qtype = question_item["type"]
    gold_sources = question_item["gold_sources"]

    retrieved = hybrid_search(question=question, top_k=RETURN_K)

    gold_keys = {source_key(item) for item in gold_sources}
    retrieved_keys = [source_key(item) for item in retrieved]

    hit_1 = int(len(retrieved_keys) >= 1 and retrieved_keys[0] in gold_keys)
    hit_3 = int(any(key in gold_keys for key in retrieved_keys[:3]))

    first_match_rank = None
    for rank, key in enumerate(retrieved_keys, start=1):
        if key in gold_keys:
            first_match_rank = rank
            break

    return {
        "id": question_item["id"],
        "question": question,
        "type": qtype,
        "gold_sources": gold_sources,
        "retrieved_sources": [
            {
                "rank": i + 1,
                "source": item["source"],
                "section": item["section"],
                "chunk_id": item["chunk_id"],
                "score": item["score"],
                "preview": item["text"][:120],
            }
            for i, item in enumerate(retrieved)
        ],
        "hit_1": hit_1,
        "hit_3": hit_3,
        "first_match_rank": first_match_rank,
    }


def summarize(results: list[dict]) -> dict:
    overall = {
        "count": len(results),
        "hit_1": sum(item["hit_1"] for item in results),
        "hit_3": sum(item["hit_3"] for item in results),
    }

    overall["hit_1_rate"] = overall["hit_1"] / overall["count"] if overall["count"] else 0.0
    overall["hit_3_rate"] = overall["hit_3"] / overall["count"] if overall["count"] else 0.0

    by_type_raw = defaultdict(lambda: {"count": 0, "hit_1": 0, "hit_3": 0})

    for item in results:
        stats = by_type_raw[item["type"]]
        stats["count"] += 1
        stats["hit_1"] += item["hit_1"]
        stats["hit_3"] += item["hit_3"]

    by_type = {}
    for qtype, stats in by_type_raw.items():
        count = stats["count"]
        by_type[qtype] = {
            "count": count,
            "hit_1": stats["hit_1"],
            "hit_3": stats["hit_3"],
            "hit_1_rate": stats["hit_1"] / count if count else 0.0,
            "hit_3_rate": stats["hit_3"] / count if count else 0.0,
        }

    return {
        "overall": overall,
        "by_type": by_type,
    }


def main() -> None:
    with open(EVAL_PATH, "r", encoding="utf-8") as f:
        questions = json.load(f)

    results = [evaluate_one_question(item) for item in questions]
    summary = summarize(results)

    output = {
        "summary": summary,
        "results": results,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("===== Overall Summary =====")
    pprint(summary["overall"])
    print()

    print("===== By Type Summary =====")
    pprint(summary["by_type"])
    print()

    print(f"详细结果已保存到: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()