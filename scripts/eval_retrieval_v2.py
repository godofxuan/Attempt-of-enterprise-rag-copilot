try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import csv
import json
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.eval_metrics import mean_metric, retrieval_metrics
from app.retriever import hybrid_search

BASE_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = BASE_DIR / "data" / "eval"
OUT_DIR = BASE_DIR / "data" / "eval_outputs"

SPLIT_TO_FILE = {
    "dev": "retrieval_dev.json",
    "test": "retrieval_test.json",
    "all": "rag_eval_questions.json",
}

METRIC_NAMES = [
    "hit@1",
    "hit@3",
    "hit@5",
    "recall@5",
    "coverage@5",
    "precision@3",
    "precision@5",
    "mrr",
    "ndcg@3",
    "ndcg@5",
]


def load_questions(split: str) -> list[dict[str, Any]]:
    path = EVAL_DIR / SPLIT_TO_FILE[split]
    if not path.exists():
        raise FileNotFoundError(f"Eval file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def should_score_retrieval(item: dict[str, Any], include_no_answer: bool) -> bool:
    if include_no_answer:
        return bool(item.get("gold_sources"))
    return item.get("answerable", True) is True and bool(item.get("gold_sources"))


def retrieved_source_view(retrieved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "rank": rank,
            "source": item.get("source"),
            "section": item.get("section"),
            "chunk_id": item.get("chunk_id"),
            "score": item.get("score"),
            "preview": item.get("text", "")[:160],
        }
        for rank, item in enumerate(retrieved, start=1)
    ]


def evaluate_one(item: dict[str, Any], top_k: int) -> dict[str, Any]:
    start = time.perf_counter()
    retrieved = hybrid_search(question=item["question"], top_k=max(top_k, 5))
    latency_ms = (time.perf_counter() - start) * 1000
    retrieved_sources = retrieved_source_view(retrieved[:top_k])
    metric_sources = retrieved_source_view(retrieved)
    q_metrics = retrieval_metrics(metric_sources, item.get("gold_sources", []))

    return {
        "id": item["id"],
        "question": item["question"],
        "type": item.get("type"),
        "difficulty": item.get("difficulty"),
        "answerable": item.get("answerable", True),
        "gold_sources": item.get("gold_sources", []),
        "retrieved_sources": retrieved_sources,
        **q_metrics,
        "latency_ms": latency_ms,
    }


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"count": len(rows)}
    for name in METRIC_NAMES:
        summary[name] = mean_metric(rows, name)
    latencies = [float(row["latency_ms"]) for row in rows]
    summary["latency_ms_avg"] = mean(latencies)
    summary["latency_ms_p50"] = statistics.median(latencies) if latencies else 0.0
    summary["latency_ms_p95"] = (
        sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]
        if latencies
        else 0.0
    )
    return summary


def grouped_summary(rows: list[dict[str, Any]], group_key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(group_key) or "unknown")].append(row)
    return {key: summarize_rows(group_rows) for key, group_rows in sorted(grouped.items())}


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_group_csv(path: Path, summary: dict[str, dict[str, Any]], group_name: str) -> None:
    fieldnames = [
        group_name,
        "count",
        "hit@1",
        "hit@3",
        "hit@5",
        "recall@5",
        "coverage@5",
        "precision@5",
        "mrr",
        "ndcg@5",
        "latency_ms_avg",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for key, stats in summary.items():
            writer.writerow({group_name: key, **{name: stats.get(name) for name in fieldnames[1:]}})


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality on the enterprise RAG golden set.")
    parser.add_argument("--split", choices=sorted(SPLIT_TO_FILE), default="test")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--include-no-answer",
        action="store_true",
        help="Include questions with gold sources even if answerable=false. Default: skip unanswerable questions.",
    )
    args = parser.parse_args()

    questions = [
        item
        for item in load_questions(args.split)
        if should_score_retrieval(item, args.include_no_answer)
    ]
    rows = [evaluate_one(item, top_k=args.top_k) for item in questions]

    overall = summarize_rows(rows)
    by_type = grouped_summary(rows, "type")
    by_difficulty = grouped_summary(rows, "difficulty")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results_path = OUT_DIR / f"retrieval_{args.split}_results.json"
    details_path = OUT_DIR / f"retrieval_{args.split}_details.jsonl"
    by_type_json_path = OUT_DIR / f"retrieval_{args.split}_by_type.json"
    by_type_csv_path = OUT_DIR / f"retrieval_{args.split}_by_type.csv"
    by_difficulty_csv_path = OUT_DIR / f"retrieval_{args.split}_by_difficulty.csv"

    with results_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "summary": overall,
                "by_type": by_type,
                "by_difficulty": by_difficulty,
                "config": {"split": args.split, "top_k": args.top_k},
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    write_jsonl(details_path, rows)
    with by_type_json_path.open("w", encoding="utf-8") as f:
        json.dump(by_type, f, ensure_ascii=False, indent=2)
    write_group_csv(by_type_csv_path, by_type, "type")
    write_group_csv(by_difficulty_csv_path, by_difficulty, "difficulty")

    print(json.dumps(overall, ensure_ascii=False, indent=2))
    print(f"Saved: {results_path}")
    print(f"Saved: {details_path}")
    print(f"Saved: {by_type_csv_path}")
    print(f"Saved: {by_difficulty_csv_path}")


if __name__ == "__main__":
    main()
