from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from app.config import get_settings
from app.evaluation.runtime import build_live_runtime
from app.external_datasets.uda_finance_page_eval import (
    evaluate_uda_finance_pages,
    summarize_uda_finance_pages,
)
from app.external_datasets.uda_finance_r3 import (
    R3_PREPARED_ROOT,
    R3_PRIVATE_ROOT,
    R3_PROTOCOL_PATH,
    load_uda_finance_r3_cases,
    load_uda_finance_r3_protocol,
    verify_uda_finance_r3_preparation,
)
from app.external_datasets.uda_finance_r3_page_eval import (
    R3_PAGE_PROTOCOL_PATH,
    R3PageStrategyPipeline,
    load_page_protocol,
    publish_r3_page_campaign,
    verify_r3_page_campaign,
)


STRATEGIES = (
    "dense_chunk",
    "dense_page_max",
    "dense_page_neighbor",
    "dense_page_structure",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a frozen UDA R3 page campaign.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--split", choices=("dev", "validation", "test"), required=True)
    parser.add_argument("--strategy", action="append", choices=STRATEGIES, required=True)
    parser.add_argument("--prepared-root", type=Path, default=R3_PREPARED_ROOT)
    parser.add_argument("--index-root", type=Path, default=R3_PRIVATE_ROOT / "indexes")
    parser.add_argument("--out-root", type=Path, default=R3_PRIVATE_ROOT / "page_eval_runs")
    parser.add_argument("--dataset-protocol", type=Path, default=R3_PROTOCOL_PATH)
    parser.add_argument("--page-protocol", type=Path, default=R3_PAGE_PROTOCOL_PATH)
    parser.add_argument("--execute-validation", action="store_true")
    parser.add_argument("--execute-frozen-test", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    strategies = list(dict.fromkeys(args.strategy))
    if len(strategies) != len(args.strategy):
        raise ValueError("R3 page campaign strategies must be unique")
    if args.split == "validation" and not args.execute_validation:
        raise ValueError("R3 validation requires --execute-validation")
    if args.split == "test" and not args.execute_frozen_test:
        raise ValueError("R3 test requires --execute-frozen-test")
    if args.split == "validation" and "dense_chunk" not in strategies:
        raise ValueError("R3 validation campaign must include dense_chunk baseline")
    if args.split == "test" and "dense_chunk" not in strategies:
        raise ValueError("R3 test campaign must include dense_chunk baseline")
    dataset_protocol, dataset_protocol_sha = load_uda_finance_r3_protocol(args.dataset_protocol)
    page_protocol, page_protocol_sha = load_page_protocol(args.page_protocol)
    if page_protocol["dataset_protocol_sha256"] != dataset_protocol_sha:
        raise ValueError("R3 page protocol is not bound to the dataset protocol")
    verify_uda_finance_r3_preparation(prepared_root=args.prepared_root)
    cases, cases_sha = load_uda_finance_r3_cases(args.prepared_root, split=args.split)
    code_revision = clean_git_revision()
    settings = get_settings().model_copy(update={"v2_indexes_dir": args.index_root.resolve()})
    runtime = build_live_runtime(settings)
    expected_index = page_protocol["index_build"]
    if runtime.snapshot.version.manifest_sha256 != expected_index["index_manifest_sha256"]:
        raise ValueError("R3 page campaign loaded the wrong index manifest")
    marker = None
    if args.split in {"validation", "test"}:
        marker = claim_split_execution(
            args.out_root,
            split=args.split,
            run_id=args.run_id,
            code_revision=code_revision,
            page_protocol_sha256=page_protocol_sha,
            cases_sha256=cases_sha,
            strategies=strategies,
        )
    details_by_strategy = {}
    summaries = {}
    for strategy in strategies:
        pipeline = R3PageStrategyPipeline(runtime.pipeline, strategy=strategy, snapshot=runtime.snapshot)
        before = runtime.counters.embedding_calls
        details = evaluate_uda_finance_pages(
            cases=cases,
            pipeline=pipeline,
            retrieval_arm="dense",
            candidate_k=page_protocol["candidate_k"],
            max_chunks_per_doc=5,
            include_parent=False,
        )
        details_by_strategy[strategy] = details
        summaries[strategy] = summarize_uda_finance_pages(
            details,
            embedding_calls=runtime.counters.embedding_calls - before,
        )
    dataset_manifest_path = args.prepared_root.resolve() / "external_dataset_manifest.json"
    run_dir = publish_r3_page_campaign(
        root=args.out_root,
        manifest_fields={
            "run_id": args.run_id,
            "split": args.split,
            "code_revision": code_revision,
            "dataset_protocol_sha256": dataset_protocol_sha,
            "page_protocol_sha256": page_protocol_sha,
            "dataset_manifest_sha256": hashlib.sha256(dataset_manifest_path.read_bytes()).hexdigest(),
            "cases_sha256": cases_sha,
            "index_run_id": runtime.snapshot.version.manifest.run_id,
            "index_manifest_sha256": runtime.snapshot.version.manifest_sha256,
            "embedding_model": runtime.snapshot.version.manifest.embedding.model,
            "candidate_k": page_protocol["candidate_k"],
        },
        details_by_strategy=details_by_strategy,
        summaries=summaries,
    )
    verified = verify_r3_page_campaign(run_dir)
    if marker is not None:
        complete_split_execution(
            marker,
            result_manifest_sha256=hashlib.sha256((run_dir / "manifest.json").read_bytes()).hexdigest(),
        )
    print(json.dumps(verified.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def clean_git_revision() -> str:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
        raise ValueError("R3 page evaluation requires a clean tracked Git tree")
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def claim_split_execution(
    out_root: Path,
    *,
    split: str,
    run_id: str,
    code_revision: str,
    page_protocol_sha256: str,
    cases_sha256: str,
    strategies: list[str],
) -> Path:
    if split not in {"validation", "test"}:
        raise ValueError("only R3 validation and test require one-shot markers")
    root = Path(out_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / f"{split}_execution_v1.json"
    payload = {
        "schema_version": "uda_finance_r3_split_execution_v1",
        "status": "STARTED",
        "split": split,
        "run_id": run_id,
        "code_revision": code_revision,
        "page_protocol_sha256": page_protocol_sha256,
        "cases_sha256": cases_sha256,
        "strategies": strategies,
    }
    with marker.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    return marker


def complete_split_execution(marker: Path, *, result_manifest_sha256: str) -> None:
    marker = Path(marker).resolve()
    payload = json.loads(marker.read_text(encoding="utf-8"))
    if payload.get("status") != "STARTED":
        raise ValueError("R3 split execution marker is not STARTED")
    if len(result_manifest_sha256) != 64:
        raise ValueError("R3 result manifest hash is invalid")
    payload["result_manifest_sha256"] = result_manifest_sha256
    payload["status"] = "COMPLETED"
    temp = marker.with_suffix(".tmp")
    with temp.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, marker)


if __name__ == "__main__":
    raise SystemExit(main())
