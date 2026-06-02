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

import numpy as np

from app.config import get_settings
from app.eval_metrics import mean_metric, retrieval_metrics
from app.retriever import _embed_text, _l2_normalize, load_indexes
from app.utils import tokenize_for_bm25

BASE_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = BASE_DIR / "data" / "eval"
OUT_DIR = BASE_DIR / "data" / "eval_outputs"
SPLIT_TO_FILE = {
    "dev": "retrieval_dev.json",
    "test": "retrieval_test.json",
    "all": "rag_eval_questions.json",
}

METHODS = [
    "bm25_only",
    "dense_only",
    "concat_union",
    "weighted_score_fusion",
    "rrf_fusion",
]

SUMMARY_FIELDS = [
    "method",
    "count",
    "hit@1",
    "hit@3",
    "hit@5",
    "recall@5",
    "coverage@5",
    "precision@5",
    "mrr",
    "ndcg@3",
    "ndcg@5",
    "latency_ms_avg",
]


def load_questions(split: str) -> list[dict[str, Any]]:
    path = EVAL_DIR / SPLIT_TO_FILE[split]
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def minmax(scores: dict[int, float]) -> dict[int, float]:
    if not scores:
        return {}
    values = list(scores.values())
    lo, hi = min(values), max(values)
    if hi == lo:
        return {idx: 1.0 for idx in scores}
    return {idx: (score - lo) / (hi - lo) for idx, score in scores.items()}


def chunk_view(
    idx: int,
    chunks: list[dict[str, Any]],
    score: float,
    dense_score: float | None = None,
    bm25_score: float | None = None,
) -> dict[str, Any]:
    item = dict(chunks[idx])
    item["score"] = float(score)
    if dense_score is not None:
        item["dense_score"] = float(dense_score)
    if bm25_score is not None:
        item["bm25_score"] = float(bm25_score)
    return item


def ranked_inputs(question: str, candidate_k: int, faiss_index, bm25, chunks) -> dict[str, Any]:
    settings = get_settings()
    dense_start = time.perf_counter()
    query_embedding = _embed_text(settings.embedding_model, question)
    query_vector = _l2_normalize(np.array([query_embedding], dtype="float32"))
    dense_scores, dense_indices = faiss_index.search(query_vector, candidate_k)
    dense_latency_ms = (time.perf_counter() - dense_start) * 1000

    dense_ranked = [
        idx
        for idx in dense_indices[0].tolist()
        if idx != -1
    ]
    dense_score_map = {
        idx: float(score)
        for idx, score in zip(dense_indices[0].tolist(), dense_scores[0].tolist())
        if idx != -1
    }

    bm25_start = time.perf_counter()
    bm25_scores = bm25.get_scores(tokenize_for_bm25(question))
    bm25_ranked = np.argsort(bm25_scores)[::-1][:candidate_k].tolist()
    bm25_score_map = {idx: float(bm25_scores[idx]) for idx in bm25_ranked}
    bm25_latency_ms = (time.perf_counter() - bm25_start) * 1000

    return {
        "dense_ranked": dense_ranked,
        "dense_scores": dense_score_map,
        "bm25_ranked": bm25_ranked,
        "bm25_scores": bm25_score_map,
        "dense_latency_ms": dense_latency_ms,
        "bm25_latency_ms": bm25_latency_ms,
        "chunks": chunks,
    }


