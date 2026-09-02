from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from app.config import get_settings
from app.external_datasets.wixqa import (
    DEFAULT_WIXQA_MANIFEST,
    DEFAULT_WIXQA_ROOT,
    WixQAQuestion,
    load_wixqa_articles,
    load_wixqa_questions,
    question_ids_sha256,
    validate_wixqa_references,
    verify_wixqa_source,
)
from app.external_datasets.wixqa_retrieval import load_wixqa_flat_index
from app.runtime.ollama_embeddings import OllamaEmbeddingClient

DEFAULT_INDEX_ROOT = Path(".private/external/wixqa/indexes")
DEFAULT_OUTPUT_ROOT = Path(".private/external/wixqa/candidate_ceiling_runs")
CUTOFFS = (5, 10, 20)


def cutoff_metrics(
    question: WixQAQuestion,
    ranked_article_ids: Sequence[str],
) -> dict[str, float]:
    gold = set(question.article_ids)
    metrics: dict[str, float] = {}
    for cutoff in CUTOFFS:
        selected = set(ranked_article_ids[:cutoff])
        overlap = len(gold.intersection(selected))
        metrics[f"hit_at_{cutoff}"] = float(overlap > 0)
        metrics[f"recall_at_{cutoff}"] = overlap / len(gold)
        if len(gold) > 1:
            metrics[f"complete_at_{cutoff}"] = float(gold <= selected)
    return metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure WixQA Dense candidate ceilings.")
    parser.add_argument("--cohort", choices=("simulated", "expertwritten"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_WIXQA_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_WIXQA_MANIFEST)
    parser.add_argument("--index-root", type=Path, default=DEFAULT_INDEX_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    verify_wixqa_source(args.source_root, args.manifest)
    articles = load_wixqa_articles(args.source_root)
    questions = load_wixqa_questions(args.cohort, args.source_root)
    validate_wixqa_references(articles, questions)
    index = load_wixqa_flat_index(args.index_root)
    dataset_manifest_sha256 = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    if index.manifest.dataset_manifest_sha256 != dataset_manifest_sha256:
        raise ValueError("WixQA index does not match dataset manifest")

    client = OllamaEmbeddingClient.from_settings(
        get_settings(),
        probe_text="WixQA candidate ceiling dimension probe",
        endpoint_context="WixQA candidate ceiling analysis",
    )
    if (
        client.model_identifier != index.manifest.embedding_model
        or client.model_sha256 != index.manifest.embedding_model_sha256
    ):
        raise ValueError("WixQA query and corpus embedding identities differ")

    details: list[dict[str, object]] = []
    for ordinal, question in enumerate(questions, start=1):
        vector = client.embed_batch([question.question])
        ranking = index.dense_article_ranking(vector, candidate_k=200)
        details.append(
            {
                "question_id": question.question_id,
                "gold_article_count": len(question.article_ids),
                "metrics": cutoff_metrics(question, ranking),
            }
        )
        if ordinal in {1, len(questions)} or ordinal % 25 == 0:
            print(f"analyzed {ordinal}/{len(questions)}", flush=True)

    detail_bytes = b"".join(
        (
            json.dumps(row, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
            + "\n"
        ).encode("utf-8")
        for row in details
    )
    multi_rows = [row for row in details if int(row["gold_article_count"]) > 1]
    summary_metrics: dict[str, float] = {}
    for cutoff in CUTOFFS:
        for metric in ("hit", "recall"):
            key = f"{metric}_at_{cutoff}"
            summary_metrics[key] = sum(
                float(row["metrics"][key]) for row in details  # type: ignore[index]
            ) / len(details)
        complete_key = f"complete_at_{cutoff}"
        summary_metrics[complete_key] = sum(
            float(row["metrics"][complete_key]) for row in multi_rows  # type: ignore[index]
        ) / len(multi_rows)

    run_dir = args.output_root.resolve() / args.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "details.jsonl").write_bytes(detail_bytes)
    payload = {
        "schema_version": "wixqa_candidate_ceiling_run_v1",
        "run_id": args.run_id,
        "code_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, encoding="utf-8"
        ).strip(),
        "cohort": args.cohort,
        "case_count": len(details),
        "multi_article_case_count": len(multi_rows),
        "question_ids_sha256": question_ids_sha256(questions),
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "index_run_id": index.manifest.run_id,
        "embedding_model": client.model_identifier,
        "embedding_model_sha256": client.model_sha256,
        "candidate_k_chunks": 200,
        "query_embedding_calls": len(questions),
        "details_sha256": hashlib.sha256(detail_bytes).hexdigest(),
        "metrics": summary_metrics,
    }
    summary_bytes = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    (run_dir / "summary.json").write_bytes(summary_bytes)
    print(summary_bytes.decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
