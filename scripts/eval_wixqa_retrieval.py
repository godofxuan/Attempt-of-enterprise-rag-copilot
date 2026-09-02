from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from importlib import import_module
from pathlib import Path

from app.config import get_settings
from app.domain.queries import SearchHit
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
    WixQAArticleCandidate,
    load_wixqa_flat_index,
    merge_reranked_article_ids,
    reciprocal_rank_fusion,
    score_wixqa_ranking,
    summarize_wixqa_scores,
)
from app.retrieval.page_reranker import CrossEncoderPageReranker
from app.runtime.ollama_embeddings import OllamaEmbeddingClient

DEFAULT_INDEX_ROOT = Path(".private/external/wixqa/indexes")
DEFAULT_RUN_ROOT = Path(".private/external/wixqa/eval_runs")
DEFAULT_RERANKER_CACHE_ROOT = Path(".private/model_cache/sentence_transformers")
DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
DEFAULT_RERANKER_REVISION = "c5ee24cb16019beea0893ab7796b1df96625c6b8"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate WixQA article retrieval.")
    parser.add_argument(
        "--cohort", choices=("synthetic", "simulated", "expertwritten"), required=True
    )
    parser.add_argument("--source-root", type=Path, default=DEFAULT_WIXQA_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_WIXQA_MANIFEST)
    parser.add_argument("--index-root", type=Path, default=DEFAULT_INDEX_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--candidate-k", type=int, default=200)
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--consume-fixed-external", action="store_true")
    parser.add_argument(
        "--article-reranker",
        choices=("none", "cross_encoder"),
        default="none",
    )
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--reranker-revision", default=DEFAULT_RERANKER_REVISION)
    parser.add_argument("--reranker-cache-root", type=Path, default=DEFAULT_RERANKER_CACHE_ROOT)
    parser.add_argument("--reranker-device", default="cpu")
    parser.add_argument(
        "--reranker-dtype",
        choices=("auto", "float32", "float16", "bfloat16"),
        default="auto",
    )
    parser.add_argument("--reranker-batch-size", type=int, default=16)
    parser.add_argument("--reranker-top-n", type=int, default=10)
    parser.add_argument("--reranker-dense-head-count", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cohort == "expertwritten" and not args.consume_fixed_external:
        raise SystemExit("ExpertWritten requires --consume-fixed-external after protocol freeze")
    if args.max_cases is not None and args.max_cases < 1:
        raise SystemExit("--max-cases must be positive")
    if not 1 <= args.reranker_top_n <= 20:
        raise SystemExit("--reranker-top-n must be between 1 and 20")
    if not 0 <= args.reranker_dense_head_count <= args.reranker_top_n:
        raise SystemExit("--reranker-dense-head-count must fit reranker top-N")
    if args.reranker_batch_size < 1:
        raise SystemExit("--reranker-batch-size must be positive")
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

    page_reranker = None
    reranker_load_ms = 0.0
    if args.article_reranker == "cross_encoder":
        cross_encoder_type = import_module("sentence_transformers").CrossEncoder
        snapshot = _resolve_model_snapshot(
            args.reranker_cache_root,
            model_id=args.reranker_model,
            revision=args.reranker_revision,
        )
        load_started = time.perf_counter()
        model = cross_encoder_type(
            str(snapshot),
            device=args.reranker_device,
            model_kwargs=_model_kwargs_for_dtype(args.reranker_dtype),
        )
        reranker_load_ms = (time.perf_counter() - load_started) * 1000

        def score_fn(question: str, texts: list[str]) -> list[float]:
            scores = model.predict(
                [(question, text) for text in texts],
                batch_size=args.reranker_batch_size,
                show_progress_bar=False,
            )
            return [float(item) for item in scores]

        page_reranker = CrossEncoderPageReranker(
            model_id=f"{args.reranker_model}@{args.reranker_revision}",
            score_fn=score_fn,
        )

    details = []
    reranker_calls = 0
    reranker_admitted = 0
    reranker_quarantined = 0
    reranker_guard_rule_ids: set[str] = set()
    for ordinal, question in enumerate(questions, start=1):
        bm25_started = time.perf_counter()
        bm25 = index.bm25_article_ranking(question.question, candidate_k=args.candidate_k)
        bm25_ms = (time.perf_counter() - bm25_started) * 1000

        dense_started = time.perf_counter()
        query_vector = client.embed_batch([question.question])
        dense_candidates = index.dense_article_candidates(
            query_vector,
            candidate_k=args.candidate_k,
        )
        dense = [item.article_id for item in dense_candidates]
        dense_ms = (time.perf_counter() - dense_started) * 1000

        fusion_started = time.perf_counter()
        hybrid = reciprocal_rank_fusion(bm25, dense, rrf_k=index.manifest.rrf_k)
        fusion_ms = (time.perf_counter() - fusion_started) * 1000
        details.extend(
            [
                score_wixqa_ranking(
                    question, arm="bm25", ranked_article_ids=bm25, latency_ms=bm25_ms
                ),
                score_wixqa_ranking(
                    question, arm="dense", ranked_article_ids=dense, latency_ms=dense_ms
                ),
                score_wixqa_ranking(
                    question,
                    arm="hybrid_rrf",
                    ranked_article_ids=hybrid,
                    latency_ms=bm25_ms + dense_ms + fusion_ms,
                ),
            ]
        )
        if page_reranker is not None:
            top_n = min(args.reranker_top_n, len(dense_candidates))
            reranker_started = time.perf_counter()
            reranked = page_reranker.rerank(
                question=question.question,
                candidates=[
                    _candidate_hit(item, index_run_id=index.manifest.run_id, rank=rank)
                    for rank, item in enumerate(dense_candidates[:top_n], start=1)
                ],
            )
            reranker_ms = (time.perf_counter() - reranker_started) * 1000
            reranker_calls += 1
            reranker_admitted += reranked.admitted_count
            reranker_quarantined += reranked.quarantined_count
            reranker_guard_rule_ids.update(reranked.guard_rule_ids)
            final = merge_reranked_article_ids(
                dense_article_ids=dense,
                reranked_article_ids=[item.doc_id for item in reranked.hits],
                reranker_top_n=top_n,
                dense_head_count=min(args.reranker_dense_head_count, top_n),
            )
            details.append(
                score_wixqa_ranking(
                    question,
                    arm="dense_cross_encoder",
                    ranked_article_ids=final,
                    latency_ms=dense_ms + reranker_ms,
                )
            )
        if ordinal in {1, len(questions)} or ordinal % 25 == 0:
            print(f"evaluated {ordinal}/{len(questions)}", flush=True)

    arms = ["bm25", "dense", "hybrid_rrf"]
    if page_reranker is not None:
        arms.append("dense_cross_encoder")
    summaries = [summarize_wixqa_scores(details, cohort=args.cohort, arm=arm) for arm in arms]
    run_dir = args.output_root.resolve() / args.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    detail_bytes = b"".join(
        (
            json.dumps(
                row.model_dump(mode="json"),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        for row in details
    )
    (run_dir / "details.jsonl").write_bytes(detail_bytes)
    code_revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, encoding="utf-8"
    ).strip()
    payload = {
        "schema_version": "wixqa_retrieval_run_v2",
        "run_id": args.run_id,
        "code_revision": code_revision,
        "cohort": args.cohort,
        "consumption": (
            "FIXED_CONSUMED"
            if args.cohort == "expertwritten"
            else "VALIDATION"
            if args.cohort == "simulated"
            else "DEVELOPMENT"
        ),
        "case_count": len(questions),
        "question_ids_sha256": question_ids_sha256(questions),
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "index_run_id": index.manifest.run_id,
        "index_manifest_sha256": hashlib.sha256(
            (
                args.index_root.resolve() / "versions" / index.manifest.run_id / "manifest.json"
            ).read_bytes()
        ).hexdigest(),
        "embedding_model": client.model_identifier,
        "embedding_model_sha256": client.model_sha256,
        "candidate_k": args.candidate_k,
        "query_embedding_calls": len(questions),
        "reranker": {
            "type": args.article_reranker,
            "model": args.reranker_model if page_reranker is not None else None,
            "revision": args.reranker_revision if page_reranker is not None else None,
            "device": args.reranker_device if page_reranker is not None else None,
            "dtype": args.reranker_dtype if page_reranker is not None else None,
            "batch_size": args.reranker_batch_size if page_reranker is not None else None,
            "top_n": args.reranker_top_n if page_reranker is not None else None,
            "dense_head_count": (
                args.reranker_dense_head_count if page_reranker is not None else None
            ),
            "load_ms": reranker_load_ms,
            "calls": reranker_calls,
            "admitted_candidates": reranker_admitted,
            "quarantined_candidates": reranker_quarantined,
            "guard_rule_ids": sorted(reranker_guard_rule_ids),
        },
        "details_sha256": hashlib.sha256(detail_bytes).hexdigest(),
        "summaries": [row.model_dump(mode="json") for row in summaries],
    }
    summary_bytes = (
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    (run_dir / "summary.json").write_bytes(summary_bytes)
    print(summary_bytes.decode("utf-8"))
    return 0


def _model_kwargs_for_dtype(dtype: str) -> dict[str, object]:
    if dtype == "auto":
        return {}
    torch = import_module("torch")
    return {
        "torch_dtype": {
            "float32": torch.float32,
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
        }[dtype]
    }


def _resolve_model_snapshot(cache_root: Path, *, model_id: str, revision: str) -> Path:
    model_dir = "models--" + model_id.replace("/", "--")
    snapshot = Path(cache_root).resolve() / model_dir / "snapshots" / revision
    if not snapshot.is_dir():
        raise FileNotFoundError(
            f"pinned reranker snapshot is unavailable on D drive: {model_id}@{revision}"
        )
    return snapshot


def _candidate_hit(
    candidate: WixQAArticleCandidate,
    *,
    index_run_id: str,
    rank: int,
) -> SearchHit:
    title = candidate.text.splitlines()[0].strip() or candidate.article_id
    return SearchHit(
        index_run_id=index_run_id,
        chunk_id=candidate.chunk_id,
        doc_id=candidate.article_id,
        source_path=f"wixqa://article/{candidate.article_id}",
        section_path=[title],
        matched_text=candidate.text,
        context_text=candidate.text,
        tenant_id="wixqa-public",
        region="global",
        acl_groups=["public"],
        version_id="wixqa-pinned",
        version="wixqa-pinned",
        status="active",
        authority_level=1,
        variant="wixqa-dense-candidate",
        fused_score=candidate.dense_score,
        dense_score=candidate.dense_score,
        dense_rank=rank,
    )


if __name__ == "__main__":
    raise SystemExit(main())
