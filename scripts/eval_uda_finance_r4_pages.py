from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from app.config import get_settings
from app.evaluation.runtime import build_live_runtime
from app.external_datasets.uda_finance_hierarchical import FocusedPageFusionPipeline
from app.external_datasets.uda_finance_page_eval import (
    evaluate_uda_finance_pages,
    summarize_uda_finance_pages,
)
from app.external_datasets.uda_finance_r4 import (
    R4_PREPARED_ROOT,
    R4_PRIVATE_ROOT,
    R4_PROTOCOL_PATH,
    load_uda_finance_r4_cases,
    load_uda_finance_r4_protocol,
    verify_uda_finance_r4_preparation,
)
from app.external_datasets.uda_finance_r4_eval import (
    publish_r4_campaign,
    verify_r4_campaign,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the frozen paired UDA R4 page campaign.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--split", choices=("dev", "validation", "test"), required=True)
    parser.add_argument("--prepared-root", type=Path, default=R4_PREPARED_ROOT)
    parser.add_argument("--index-root", type=Path, default=R4_PRIVATE_ROOT / "indexes")
    parser.add_argument("--out-root", type=Path, default=R4_PRIVATE_ROOT / "page_eval_runs")
    parser.add_argument("--protocol", type=Path, default=R4_PROTOCOL_PATH)
    parser.add_argument("--development-run-id")
    parser.add_argument("--execute-validation", action="store_true")
    parser.add_argument("--execute-frozen-test", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.split == "validation" and not args.execute_validation:
        raise ValueError("R4 validation requires --execute-validation")
    if args.split == "test" and not args.execute_frozen_test:
        raise ValueError("R4 test requires --execute-frozen-test")
    if args.split == "test":
        require_validation_authorization(args.out_root)
    protocol, protocol_sha256 = load_uda_finance_r4_protocol(args.protocol)
    verify_uda_finance_r4_preparation(prepared_root=args.prepared_root)
    cases, cases_sha256 = load_uda_finance_r4_cases(args.prepared_root, split=args.split)
    code_revision = clean_git_revision()
    if args.split == "validation":
        if not args.development_run_id:
            raise ValueError("R4 validation requires --development-run-id")
        _, development_cases_sha256 = load_uda_finance_r4_cases(
            args.prepared_root,
            split="dev",
        )
        require_development_authorization(
            args.out_root,
            run_id=args.development_run_id,
            code_revision=code_revision,
            protocol_sha256=protocol_sha256,
            cases_sha256=development_cases_sha256,
        )
    settings = get_settings().model_copy(update={"v2_indexes_dir": args.index_root.resolve()})
    runtime = build_live_runtime(settings)
    marker = None
    if args.split in {"validation", "test"}:
        marker = claim_split_execution(
            args.out_root,
            split=args.split,
            run_id=args.run_id,
            code_revision=code_revision,
            protocol_sha256=protocol_sha256,
            cases_sha256=cases_sha256,
        )
    before = runtime.counters.embedding_calls
    baseline_details = evaluate_uda_finance_pages(
        cases=cases,
        pipeline=runtime.pipeline,
        retrieval_arm="dense",
        candidate_k=protocol.baseline_candidate_k,
        max_chunks_per_doc=protocol.baseline_max_chunks_per_doc,
        include_parent=False,
    )
    baseline_summary = summarize_uda_finance_pages(
        baseline_details,
        embedding_calls=runtime.counters.embedding_calls - before,
    )
    candidate_pipeline = FocusedPageFusionPipeline(
        runtime.pipeline,
        source_top_k=protocol.source_top_k,
        candidate_k=protocol.candidate_k,
        max_chunks_per_doc=protocol.max_chunks_per_doc,
        lexical_weight=protocol.lexical_weight,
        original_bm25_weight=protocol.original_bm25_weight,
        rrf_k=protocol.rrf_k,
        parallel_search=protocol.parallel_search,
        shared_scope_search=protocol.shared_scope_search,
    )
    before = runtime.counters.embedding_calls
    candidate_details = evaluate_uda_finance_pages(
        cases=cases,
        pipeline=candidate_pipeline,
        retrieval_arm="dense",
        candidate_k=protocol.baseline_candidate_k,
        max_chunks_per_doc=protocol.baseline_max_chunks_per_doc,
        include_parent=False,
    )
    candidate_summary = summarize_uda_finance_pages(
        candidate_details,
        embedding_calls=runtime.counters.embedding_calls - before,
    )
    dataset_manifest_path = args.prepared_root.resolve() / "external_dataset_manifest.json"
    run_dir = publish_r4_campaign(
        root=args.out_root,
        manifest_fields={
            "run_id": args.run_id,
            "split": args.split,
            "code_revision": code_revision,
            "protocol_sha256": protocol_sha256,
            "dataset_manifest_sha256": hashlib.sha256(
                dataset_manifest_path.read_bytes()
            ).hexdigest(),
            "cases_sha256": cases_sha256,
            "index_run_id": runtime.snapshot.version.manifest.run_id,
            "index_manifest_sha256": runtime.snapshot.version.manifest_sha256,
            "embedding_model": runtime.snapshot.version.manifest.embedding.model,
        },
        details_by_arm={
            "dense_chunk": baseline_details,
            "focused_page_fusion": candidate_details,
        },
        summaries={
            "dense_chunk": baseline_summary,
            "focused_page_fusion": candidate_summary,
        },
        protocol=protocol,
    )
    verified = verify_r4_campaign(run_dir)
    manifest_sha256 = hashlib.sha256((run_dir / "manifest.json").read_bytes()).hexdigest()
    if marker is not None:
        complete_split_execution(
            marker,
            result_manifest_sha256=manifest_sha256,
            decision=verified.decision,
        )
    print(
        json.dumps(verified.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0


def clean_git_revision() -> str:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
        raise ValueError("R4 page evaluation requires a clean tracked Git tree")
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def claim_split_execution(
    out_root: Path,
    *,
    split: str,
    run_id: str,
    code_revision: str,
    protocol_sha256: str,
    cases_sha256: str,
) -> Path:
    if split not in {"validation", "test"}:
        raise ValueError("only R4 validation and test require one-shot markers")
    root = Path(out_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / f"{split}_execution_v1.json"
    payload = {
        "schema_version": "uda_finance_r4_split_execution_v1",
        "status": "STARTED",
        "split": split,
        "run_id": run_id,
        "code_revision": code_revision,
        "protocol_sha256": protocol_sha256,
        "cases_sha256": cases_sha256,
    }
    with marker.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    return marker


def complete_split_execution(marker: Path, *, result_manifest_sha256: str, decision: str) -> None:
    marker = Path(marker).resolve()
    payload = json.loads(marker.read_text(encoding="utf-8"))
    if payload.get("status") != "STARTED":
        raise ValueError("R4 split execution marker is not STARTED")
    payload.update(
        {
            "status": "COMPLETED",
            "result_manifest_sha256": result_manifest_sha256,
            "decision": decision,
        }
    )
    temp = marker.with_suffix(".tmp")
    with temp.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, marker)


def require_validation_authorization(out_root: Path) -> None:
    marker = Path(out_root).resolve() / "validation_execution_v1.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    if payload.get("status") != "COMPLETED" or payload.get("decision") != (
        "VALIDATION_PASSED_TEST_AUTHORIZED"
    ):
        raise ValueError("R4 frozen test is not authorized by validation")


def require_development_authorization(
    out_root: Path,
    *,
    run_id: str,
    code_revision: str,
    protocol_sha256: str,
    cases_sha256: str,
) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id):
        raise ValueError("invalid R4 development run ID")
    manifest = verify_r4_campaign(Path(out_root).resolve() / run_id)
    if (
        manifest.split != "dev"
        or manifest.code_revision != code_revision
        or manifest.protocol_sha256 != protocol_sha256
        or manifest.cases_sha256 != cases_sha256
        or not manifest.gate_checks.passed
    ):
        raise ValueError("R4 development run does not authorize validation")


if __name__ == "__main__":
    raise SystemExit(main())
