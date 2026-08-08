from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from app.config import get_settings
from app.evaluation.runtime import build_live_runtime
from app.external_datasets.uda_finance import (
    DEFAULT_PREPARED_ROOT,
    DEFAULT_PRIVATE_ROOT,
    DEFAULT_PROTOCOL_PATH,
    load_uda_finance_protocol,
    verify_uda_finance_preparation,
)
from app.external_datasets.uda_finance_page_eval import (
    evaluate_uda_finance_pages,
    load_uda_finance_cases,
    publish_uda_finance_page_run,
    summarize_uda_finance_pages,
    verify_uda_finance_page_run,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate UDA document-conditioned page retrieval.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--retrieval-arm", choices=("bm25", "dense", "hybrid_rrf"), required=True)
    parser.add_argument("--prepared-root", type=Path, default=DEFAULT_PREPARED_ROOT)
    parser.add_argument("--index-root", type=Path, default=DEFAULT_PRIVATE_ROOT / "indexes")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_PRIVATE_ROOT / "eval_runs")
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL_PATH)
    parser.add_argument("--candidate-k", type=int, default=20)
    parser.add_argument("--max-chunks-per-doc", type=int, default=5)
    parser.add_argument("--include-parent", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--execute-frozen-test", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol, protocol_sha256 = load_uda_finance_protocol(args.protocol)
    if args.split == "test" and not args.execute_frozen_test:
        raise ValueError("UDA test requires explicit --execute-frozen-test confirmation")
    if args.retrieval_arm not in protocol.retrieval_arms:
        raise ValueError("UDA retrieval arm is outside the frozen protocol")
    dataset = verify_uda_finance_preparation(prepared_root=args.prepared_root)
    cases, cases_sha256 = load_uda_finance_cases(args.prepared_root, split=args.split)
    settings = get_settings().model_copy(update={"v2_indexes_dir": args.index_root.resolve()})
    runtime = build_live_runtime(settings)
    before = runtime.counters.embedding_calls
    details = evaluate_uda_finance_pages(
        cases=cases,
        pipeline=runtime.pipeline,
        retrieval_arm=args.retrieval_arm,
        candidate_k=args.candidate_k,
        max_chunks_per_doc=args.max_chunks_per_doc,
        include_parent=args.include_parent,
    )
    embedding_calls = runtime.counters.embedding_calls - before
    summary = summarize_uda_finance_pages(details, embedding_calls=embedding_calls)
    dataset_manifest_path = args.prepared_root.resolve() / "external_dataset_manifest.json"
    run_dir = publish_uda_finance_page_run(
        root=args.out_root,
        run_id=args.run_id,
        split=args.split,
        retrieval_arm=args.retrieval_arm,
        code_revision=_clean_git_revision(),
        protocol_sha256=protocol_sha256,
        dataset_manifest_sha256=hashlib.sha256(dataset_manifest_path.read_bytes()).hexdigest(),
        cases_sha256=cases_sha256,
        index_run_id=runtime.snapshot.version.manifest.run_id,
        index_manifest_sha256=runtime.snapshot.version.manifest_sha256,
        embedding_model=runtime.snapshot.version.manifest.embedding.model,
        candidate_k=args.candidate_k,
        max_chunks_per_doc=args.max_chunks_per_doc,
        include_parent=args.include_parent,
        details=details,
        summary=summary,
    )
    verified = verify_uda_finance_page_run(run_dir)
    print(json.dumps(verified.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _clean_git_revision() -> str:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
        raise ValueError("UDA evaluation requires a clean tracked Git tree")
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
