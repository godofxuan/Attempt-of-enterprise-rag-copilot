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
    load_wixqa_articles,
    load_wixqa_questions,
    question_ids_sha256,
    validate_wixqa_references,
    verify_wixqa_source,
)
from app.external_datasets.wixqa_retrieval import (
    load_wixqa_flat_index,
    reciprocal_rank_fusion,
    score_wixqa_ranking,
    summarize_wixqa_scores,
)
from app.runtime.ollama_embeddings import OllamaEmbeddingClient


DEFAULT_INDEX_ROOT = Path(".private/external/wixqa/indexes")
DEFAULT_RUN_ROOT = Path(".private/external/wixqa/eval_runs")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate WixQA article retrieval.")
    parser.add_argument("--cohort", choices=("synthetic", "simulated", "expertwritten"), required=True)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_WIXQA_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_WIXQA_MANIFEST)
    parser.add_argument("--index-root", type=Path, default=DEFAULT_INDEX_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--candidate-k", type=int, default=200)
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--consume-fixed-external", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cohort == "expertwritten" and not args.consume_fixed_external:
        raise SystemExit("ExpertWritten requires --consume-fixed-external after protocol freeze")
    if args.max_cases is not None and args.max_cases < 1:
        raise SystemExit("--max-cases must be positive")
    verify_wixqa_source(args.source_root, args.manifest)
    articles = load_wixqa_articles(args.source_root)
    questions = load_wixqa_questions(args.cohort, args.source_root)
    if args.max_cases is not None:
        questions = questions[: args.max_cases]
    validate_wixqa_references(articles, questions)
    index = load_wixqa_flat_index(args.index_root)
    dataset_manifest_sha256 = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    if index.manifest.dataset_manifest_sha256 != dataset_manifest_sha256:
        raise ValueError("WixQA index does not match dataset manifest")
    settings = get_settings()
    client = OllamaEmbeddingClient.from_settings(
        settings,
        probe_text="WixQA query embedding dimension probe",
        endpoint_context="WixQA retrieval evaluation",
    )
    if (
        client.model_identifier != index.manifest.embedding_model
        or client.model_sha256 != index.manifest.embedding_model_sha256
    ):
        raise ValueError("WixQA query and corpus embedding identities differ")

    details = []
    for ordinal, question in enumerate(questions, start=1):
        bm25_started = time.perf_counter()
        bm25 = index.bm25_article_ranking(question.question, candidate_k=args.candidate_k)
        bm25_ms = (time.perf_counter() - bm25_started) * 1000

        dense_started = time.perf_counter()
        query_vector = client.embed_batch([question.question])
        dense = index.dense_article_ranking(query_vector, candidate_k=args.candidate_k)
        dense_ms = (time.perf_counter() - dense_started) * 1000

        fusion_started = time.perf_counter()
        hybrid = reciprocal_rank_fusion(bm25, dense, rrf_k=index.manifest.rrf_k)
        fusion_ms = (time.perf_counter() - fusion_started) * 1000
        details.extend(
            [
                score_wixqa_ranking(question, arm="bm25", ranked_article_ids=bm25, latency_ms=bm25_ms),
                score_wixqa_ranking(question, arm="dense", ranked_article_ids=dense, latency_ms=dense_ms),
                score_wixqa_ranking(
                    question,
                    arm="hybrid_rrf",
                    ranked_article_ids=hybrid,
                    latency_ms=bm25_ms + dense_ms + fusion_ms,
                ),
            ]
        )
        if ordinal in {1, len(questions)} or ordinal % 25 == 0:
            print(f"evaluated {ordinal}/{len(questions)}", flush=True)

    summaries = [
        summarize_wixqa_scores(details, cohort=args.cohort, arm=arm)
        for arm in ("bm25", "dense", "hybrid_rrf")
    ]
    run_dir = args.output_root.resolve() / args.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    detail_bytes = b"".join(
        (json.dumps(row.model_dump(mode="json"), ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        for row in details
    )
    (run_dir / "details.jsonl").write_bytes(detail_bytes)
    code_revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, encoding="utf-8"
    ).strip()
    payload = {
        "schema_version": "wixqa_retrieval_run_v1",
        "run_id": args.run_id,
        "code_revision": code_revision,
        "cohort": args.cohort,
        "consumption": (
            "FIXED_CONSUMED" if args.cohort == "expertwritten" else
            "VALIDATION" if args.cohort == "simulated" else "DEVELOPMENT"
        ),
        "case_count": len(questions),
        "question_ids_sha256": question_ids_sha256(questions),
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "index_run_id": index.manifest.run_id,
        "index_manifest_sha256": hashlib.sha256(
            (args.index_root.resolve() / "versions" / index.manifest.run_id / "manifest.json").read_bytes()
        ).hexdigest(),
        "embedding_model": client.model_identifier,
        "embedding_model_sha256": client.model_sha256,
        "candidate_k": args.candidate_k,
        "query_embedding_calls": len(questions),
        "details_sha256": hashlib.sha256(detail_bytes).hexdigest(),
        "summaries": [row.model_dump(mode="json") for row in summaries],
    }
    summary_bytes = (
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    (run_dir / "summary.json").write_bytes(summary_bytes)
    print(summary_bytes.decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

