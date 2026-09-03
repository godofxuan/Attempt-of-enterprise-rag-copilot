from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

import numpy as np

from app.config import get_settings
from app.external_datasets.wixqa import (
    DEFAULT_WIXQA_MANIFEST,
    DEFAULT_WIXQA_ROOT,
    load_wixqa_questions,
    question_ids_sha256,
    verify_wixqa_source,
)
from app.external_datasets.wixqa_retrieval import load_wixqa_flat_index
from app.runtime.model_transport import ModelRequestError
from app.runtime.ollama_embeddings import OllamaEmbeddingClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export fixed WixQA dense article candidates through top 50."
    )
    parser.add_argument("--source-root", type=Path, default=DEFAULT_WIXQA_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_WIXQA_MANIFEST)
    parser.add_argument(
        "--index-root",
        type=Path,
        default=Path(".private/external/wixqa/indexes"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-k", type=int, default=200)
    parser.add_argument("--article-depth", type=int, default=50)
    parser.add_argument(
        "--chunk-depth",
        type=int,
        default=0,
        help="Also retain this many raw dense chunks before article deduplication.",
    )
    parser.add_argument("--embedding-http-500-fallback-url")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if (
        args.candidate_k < max(args.article_depth, args.chunk_depth)
        or args.article_depth < 50
        or args.chunk_depth < 0
    ):
        raise SystemExit("candidate-k must cover an article-depth of at least 50 and chunk-depth")
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"candidate output already exists: {output}")

    verify_wixqa_source(args.source_root, args.manifest)
    questions = load_wixqa_questions("expertwritten", args.source_root)
    index = load_wixqa_flat_index(args.index_root)
    dataset_manifest_sha256 = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    if index.manifest.dataset_manifest_sha256 != dataset_manifest_sha256:
        raise ValueError("WixQA index does not match dataset manifest")

    settings = get_settings()
    client = OllamaEmbeddingClient.from_settings(
        settings,
        probe_text="WixQA dense candidate export dimension probe",
        endpoint_context="WixQA dense candidate export",
    )
    fallback = None
    if args.embedding_http_500_fallback_url:
        fallback = OllamaEmbeddingClient.from_settings(
            settings.model_copy(update={"llm_base_url": args.embedding_http_500_fallback_url}),
            probe_text="WixQA dense candidate fallback dimension probe",
            endpoint_context="WixQA dense candidate export fallback",
        )
    for candidate in (client, fallback):
        if candidate is not None and (
            candidate.model_identifier != index.manifest.embedding_model
            or candidate.model_sha256 != index.manifest.embedding_model_sha256
            or candidate.dimension != index.manifest.embedding_dimension
        ):
            raise ValueError("WixQA candidate embedding identity differs from index")

    rows: list[dict[str, object]] = []
    fallback_count = 0
    latencies: list[float] = []
    for ordinal, question in enumerate(questions, start=1):
        started = time.perf_counter()
        try:
            query_vector = client.embed_batch([question.question])
        except ModelRequestError as exc:
            if exc.status_code != 500 or fallback is None:
                raise
            fallback_count += 1
            print(
                f"query {ordinal} primary embedding HTTP 500; using fallback",
                flush=True,
            )
            query_vector = fallback.embed_batch([question.question])
        candidates, chunk_candidates = _candidate_views(
            index=index,
            query_vector=query_vector,
            chunk_candidate_k=args.candidate_k,
            article_depth=args.article_depth,
            chunk_depth=args.chunk_depth,
        )
        latencies.append((time.perf_counter() - started) * 1000.0)
        if len(candidates) < args.article_depth:
            raise ValueError(
                f"query {question.question_id} produced only {len(candidates)} unique articles"
            )
        rows.append(
            {
                "question_id": question.question_id,
                "question": question.question,
                "gold_article_ids": question.article_ids,
                "candidates": candidates,
                "chunk_candidates": chunk_candidates,
            }
        )
        if ordinal in {1, len(questions)} or ordinal % 25 == 0:
            print(f"exported {ordinal}/{len(questions)}", flush=True)

    cutoffs = (5, 10, 20, 50)
    recall = {f"article_recall_at_{cutoff}": _mean_recall(rows, cutoff) for cutoff in cutoffs}
    chunk_cutoffs = tuple(
        cutoff for cutoff in (5, 10, 20, 50, 100, 200) if cutoff <= args.chunk_depth
    )
    chunk_capacity = {
        f"raw_chunk_article_recall_at_{cutoff}": _mean_chunk_article_recall(rows, cutoff)
        for cutoff in chunk_cutoffs
    }
    chunk_unique_articles = {
        str(cutoff): _unique_article_count_summary(rows, cutoff) for cutoff in chunk_cutoffs
    }
    payload = {
        "schema_version": "wixqa_dense_candidates_v1",
        "code_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, encoding="utf-8"
        ).strip(),
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "question_ids_sha256": question_ids_sha256(questions),
        "case_count": len(rows),
        "index_run_id": index.manifest.run_id,
        "embedding_model": client.model_identifier,
        "embedding_model_sha256": client.model_sha256,
        "chunk_candidate_k": args.candidate_k,
        "article_depth": args.article_depth,
        "chunk_depth": args.chunk_depth,
        "embedding_http_500_fallback_count": fallback_count,
        "dense_metrics": recall,
        "raw_chunk_candidate_metrics": chunk_capacity,
        "raw_chunk_unique_article_counts": chunk_unique_articles,
        "dense_latency_ms": _latency_summary(latencies),
        "cases": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    content = (
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    output.write_bytes(content)
    print(
        json.dumps(
            {
                "output": str(output),
                "sha256": hashlib.sha256(content).hexdigest(),
                "fallback_count": fallback_count,
                **recall,
                **chunk_capacity,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _candidate_views(
    *,
    index,
    query_vector,
    chunk_candidate_k: int,
    article_depth: int,
    chunk_depth: int,
):
    vector = np.ascontiguousarray(query_vector, dtype="float32")
    norms = np.linalg.norm(vector, axis=1, keepdims=True)
    if vector.shape != (1, index.manifest.embedding_dimension) or np.any(norms == 0):
        raise ValueError("invalid WixQA query vector")
    vector = vector / norms
    scores, indices = index.faiss_index.search(vector, chunk_candidate_k)
    article_rows = []
    chunk_rows = []
    seen: set[str] = set()
    for chunk_rank, (score, raw_index) in enumerate(
        zip(scores[0], indices[0], strict=True), start=1
    ):
        chunk_index = int(raw_index)
        if chunk_index < 0:
            continue
        chunk = index.chunks[chunk_index]
        if len(chunk_rows) < chunk_depth:
            chunk_rows.append(
                {
                    "article_id": chunk.article_id,
                    "chunk_id": chunk.chunk_id,
                    "text": chunk.text,
                    "dense_chunk_rank": chunk_rank,
                    "dense_score": float(score),
                }
            )
        if chunk.article_id in seen:
            continue
        seen.add(chunk.article_id)
        if len(article_rows) < article_depth:
            article_rows.append(
                {
                    "article_id": chunk.article_id,
                    "chunk_id": chunk.chunk_id,
                    "text": chunk.text,
                    "dense_article_rank": len(article_rows) + 1,
                    "dense_chunk_rank": chunk_rank,
                    "dense_score": float(score),
                }
            )
        if len(article_rows) == article_depth and len(chunk_rows) == chunk_depth:
            break
    return article_rows, chunk_rows


def _mean_recall(rows: list[dict[str, object]], cutoff: int) -> float:
    values = []
    for row in rows:
        gold = set(row["gold_article_ids"])
        candidates = row["candidates"]
        ranked = [item["article_id"] for item in candidates[:cutoff]]
        values.append(len(gold.intersection(ranked)) / len(gold))
    return sum(values) / len(values)


def _mean_chunk_article_recall(rows: list[dict[str, object]], cutoff: int) -> float:
    values = []
    for row in rows:
        gold = set(row["gold_article_ids"])
        ranked = _unique_chunk_article_ids(row["chunk_candidates"], cutoff)
        values.append(len(gold.intersection(ranked)) / len(gold))
    return sum(values) / len(values)


def _unique_article_count_summary(
    rows: list[dict[str, object]], cutoff: int
) -> dict[str, float | int]:
    counts = sorted(len(_unique_chunk_article_ids(row["chunk_candidates"], cutoff)) for row in rows)
    return {
        "mean": sum(counts) / len(counts),
        "min": counts[0],
        "p50": counts[int(0.50 * (len(counts) - 1))],
        "p95": counts[int(0.95 * (len(counts) - 1))],
        "max": counts[-1],
    }


def _unique_chunk_article_ids(candidates, cutoff: int) -> list[str]:
    return list(dict.fromkeys(item["article_id"] for item in candidates[:cutoff]))


def _latency_summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "mean": sum(ordered) / len(ordered),
        "p50": ordered[int(0.50 * (len(ordered) - 1))],
        "p95": ordered[int(0.95 * (len(ordered) - 1))],
    }


if __name__ == "__main__":
    raise SystemExit(main())
