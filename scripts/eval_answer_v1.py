try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

from app.eval_metrics import (
    citation_metrics,
    classify_error_type,
    missing_must_include,
    must_include_rate,
    refusal_ok,
    unsafe_answer,
    violated_must_not_include,
)
from app.rag_service import answer_question

BASE_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = BASE_DIR / "data" / "eval"
OUT_DIR = BASE_DIR / "data" / "eval_outputs"
SPLIT_TO_FILE = {
    "dev": "answer_dev.json",
    "test": "answer_test.json",
    "adversarial": "adversarial_test.json",
}

ERROR_ANALYSIS_FIELDS = [
    "id",
    "type",
    "question",
    "error_type",
    "must_include_rate",
    "missing_must_include",
    "violated_must_not_include",
    "gold_sources",
    "retrieved_sources",
    "cited_sources",
    "model_answer",
    "gold_answer",
]


def load_questions(split: str) -> list[dict[str, Any]]:
    if split == "all":
        rows: list[dict[str, Any]] = []
        for file_name in SPLIT_TO_FILE.values():
            with (EVAL_DIR / file_name).open("r", encoding="utf-8") as f:
                rows.extend(json.load(f))
        return rows
    with (EVAL_DIR / SPLIT_TO_FILE[split]).open("r", encoding="utf-8") as f:
        return json.load(f)


def source_view(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source": item.get("source"),
            "section": item.get("section"),
            "chunk_id": item.get("chunk_id"),
            "score": item.get("score"),
            "preview": item.get("preview") or item.get("text", "")[:160],
        }
        for item in sources
    ]


def evaluate_one(item: dict[str, Any], top_k: int) -> dict[str, Any]:
    start = time.perf_counter()
    response = answer_question(item["question"], top_k=top_k)
    latency_ms = (time.perf_counter() - start) * 1000

    model_answer = response.get("answer", "")
    retrieved_sources = source_view(response.get("sources", []))
    cited_sources = retrieved_sources
    must_include = item.get("must_include", [])
    must_not_include = item.get("must_not_include", [])

    missing = missing_must_include(model_answer, must_include)
    include_rate = must_include_rate(model_answer, must_include)
    violations = violated_must_not_include(model_answer, must_not_include)
    must_not_include_ok = int(len(violations) == 0)
    citation_hit, citation_coverage = citation_metrics(
        item.get("gold_sources", []), cited_sources
    )

    qtype = item.get("type")
    answerable = item.get("answerable") is True
    should_refuse = (not answerable) or qtype in {"no_answer", "adversarial"}
    refusal_ok_value = refusal_ok(model_answer) if should_refuse else None
    unsafe_value = unsafe_answer(model_answer) if qtype == "adversarial" else False
    error_type = classify_error_type(
        answerable=answerable,
        qtype=qtype,
        refusal_ok_value=bool(refusal_ok_value),
        unsafe_answer_value=unsafe_value,
        violated_must_not_include_value=violations,
        retrieved_sources=retrieved_sources,
        cited_sources=cited_sources,
        gold_sources=item.get("gold_sources", []),
        must_include_rate_value=include_rate,
    )

    return {
        "id": item["id"],
        "question": item["question"],
        "type": qtype,
        "answerable": item.get("answerable"),
        "gold_answer": item.get("gold_answer"),
        "model_answer": model_answer,
        "gold_sources": item.get("gold_sources", []),
        "retrieved_sources": retrieved_sources,
        "cited_sources": cited_sources,
        "must_include": must_include,
        "missing_must_include": missing,
        "must_include_rate": include_rate,
        "must_not_include": must_not_include,
        "violated_must_not_include": violations,
        "must_not_include_ok": must_not_include_ok,
        "citation_hit": citation_hit,
        "citation_coverage": citation_coverage,
        "refusal_ok": refusal_ok_value,
        "unsafe_answer": unsafe_value,
        "latency_ms": latency_ms,
        "error_type": error_type,
    }


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [row for row in rows if row.get("answerable") is True]
    should_refuse = [
        row
        for row in rows
        if row.get("answerable") is False or row.get("type") in {"no_answer", "adversarial"}
    ]
    return {
        "count": len(rows),
        "answerable_count": len(answerable),
        "no_answer_count": sum(1 for row in rows if row.get("type") == "no_answer"),
        "adversarial_count": sum(1 for row in rows if row.get("type") == "adversarial"),
        "must_include_rate_avg": mean([float(row["must_include_rate"]) for row in answerable]),
        "must_not_include_ok_rate": mean([float(row["must_not_include_ok"]) for row in rows]),
        "citation_hit_rate": mean([float(row["citation_hit"]) for row in answerable]),
        "citation_coverage_rate": mean([float(row["citation_coverage"]) for row in answerable]),
        "refusal_accuracy": mean([
            float(row["refusal_ok"])
            for row in should_refuse
            if row.get("refusal_ok") is not None
        ]),
        "latency_ms_avg": mean([float(row["latency_ms"]) for row in rows]),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def csv_value(value: Any) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)


def write_error_analysis(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ERROR_ANALYSIS_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                field: csv_value(row.get(field))
                for field in ERROR_ANALYSIS_FIELDS
            })


def main() -> None:
    parser = argparse.ArgumentParser(description="Run answer/refusal evaluation using the current RAG pipeline.")
    parser.add_argument("--split", choices=["dev", "test", "adversarial", "all"], default="test")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N questions for a quick smoke test.")
    args = parser.parse_args()

    questions = load_questions(args.split)
    if args.limit:
        questions = questions[: args.limit]

    rows = [evaluate_one(item, args.top_k) for item in questions]
    summary = summarize(rows)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results_path = OUT_DIR / f"answer_{args.split}_results.json"
    details_path = OUT_DIR / f"answer_{args.split}_details.jsonl"
    error_path = OUT_DIR / f"answer_{args.split}_error_analysis.csv"

    with results_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "summary": summary,
                "config": {
                    "split": args.split,
                    "top_k": args.top_k,
                    "limit": args.limit,
                },
                "output_files": {
                    "details": str(details_path),
                    "error_analysis": str(error_path),
                },
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    write_jsonl(details_path, rows)
    write_error_analysis(error_path, rows)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Saved: {results_path}")
    print(f"Saved: {details_path}")
    print(f"Saved: {error_path}")


if __name__ == "__main__":
    main()
