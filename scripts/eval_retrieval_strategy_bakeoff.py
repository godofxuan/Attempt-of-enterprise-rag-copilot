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
    fuse_ranked_lists,
    reciprocal_rank_fusion_scores,
    representative_article_vectors,
    select_diverse_articles,
)
from app.evaluation.query_expansion import (
    build_query_expansion_messages,
    validate_query_expansion,
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
from app.ollama_chat import chat_with_ollama
from app.runtime.model_transport import ModelRequestError


Strategy = Literal[
    "S0_BASELINE_HYBRID",
    "S1_DIVERSITY_TOP5",
    "S2_DEEPER_CANDIDATE_DIVERSITY",
    "S4_MULTI_QUERY_EXPANSION",
]
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
    parser.add_argument("--expansion-model", default="qwen3:8b")
    return parser


def strategy_window(strategy: Strategy) -> int:
    return {
        "S0_BASELINE_HYBRID": 5,
        "S1_DIVERSITY_TOP5": 20,
        "S2_DEEPER_CANDIDATE_DIVERSITY": 40,
        "S4_MULTI_QUERY_EXPANSION": 5,
    }[strategy]


def select_strategy_ranking(
    *,
    strategy: Strategy,
    rrf_article_ids: list[str],
    index,
    query_vector,
) -> list[str]:
    window = strategy_window(strategy)
    if strategy in {"S0_BASELINE_HYBRID", "S4_MULTI_QUERY_EXPANSION"}:
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
    private_cases: list[dict[str, object]] = []
    scores = []
    expansion_counters = {"attempts": 0, "accepted": 0, "fallbacks": 0, "transport_retries": 0, "transport_errors": 0}
    for ordinal, question in enumerate(questions, start=1):
        case_started = time.perf_counter()
        variants = [question.question]
        expansion_public: dict[str, object] = {"status": "not_applicable"}
        expansion_private: dict[str, object] = {}
        if args.strategy == "S4_MULTI_QUERY_EXPANSION":
            expansion_counters["attempts"] += 1
            try:
                response = chat_with_ollama(
                    args.expansion_model,
                    build_query_expansion_messages(question.question),
                    response_format="json",
                    think=False,
                    timeout_seconds=30.0,
                    max_output_tokens=160,
                    seed=_question_seed(question.question_id),
                    return_transport=True,
                )
                raw_output, attempts, retries = response
                expansion_counters["transport_retries"] += retries
                expansion = validate_query_expansion(
                    original_query=question.question,
                    raw_output=raw_output,
                )
                expansion_public = {
                    "status": "accepted" if expansion.accepted else "fallback",
                    "rejection_reason": expansion.rejection_reason,
                    "raw_output_sha256": expansion.raw_output_sha256,
                    "transport_attempts": attempts,
                    "transport_retries": retries,
                }
                expansion_private = {"raw_output": raw_output, "accepted_queries": list(expansion.queries)}
                if expansion.accepted:
                    variants.extend(expansion.queries)
                    expansion_counters["accepted"] += 1
                else:
                    expansion_counters["fallbacks"] += 1
            except ModelRequestError as error:
                expansion_counters["transport_errors"] += 1
                expansion_counters["fallbacks"] += 1
                expansion_public = {
                    "status": "fallback",
                    "rejection_reason": error.code,
                    "raw_output_sha256": None,
                    "transport_attempts": error.attempts,
                    "transport_retries": max(0, error.attempts - 1),
                }
            except Exception:
                expansion_counters["transport_errors"] += 1
                expansion_counters["fallbacks"] += 1
                expansion_public = {"status": "fallback", "rejection_reason": "unexpected_error", "raw_output_sha256": None, "transport_attempts": 0, "transport_retries": 0}

        query_vectors = []
        per_query_rankings = []
        for variant in variants:
            bm25 = index.bm25_article_ranking(variant, candidate_k=200)
            query_vector = embedding.embed_batch([variant])
            dense = index.dense_article_ranking(query_vector, candidate_k=200)
            rrf_pairs = reciprocal_rank_fusion_scores(bm25, dense, rrf_k=index.manifest.rrf_k)
            per_query_rankings.append([article_id for article_id, _score in rrf_pairs])
            query_vectors.append(query_vector)
        rrf = fuse_ranked_lists(per_query_rankings, rrf_k=index.manifest.rrf_k)
        ranking = select_strategy_ranking(
            strategy=args.strategy,
            rrf_article_ids=rrf,
            index=index,
            query_vector=query_vectors[0],
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
                "query_variant_count": len(variants),
                "query_expansion": expansion_public,
                "score": score.model_dump(mode="json"),
            }
        )
        private_cases.append({"question_id": question.question_id, "question": question.question, "query_variants": variants, "query_expansion": expansion_private})
        print(f"evaluated {ordinal}/{len(questions)}", flush=True)

    summary = summarize_wixqa_scores(scores, cohort=args.cohort, arm="hybrid_rrf")
    config = {
        "strategy": args.strategy,
        "query_expansion_model": args.expansion_model if args.strategy == "S4_MULTI_QUERY_EXPANSION" else None,
        "query_expansion_generation": ({"temperature": 0.0, "think": False, "num_predict": 160, "seed_policy": "sha256(question_id)"} if args.strategy == "S4_MULTI_QUERY_EXPANSION" else None),
        "query_expansion_transport": expansion_counters if args.strategy == "S4_MULTI_QUERY_EXPANSION" else None,
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
    private_payload = {"schema_version": "retrieval_strategy_bakeoff_private_v1", "config": config, "cases": cases, "private_query_expansion": private_cases}
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


def _question_seed(question_id: str) -> int:
    return int.from_bytes(hashlib.sha256(question_id.encode("utf-8")).digest()[:4], "big") % 2_147_483_648


if __name__ == "__main__":
    raise SystemExit(main())
