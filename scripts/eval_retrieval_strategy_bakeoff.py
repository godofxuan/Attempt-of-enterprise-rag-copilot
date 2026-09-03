"""Run one deterministic WixQA retrieval strategy under the frozen bake-off."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Literal

from app.config import get_settings
from app.evaluation.retrieval_strategy_bakeoff import (
    DIVERSITY_ALPHA,
    reciprocal_rank_fusion_scores,
    representative_article_vectors,
    select_diverse_articles,
)
from app.external_datasets.wixqa import (
    DEFAULT_WIXQA_MANIFEST,
    DEFAULT_WIXQA_ROOT,
    canonical_json_bytes,
    load_wixqa_articles,
    load_wixqa_questions,
    question_ids_sha256,
    validate_wixqa_references,
    verify_wixqa_source,
)
from app.external_datasets.wixqa_retrieval import (
    load_wixqa_flat_index,
    score_wixqa_ranking,
    summarize_wixqa_scores,
)
from app.runtime.ollama_embeddings import OllamaEmbeddingClient


Strategy = Literal["S0_BASELINE_HYBRID", "S1_DIVERSITY_TOP5", "S2_DEEPER_CANDIDATE_DIVERSITY"]
DEFAULT_INDEX_ROOT = Path(".private/external/wixqa/indexes")
DEFAULT_PRIVATE_ROOT = Path(".private/external/wixqa/retrieval_strategy_bakeoff")
DEFAULT_PUBLIC_ROOT = Path("docs/retrieval_strategy_bakeoff_v1/evidence")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", choices=tuple(Strategy.__args__), required=True)
    parser.add_argument("--cohort", choices=("simulated", "expertwritten"), default="expertwritten")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_WIXQA_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_WIXQA_MANIFEST)
    parser.add_argument("--index-root", type=Path, default=DEFAULT_INDEX_ROOT)
    parser.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE_ROOT)
    parser.add_argument("--public-root", type=Path, default=DEFAULT_PUBLIC_ROOT)
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--consume-fixed-external", action="store_true")
    return parser


def strategy_window(strategy: Strategy) -> int:
    return {"S0_BASELINE_HYBRID": 5, "S1_DIVERSITY_TOP5": 20, "S2_DEEPER_CANDIDATE_DIVERSITY": 40}[strategy]


def select_strategy_ranking(
    *,
    strategy: Strategy,
    rrf_article_ids: list[str],
    index,
    query_vector,
) -> list[str]:
    window = strategy_window(strategy)
    if strategy == "S0_BASELINE_HYBRID":
        return rrf_article_ids[:window]
    candidates = rrf_article_ids[:window]
    vectors = representative_article_vectors(
        index,
        article_ids=candidates,
        query_vector=query_vector,
    )
    return select_diverse_articles(candidates, article_vectors=vectors, final_k=5)


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
    manifest_sha256 = _sha256_file(args.manifest)
    if index.manifest.dataset_manifest_sha256 != manifest_sha256:
        raise ValueError("WixQA index does not match the selected dataset manifest")

    settings = get_settings()
    embedding = OllamaEmbeddingClient.from_settings(
        settings,
        probe_text="WixQA retrieval strategy bake-off embedding dimension probe",
        endpoint_context="WixQA retrieval strategy bake-off",
    )
    if (
        embedding.model_identifier != index.manifest.embedding_model
        or embedding.model_sha256 != index.manifest.embedding_model_sha256
    ):
        raise ValueError("query and corpus embedding identities differ")

    private_dir = args.private_root.resolve() / args.run_id
    if private_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing run: {private_dir}")
    private_dir.mkdir(parents=True)
    started = time.perf_counter()
    cases: list[dict[str, object]] = []
    scores = []
    for ordinal, question in enumerate(questions, start=1):
        case_started = time.perf_counter()
        bm25 = index.bm25_article_ranking(question.question, candidate_k=200)
        query_vector = embedding.embed_batch([question.question])
        dense = index.dense_article_ranking(query_vector, candidate_k=200)
        rrf_pairs = reciprocal_rank_fusion_scores(bm25, dense, rrf_k=index.manifest.rrf_k)
        rrf = [article_id for article_id, _score in rrf_pairs]
        ranking = select_strategy_ranking(
            strategy=args.strategy,
            rrf_article_ids=rrf,
            index=index,
            query_vector=query_vector,
        )
        latency_ms = (time.perf_counter() - case_started) * 1000.0
        score = score_wixqa_ranking(
            question,
            arm="hybrid_rrf",
            ranked_article_ids=ranking,
            latency_ms=latency_ms,
        )
        scores.append(score)
        cases.append(
            {
                "question_id": question.question_id,
                "gold_article_ids_sha256": hashlib.sha256(
                    canonical_json_bytes(sorted(question.article_ids))
                ).hexdigest(),
                "rrf_candidate_window": strategy_window(args.strategy),
                "rrf_candidate_gold_recall": len(set(rrf[: strategy_window(args.strategy)]).intersection(question.article_ids)) / len(question.article_ids),
                "score": score.model_dump(mode="json"),
            }
        )
        print(f"evaluated {ordinal}/{len(questions)}", flush=True)

    summary = summarize_wixqa_scores(scores, cohort=args.cohort, arm="hybrid_rrf")
    config = {
        "strategy": args.strategy,
        "final_top_k": 5,
        "source_candidate_depth_per_retriever": 200,
        "rrf_window": strategy_window(args.strategy),
        "rrf_k": index.manifest.rrf_k,
        "diversity_alpha": DIVERSITY_ALPHA if args.strategy != "S0_BASELINE_HYBRID" else None,
        "embedding_model": embedding.model_identifier,
        "embedding_model_sha256": embedding.model_sha256,
        "index_run_id": index.manifest.run_id,
        "index_manifest_sha256": _sha256_file(
            args.index_root.resolve() / "versions" / index.manifest.run_id / "manifest.json"
        ),
        "dataset_manifest_sha256": manifest_sha256,
        "question_ids_sha256": question_ids_sha256(questions),
        "case_count": len(questions),
        "git_sha": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "duration_ms": (time.perf_counter() - started) * 1000.0,
    }
    private_payload = {"schema_version": "retrieval_strategy_bakeoff_private_v1", "config": config, "cases": cases}
    private_bytes = canonical_json_bytes(private_payload)
    (private_dir / "details.json").write_bytes(private_bytes)
    public_payload = {
        "schema_version": "retrieval_strategy_bakeoff_public_v1",
        "config": config,
        "summary": summary.model_dump(mode="json"),
        "private_details_sha256": hashlib.sha256(private_bytes).hexdigest(),
        "claim_boundary": "Consumed WixQA cohort retrieval evidence only; it is not answer accuracy, blind validation, or a production latency SLA.",
    }
    public_payload["artifact_payload_sha256"] = hashlib.sha256(canonical_json_bytes(public_payload)).hexdigest()
    args.public_root.mkdir(parents=True, exist_ok=True)
    output = args.public_root / f"{args.run_id}.json"
    if output.exists():
        raise FileExistsError(f"refusing to overwrite public evidence: {output}")
    output.write_bytes(canonical_json_bytes(public_payload))
    print(json.dumps(public_payload, indent=2, sort_keys=True))
    return 0


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
