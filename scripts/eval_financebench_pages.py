try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
import subprocess
from dataclasses import replace
from pathlib import Path

from app.config import get_settings
from app.evaluation.runtime import build_live_runtime
from app.external_datasets.financebench import (
    DEFAULT_PREPARED_ROOT,
    DEFAULT_PRIVATE_ROOT,
    DEFAULT_SOURCE_ROOT,
    build_financebench_entity_catalog,
    verify_financebench_preparation,
)
from app.external_datasets.financebench_page_eval import (
    build_financebench_page_manifest,
    evaluate_financebench_page_cases,
    load_financebench_bundle,
    load_financebench_page_freeze_protocol,
    publish_financebench_page_run,
    summarize_financebench_page_cases,
)
from app.ollama_chat import chat_with_ollama
from app.retrieval.entity_scope import EntityScopedSearchBackend
from app.retrieval.page_reranker import LocalLLMPageReranker
from app.retrieval.page_reranker import CrossEncoderPageReranker


DEFAULT_INDEX_ROOT = DEFAULT_PRIVATE_ROOT / "indexes"
DEFAULT_OUT_ROOT = DEFAULT_PRIVATE_ROOT / "eval_runs" / "page_retrieval"
DEFAULT_FREEZE_PROTOCOL = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "external_datasets"
    / "evidence"
    / "financebench_page_retrieval_freeze_v1.json"
)
DEFAULT_CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
DEFAULT_CROSS_ENCODER_REVISION = "c5ee24cb16019beea0893ab7796b1df96625c6b8"
DEFAULT_RERANKER_CACHE = (
    Path(__file__).resolve().parent.parent
    / ".private"
    / "model_cache"
    / "sentence_transformers"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate FinanceBench dev document retrieval and exact PDF page "
            "localization without running answer generation."
        )
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument(
        "--prepared-root",
        type=Path,
        default=DEFAULT_PREPARED_ROOT,
    )
    parser.add_argument("--index-root", type=Path, default=DEFAULT_INDEX_ROOT)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--candidate-k", type=int, default=20)
    parser.add_argument("--max-chunks-per-doc", type=int, default=2)
    parser.add_argument(
        "--include-parent",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--retrieval-variant",
        choices=["production", "bm25", "dense", "hybrid_rrf"],
        default="production",
    )
    parser.add_argument(
        "--page-drilldown",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument("--drilldown-max-documents", type=int, default=3)
    parser.add_argument("--drilldown-chunks-per-doc", type=int, default=5)
    parser.add_argument(
        "--drilldown-mode",
        choices=["hybrid", "dense", "bm25"],
        default="hybrid",
    )
    parser.add_argument(
        "--drilldown-merge-mode",
        choices=["quota", "global_page_score"],
        default="quota",
    )
    parser.add_argument(
        "--page-reranker",
        choices=["none", "local_llm", "cross_encoder"],
        default="none",
    )
    parser.add_argument("--reranker-model")
    parser.add_argument("--reranker-model-revision")
    parser.add_argument(
        "--reranker-cache-dir",
        type=Path,
        default=DEFAULT_RERANKER_CACHE,
    )
    parser.add_argument("--reranker-batch-size", type=int, default=16)
    parser.add_argument(
        "--reranker-device",
        choices=["auto", "cpu", "cuda"],
        default="auto",
    )
    parser.add_argument(
        "--reranker-timeout-seconds",
        type=float,
        default=120.0,
    )
    parser.add_argument(
        "--reranker-dense-head-count",
        type=int,
        default=0,
    )
    parser.add_argument(
        "--reranker-max-attempts",
        type=int,
        default=2,
    )
    parser.add_argument(
        "--reranker-gate-mode",
        choices=["always", "dense_top1_below"],
        default="always",
    )
    parser.add_argument(
        "--reranker-gate-threshold",
        type=float,
        default=0.639074,
    )
    parser.add_argument(
        "--freeze-protocol",
        type=Path,
        default=DEFAULT_FREEZE_PROTOCOL,
    )
    parser.add_argument("--execute-frozen-test", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_root = args.source_root.resolve()
    prepared_root = args.prepared_root.resolve()
    index_root = args.index_root.resolve()
    out_root = args.out_root.resolve()
    code_revision = _clean_git_revision()
    freeze_protocol_sha256 = None
    if args.split == "test":
        if not args.execute_frozen_test:
            raise ValueError(
                "test split requires explicit --execute-frozen-test confirmation"
            )
        protocol, freeze_protocol_sha256 = (
            load_financebench_page_freeze_protocol(args.freeze_protocol)
        )
        _validate_frozen_configuration(args, protocol.configuration)
    verify_financebench_preparation(
        source_root=source_root,
        prepared_root=prepared_root,
    )
    cases, evidence_cases, source_hashes = load_financebench_bundle(
        prepared_root,
        split=args.split,
    )
    settings = get_settings().model_copy(
        update={"v2_indexes_dir": index_root}
    )
    runtime = build_live_runtime(settings)
    manifest_embedding = runtime.snapshot.version.manifest.embedding.model
    if manifest_embedding != settings.embedding_model:
        raise ValueError(
            "configured embedding model does not match active index manifest: "
            f"{settings.embedding_model!r} != {manifest_embedding!r}"
        )
    catalog = build_financebench_entity_catalog(source_root)
    raw_pipeline = runtime.pipeline
    pipeline = EntityScopedSearchBackend(raw_pipeline, catalog)
    runtime = replace(
        runtime,
        variant=(
            f"{runtime.variant}+financebench-page-localization-v1"
        ),
        pipeline=pipeline,
    )
    if args.page_reranker != "none" and not args.page_drilldown:
        raise ValueError("page reranker requires --page-drilldown")
    if not 0 < args.reranker_timeout_seconds <= 300:
        raise ValueError("reranker timeout must be between 0 and 300 seconds")
    if not 0 <= args.reranker_dense_head_count <= 4:
        raise ValueError("reranker dense head count must be between 0 and 4")
    if args.page_reranker == "none" and args.reranker_dense_head_count:
        raise ValueError("dense head preservation requires a page reranker")
    if not 1 <= args.reranker_max_attempts <= 3:
        raise ValueError("reranker max attempts must be between 1 and 3")
    if not 1 <= args.reranker_batch_size <= 128:
        raise ValueError("reranker batch size must be between 1 and 128")
    if not float("-inf") < args.reranker_gate_threshold < float("inf"):
        raise ValueError("reranker gate threshold must be finite")
    if args.page_reranker == "local_llm":
        reranker_model = args.reranker_model or settings.evidence_model
    elif args.page_reranker == "cross_encoder":
        reranker_model = args.reranker_model or DEFAULT_CROSS_ENCODER_MODEL
    else:
        reranker_model = "none"
    reranker_model_revision = (
        args.reranker_model_revision or DEFAULT_CROSS_ENCODER_REVISION
        if args.page_reranker == "cross_encoder"
        else "none"
    )

    def tracked_reranker_chat(
        model,
        messages,
        *,
        response_format=None,
        think=None,
    ):
        runtime.counters.generation_calls += 1
        return chat_with_ollama(
            model,
            messages,
            response_format=response_format,
            think=think,
            timeout_seconds=args.reranker_timeout_seconds,
        )

    page_reranker = None
    if args.page_reranker == "local_llm":
        page_reranker = LocalLLMPageReranker(
            model=reranker_model,
            chat_fn=tracked_reranker_chat,
            max_attempts=args.reranker_max_attempts,
        )
    elif args.page_reranker == "cross_encoder":
        page_reranker = CrossEncoderPageReranker(
            model_id=reranker_model,
            score_fn=_load_cross_encoder_score_fn(
                model_id=reranker_model,
                revision=reranker_model_revision,
                cache_dir=args.reranker_cache_dir,
                batch_size=args.reranker_batch_size,
                device=args.reranker_device,
            ),
        )
    embedding_calls_before = runtime.counters.embedding_calls
    generation_calls_before = runtime.counters.generation_calls
    details = evaluate_financebench_page_cases(
        cases=cases,
        evidence_cases=evidence_cases,
        pipeline=runtime.pipeline,
        candidate_k=args.candidate_k,
        max_chunks_per_doc=args.max_chunks_per_doc,
        include_parent=args.include_parent,
        retrieval_variant=args.retrieval_variant,
        split=args.split,
        page_drilldown_backend=(
            raw_pipeline if args.page_drilldown else None
        ),
        drilldown_max_documents=args.drilldown_max_documents,
        drilldown_chunks_per_doc=args.drilldown_chunks_per_doc,
        drilldown_mode=args.drilldown_mode,
        drilldown_merge_mode=args.drilldown_merge_mode,
        page_reranker=page_reranker,
        reranker_dense_head_count=args.reranker_dense_head_count,
        reranker_gate_mode=args.reranker_gate_mode,
        reranker_gate_threshold=args.reranker_gate_threshold,
    )
    embedding_calls = runtime.counters.embedding_calls - embedding_calls_before
    generation_calls = (
        runtime.counters.generation_calls - generation_calls_before
    )
    summary = summarize_financebench_page_cases(details)
    run_manifest = build_financebench_page_manifest(
        run_id=args.run_id,
        source_hashes=source_hashes,
        index_run_id=runtime.snapshot.version.manifest.run_id,
        index_manifest_sha256=runtime.snapshot.version.manifest_sha256,
        entity_catalog_sha256=catalog.canonical_sha256(),
        embedding_model=settings.embedding_model,
        embedding_calls=embedding_calls,
        generation_calls=generation_calls,
        split=args.split,
        code_revision=code_revision,
        freeze_protocol_sha256=freeze_protocol_sha256,
        candidate_k=args.candidate_k,
        max_chunks_per_doc=args.max_chunks_per_doc,
        include_parent=args.include_parent,
        retrieval_variant=args.retrieval_variant,
        page_drilldown=args.page_drilldown,
        drilldown_max_documents=args.drilldown_max_documents,
        drilldown_chunks_per_doc=args.drilldown_chunks_per_doc,
        drilldown_mode=args.drilldown_mode,
        drilldown_merge_mode=args.drilldown_merge_mode,
        page_reranker=args.page_reranker,
        reranker_model=reranker_model,
        reranker_model_revision=reranker_model_revision,
        reranker_timeout_seconds=(
            args.reranker_timeout_seconds
            if args.page_reranker == "local_llm"
            else "none"
        ),
        reranker_batch_size=(
            args.reranker_batch_size
            if args.page_reranker == "cross_encoder"
            else "none"
        ),
        reranker_device=(
            args.reranker_device
            if args.page_reranker == "cross_encoder"
            else "none"
        ),
        reranker_dense_head_count=args.reranker_dense_head_count,
        reranker_max_attempts=args.reranker_max_attempts,
        reranker_gate_mode=args.reranker_gate_mode,
        reranker_gate_threshold=args.reranker_gate_threshold,
        summary=summary,
    )
    output = publish_financebench_page_run(
        root=out_root,
        manifest=run_manifest,
        details=details,
    )
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "split": args.split,
                "case_count": summary.case_count,
                "passed_case_count": summary.passed_case_count,
                "document_recall_at_5_mean": (
                    summary.document_recall_at_5_mean
                ),
                "page_metrics": [
                    item.model_dump(mode="json")
                    for item in summary.cutoffs
                ],
                "page_candidate_metrics": [
                    item.model_dump(mode="json")
                    for item in summary.candidate_cutoffs
                ],
                "page_reranker_metrics": [
                    item.model_dump(mode="json")
                    for item in summary.reranker_cutoffs
                ],
                "reranker_case_count": summary.reranker_case_count,
                "embedding_calls": embedding_calls,
                "generation_calls": generation_calls,
                "reranker_model": reranker_model,
                "output_dir": str(output),
                "frozen_test": (
                    "EXECUTED" if args.split == "test" else "NOT_RUN"
                ),
                "answer_generation": "NOT_RUN",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _load_cross_encoder_score_fn(
    *,
    model_id: str,
    revision: str,
    cache_dir: Path,
    batch_size: int,
    device: str,
):
    try:
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import LocalEntryNotFoundError
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        raise RuntimeError(
            "cross-encoder evaluation requires the optional "
            "sentence-transformers dependency"
        ) from exc

    resolved_cache = Path(cache_dir).resolve()
    resolved_cache.mkdir(parents=True, exist_ok=True)
    try:
        snapshot_path = snapshot_download(
            repo_id=model_id,
            revision=revision,
            cache_dir=resolved_cache,
            local_files_only=True,
        )
    except LocalEntryNotFoundError:
        snapshot_path = snapshot_download(
            repo_id=model_id,
            revision=revision,
            cache_dir=resolved_cache,
        )
    model = CrossEncoder(
        snapshot_path,
        device=None if device == "auto" else device,
        max_length=512,
    )

    def score(question, candidate_texts):
        pairs = [(question, text) for text in candidate_texts]
        return model.predict(
            pairs,
            batch_size=batch_size,
            show_progress_bar=False,
        )

    return score


def _clean_git_revision() -> str:
    root = Path(__file__).resolve().parent.parent
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError(
            "FinanceBench page evaluation requires a clean tracked worktree"
        )
    if len(revision) != 40 or any(
        character not in "0123456789abcdef" for character in revision
    ):
        raise ValueError("Git returned an invalid code revision")
    return revision


def _validate_frozen_configuration(args, configuration) -> None:
    if args.retrieval_variant != "production":
        raise ValueError(
            "test split requires the frozen production retrieval variant"
        )
    if args.drilldown_merge_mode != "quota":
        raise ValueError(
            "test split requires the frozen quota drilldown merge mode"
        )
    if args.page_reranker != "none" or args.reranker_model is not None:
        raise ValueError("test split does not permit an unfrozen page reranker")
    if args.reranker_dense_head_count != 0:
        raise ValueError("test split requires zero reranker dense head count")
    if args.reranker_gate_mode != "always":
        raise ValueError("test split requires the frozen reranker gate mode")
    actual = {
        "top_k": 5,
        "candidate_k": args.candidate_k,
        "max_chunks_per_doc": args.max_chunks_per_doc,
        "include_parent": args.include_parent,
        "page_drilldown": args.page_drilldown,
        "drilldown_max_documents": args.drilldown_max_documents,
        "drilldown_chunks_per_doc": args.drilldown_chunks_per_doc,
        "drilldown_mode": args.drilldown_mode,
        "metric_contract": "unique_doc_page_v1",
        "entity_scope": "exact_year_plus_entity_history_v5",
    }
    if actual != configuration.model_dump(mode="json"):
        raise ValueError(
            "test split configuration does not match the frozen protocol"
        )


if __name__ == "__main__":
    raise SystemExit(main())