def bm25_only(inputs: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
    return [
        chunk_view(idx, inputs["chunks"], inputs["bm25_scores"][idx], bm25_score=inputs["bm25_scores"][idx])
        for idx in inputs["bm25_ranked"][:top_k]
    ]


def dense_only(inputs: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
    return [
        chunk_view(idx, inputs["chunks"], inputs["dense_scores"][idx], dense_score=inputs["dense_scores"][idx])
        for idx in inputs["dense_ranked"][:top_k]
    ]


def concat_union(inputs: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
    ordered: list[int] = []
    seen: set[int] = set()
    for idx in inputs["dense_ranked"][:top_k] + inputs["bm25_ranked"][:top_k]:
        if idx in seen:
            continue
        ordered.append(idx)
        seen.add(idx)
        if len(ordered) >= top_k:
            break
    return [
        chunk_view(
            idx,
            inputs["chunks"],
            float(len(ordered) - rank),
            dense_score=inputs["dense_scores"].get(idx),
            bm25_score=inputs["bm25_scores"].get(idx),
        )
        for rank, idx in enumerate(ordered)
    ]


def weighted_score_fusion(inputs: dict[str, Any], top_k: int, alpha: float) -> list[dict[str, Any]]:
    dense_norm = minmax(inputs["dense_scores"])
    bm25_norm = minmax(inputs["bm25_scores"])
    candidate_ids = set(dense_norm) | set(bm25_norm)
    fused = {
        idx: alpha * dense_norm.get(idx, 0.0) + (1 - alpha) * bm25_norm.get(idx, 0.0)
        for idx in candidate_ids
    }
    ranked = sorted(
        fused,
        key=lambda idx: (
            fused[idx],
            dense_norm.get(idx, 0.0),
            bm25_norm.get(idx, 0.0),
        ),
        reverse=True,
    )[:top_k]
    return [
        chunk_view(
            idx,
            inputs["chunks"],
            fused[idx],
            dense_score=inputs["dense_scores"].get(idx),
            bm25_score=inputs["bm25_scores"].get(idx),
        )
        for idx in ranked
    ]


def rrf_fusion(inputs: dict[str, Any], top_k: int, rrf_k: int) -> list[dict[str, Any]]:
    fused: dict[int, float] = {}
    for rank, idx in enumerate(inputs["dense_ranked"], start=1):
        fused[idx] = fused.get(idx, 0.0) + 1.0 / (rrf_k + rank)
    for rank, idx in enumerate(inputs["bm25_ranked"], start=1):
        fused[idx] = fused.get(idx, 0.0) + 1.0 / (rrf_k + rank)
    ranked = sorted(fused, key=lambda idx: fused[idx], reverse=True)[:top_k]
    return [
        chunk_view(
            idx,
            inputs["chunks"],
            fused[idx],
            dense_score=inputs["dense_scores"].get(idx),
            bm25_score=inputs["bm25_scores"].get(idx),
        )
        for idx in ranked
    ]


def run_method(
    method: str,
    inputs: dict[str, Any],
    top_k: int,
    alpha: float,
    rrf_k: int,
) -> list[dict[str, Any]]:
    if method == "bm25_only":
        return bm25_only(inputs, top_k)
    if method == "dense_only":
        return dense_only(inputs, top_k)
    if method == "concat_union":
        return concat_union(inputs, top_k)
    if method == "weighted_score_fusion":
        return weighted_score_fusion(inputs, top_k, alpha)
    if method == "rrf_fusion":
        return rrf_fusion(inputs, top_k, rrf_k)
    raise ValueError(method)


def base_latency_ms(method: str, inputs: dict[str, Any]) -> float:
    dense_latency = float(inputs["dense_latency_ms"])
    bm25_latency = float(inputs["bm25_latency_ms"])
    if method == "bm25_only":
        return bm25_latency
    if method == "dense_only":
        return dense_latency
    return dense_latency + bm25_latency


def retrieved_source_view(retrieved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "rank": rank,
            "source": item.get("source"),
            "section": item.get("section"),
            "chunk_id": item.get("chunk_id"),
            "score": item.get("score"),
            "dense_score": item.get("dense_score"),
            "bm25_score": item.get("bm25_score"),
        }
        for rank, item in enumerate(retrieved, start=1)
    ]


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize(method: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"method": method, "count": len(rows)}
    for name in SUMMARY_FIELDS[2:-1]:
        summary[name] = mean_metric(rows, name)
    summary["latency_ms_avg"] = mean([float(row["latency_ms"]) for row in rows])
    return summary


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare retrieval fusion strategies.")
    parser.add_argument("--split", choices=sorted(SPLIT_TO_FILE), default="test")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=None)
    parser.add_argument("--alpha", type=float, default=0.5)
    parser.add_argument("--rrf-k", type=int, default=60)
    args = parser.parse_args()

    settings = get_settings()
    candidate_k = args.candidate_k or max(settings.retrieval_candidate_k, args.top_k, 5)
    questions = [
        item
        for item in load_questions(args.split)
        if item.get("answerable", True) is True and item.get("gold_sources")
    ]
    faiss_index, bm25, chunks = load_indexes()

    all_details: list[dict[str, Any]] = []
    method_rows: dict[str, list[dict[str, Any]]] = {method: [] for method in METHODS}

    for item in questions:
        inputs = ranked_inputs(item["question"], candidate_k, faiss_index, bm25, chunks)
        for method in METHODS:
            start = time.perf_counter()
            retrieved = run_method(method, inputs, args.top_k, args.alpha, args.rrf_k)
            latency_ms = base_latency_ms(method, inputs) + (time.perf_counter() - start) * 1000
            row = {
                "method": method,
                "id": item["id"],
                "question": item["question"],
                "type": item.get("type"),
                "difficulty": item.get("difficulty"),
                "answerable": item.get("answerable", True),
                "gold_sources": item.get("gold_sources", []),
                "retrieved_sources": retrieved_source_view(retrieved),
                **retrieval_metrics(retrieved, item.get("gold_sources", [])),
                "latency_ms": latency_ms,
            }
            method_rows[method].append(row)
            all_details.append(row)

    summary_table = [summarize(method, method_rows[method]) for method in METHODS]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results_path = OUT_DIR / f"fusion_ablation_{args.split}_results.json"
    details_path = OUT_DIR / f"fusion_ablation_{args.split}_details.jsonl"
    summary_path = OUT_DIR / f"fusion_ablation_{args.split}_summary.csv"

    with results_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "summary_table": summary_table,
                "config": {
                    "split": args.split,
                    "top_k": args.top_k,
                    "candidate_k": candidate_k,
                    "alpha": args.alpha,
                    "rrf_k": args.rrf_k,
                    "note": "weighted_score_fusion uses per-query min-max normalized dense and BM25 scores; it is an experimental baseline.",
                },
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    write_jsonl(details_path, all_details)
    write_summary_csv(summary_path, summary_table)

    print(json.dumps(summary_table, ensure_ascii=False, indent=2))
    print(f"Saved: {results_path}")
    print(f"Saved: {details_path}")
    print(f"Saved: {summary_path}")


if __name__ == "__main__":
    main()
