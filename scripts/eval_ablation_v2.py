try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np

from app.config import get_settings
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


def source_key(item: dict[str, Any]) -> tuple[str, str]:
    return item.get("source", ""), item.get("section", "")


def compute_metrics(gold_sources: list[dict[str, Any]], retrieved: list[dict[str, Any]], top_k: int) -> dict[str, float]:
    gold_keys = {source_key(s) for s in gold_sources}
    retrieved_keys = [source_key(r) for r in retrieved]
    out: dict[str, float] = {}
    for k in (1, 3, top_k):
        top = retrieved_keys[:k]
        out[f"hit@{k}"] = float(any(x in gold_keys for x in top)) if gold_keys else 0.0
        out[f"recall@{k}"] = float(len(set(top) & gold_keys) / len(gold_keys)) if gold_keys else 0.0
        out[f"coverage@{k}"] = float(gold_keys.issubset(set(top))) if gold_keys else 0.0
    rank = next((i for i, x in enumerate(retrieved_keys, start=1) if x in gold_keys), None)
    out["mrr"] = 1.0 / rank if rank else 0.0
    return out


def dense_search(question: str, top_k: int, candidate_k: int, faiss_index, chunks) -> list[dict[str, Any]]:
    settings = get_settings()
    q_emb = _embed_text(settings.embedding_model, question)
    q_vec = _l2_normalize(np.array([q_emb], dtype="float32"))
    scores, indices = faiss_index.search(q_vec, max(top_k, candidate_k))
    results = []
    for idx, score in zip(indices[0].tolist(), scores[0].tolist()):
        if idx == -1:
            continue
        item = dict(chunks[idx])
        item["score"] = float(score)
        results.append(item)
        if len(results) >= top_k:
            break
    return results


def bm25_search(question: str, top_k: int, bm25, chunks) -> list[dict[str, Any]]:
    scores = bm25.get_scores(tokenize_for_bm25(question))
    ranked = np.argsort(scores)[::-1][:top_k].tolist()
    return [{**chunks[idx], "score": float(scores[idx])} for idx in ranked]


def hybrid_rrf_search(question: str, top_k: int, candidate_k: int, faiss_index, bm25, chunks) -> list[dict[str, Any]]:
    settings = get_settings()
    q_emb = _embed_text(settings.embedding_model, question)
    q_vec = _l2_normalize(np.array([q_emb], dtype="float32"))
    _, dense_indices = faiss_index.search(q_vec, candidate_k)
    dense_indices = dense_indices[0].tolist()

    sparse_scores = bm25.get_scores(tokenize_for_bm25(question))
    sparse_ranked = np.argsort(sparse_scores)[::-1][:candidate_k].tolist()

    rrf_k = 60
    fused: dict[int, float] = {}
    for rank, idx in enumerate(dense_indices, start=1):
        if idx != -1:
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (rrf_k + rank)
    for rank, idx in enumerate(sparse_ranked, start=1):
        fused[idx] = fused.get(idx, 0.0) + 1.0 / (rrf_k + rank)

    ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [{**chunks[idx], "score": float(score)} for idx, score in ranked]


def load_questions(split: str) -> list[dict[str, Any]]:
    path = EVAL_DIR / SPLIT_TO_FILE[split]
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def run_method(name: str, questions: list[dict[str, Any]], top_k: int, candidate_k: int, faiss_index, bm25, chunks) -> dict[str, Any]:
    rows = []
    for q in questions:
        start = time.perf_counter()
        if name == "bm25_only":
            retrieved = bm25_search(q["question"], top_k, bm25, chunks)
        elif name == "dense_only":
            retrieved = dense_search(q["question"], top_k, candidate_k, faiss_index, chunks)
        elif name == "hybrid_rrf":
            retrieved = hybrid_rrf_search(q["question"], top_k, candidate_k, faiss_index, bm25, chunks)
        else:
            raise ValueError(name)
        latency_ms = (time.perf_counter() - start) * 1000
        rows.append({
            "id": q["id"],
            "type": q.get("type"),
            "latency_ms": latency_ms,
            "retrieved_sources": [
                {"rank": i, "source": r.get("source"), "section": r.get("section"), "score": r.get("score")}
                for i, r in enumerate(retrieved, start=1)
            ],
            **compute_metrics(q.get("gold_sources", []), retrieved, top_k),
        })
    metrics = ["hit@1", "hit@3", f"hit@{top_k}", f"recall@{top_k}", f"coverage@{top_k}", "mrr"]
    latencies = [r["latency_ms"] for r in rows]
    summary = {"method": name, "count": len(rows)}
    for m in metrics:
        summary[m] = mean([float(r[m]) for r in rows])
    summary["latency_ms_avg"] = mean(latencies)
    summary["latency_ms_p50"] = statistics.median(latencies) if latencies else 0.0
    return {"summary": summary, "results": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare BM25 only, Dense only, and Hybrid RRF retrieval.")
    parser.add_argument("--split", choices=sorted(SPLIT_TO_FILE), default="test")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=None)
    args = parser.parse_args()

    settings = get_settings()
    candidate_k = args.candidate_k or settings.retrieval_candidate_k
    questions = [q for q in load_questions(args.split) if q.get("answerable", True) and q.get("gold_sources")]
    faiss_index, bm25, chunks = load_indexes()

    methods = ["bm25_only", "dense_only", "hybrid_rrf"]
    report = {name: run_method(name, questions, args.top_k, candidate_k, faiss_index, bm25, chunks) for name in methods}
    table = [report[name]["summary"] for name in methods]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"ablation_{args.split}_results.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump({"summary_table": table, "methods": report}, f, ensure_ascii=False, indent=2)

    print(json.dumps(table, ensure_ascii=False, indent=2))
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
