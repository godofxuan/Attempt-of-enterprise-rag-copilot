from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

from app.config import get_settings
from app.external_datasets.wixqa import (
    DEFAULT_WIXQA_MANIFEST,
    DEFAULT_WIXQA_ROOT,
    load_wixqa_questions,
    question_ids_sha256,
    verify_wixqa_source,
)
from app.external_datasets.wixqa_retrieval import load_wixqa_flat_index
from app.runtime.ollama_embeddings import OllamaEmbeddingClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Freeze WixQA ExpertWritten raw dense candidates for the final Guard ablation."
    )
    parser.add_argument("--source-root", type=Path, default=DEFAULT_WIXQA_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_WIXQA_MANIFEST)
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-k", type=int, default=200)
    return parser


def _latency_summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "mean": sum(ordered) / len(ordered),
        "p50": ordered[int(0.50 * (len(ordered) - 1))],
        "p95": ordered[int(0.95 * (len(ordered) - 1))],
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.candidate_k < 50:
        raise SystemExit("--candidate-k must be at least 50")
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"candidate output already exists: {output}")

    verify_wixqa_source(args.source_root, args.manifest)
    questions = load_wixqa_questions("expertwritten", args.source_root)
    index = load_wixqa_flat_index(args.index_root)
    manifest_sha256 = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    if index.manifest.dataset_manifest_sha256 != manifest_sha256:
        raise ValueError("WixQA index does not match the supplied manifest")

    client = OllamaEmbeddingClient.from_settings(
        get_settings(),
        probe_text="WixQA final raw candidate export probe",
        endpoint_context="WixQA final raw candidate export",
    )
    if (
        client.model_identifier != index.manifest.embedding_model
        or client.model_sha256 != index.manifest.embedding_model_sha256
        or client.dimension != index.manifest.embedding_dimension
    ):
        raise ValueError("query embedding identity differs from the frozen index")

    cases: list[dict[str, object]] = []
    latencies: list[float] = []
    for ordinal, question in enumerate(questions, start=1):
        started = time.perf_counter()
        query_vector = client.embed_batch([question.question])
        raw_rows = index.dense_raw_chunk_candidates(
            query_vector, candidate_k=args.candidate_k, max_chunks=args.candidate_k
        )
        dense_rows = index.dense_article_candidates(query_vector, candidate_k=args.candidate_k)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if len(raw_rows) != args.candidate_k:
            raise ValueError(f"{question.question_id} produced fewer than {args.candidate_k} chunks")
        cases.append(
            {
                "question_id": question.question_id,
                "question": question.question,
                "gold_article_ids": list(question.article_ids),
                "candidate_generation_ms": elapsed_ms,
                "dense_article_ids": [item.article_id for item in dense_rows],
                "raw_candidates": [
                    {
                        "dense_rank": rank,
                        "article_id": item.article_id,
                        "chunk_id": item.chunk_id,
                        "dense_score": item.dense_score,
                        "text": item.text,
                    }
                    for rank, item in enumerate(raw_rows, start=1)
                ],
            }
        )
        latencies.append(elapsed_ms)
        if ordinal in {1, len(questions)} or ordinal % 25 == 0:
            print(f"exported {ordinal}/{len(questions)}", flush=True)

    index_manifest_path = args.index_root.resolve() / "versions" / index.manifest.run_id / "manifest.json"
    payload = {
        "schema_version": "wixqa_final_raw_candidates_v1",
        "producer_git_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, encoding="utf-8"
        ).strip(),
        "cohort": "expertwritten",
        "consumption": "CONSUMED_RETROSPECTIVE",
        "case_count": len(cases),
        "question_ids_sha256": question_ids_sha256(questions),
        "dataset_manifest_sha256": manifest_sha256,
        "index_run_id": index.manifest.run_id,
        "index_manifest_sha256": hashlib.sha256(index_manifest_path.read_bytes()).hexdigest(),
        "index_artifacts": {item.path: item.sha256 for item in index.manifest.artifacts},
        "embedding_model": client.model_identifier,
        "embedding_model_sha256": client.model_sha256,
        "candidate_k": args.candidate_k,
        "candidate_generation_latency_ms": _latency_summary(latencies),
        "cases": cases,
    }
    content = (json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    print(
        json.dumps(
            {
                "output": str(output),
                "candidate_artifact_sha256": hashlib.sha256(content).hexdigest(),
                "case_count": len(cases),
                "candidate_generation_latency_ms": payload["candidate_generation_latency_ms"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
