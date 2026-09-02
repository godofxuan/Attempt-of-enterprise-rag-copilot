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
from app.external_datasets.uda_finance_hierarchical import FocusedPageFusionPipeline
from app.external_datasets.uda_finance_page_eval import (
    UdaFinancePageCaseResult,
    evaluate_uda_finance_pages,
    summarize_uda_finance_pages,
)
from app.external_datasets.uda_finance_r5 import (
    R5_PREPARED_ROOT,
    R5_PRIVATE_ROOT,
    R5_PROTOCOL_PATH,
    load_uda_finance_r5_cases,
    load_uda_finance_r5_protocol,
    stable_key,
    verify_uda_finance_r5_preparation,
)
from app.external_datasets.uda_finance_r5_eval import (
    build_r5_public_evidence,
    canonical_json_bytes,
    details_bytes,
)

DEFAULT_PUBLIC_EVIDENCE = Path("docs") / "r5" / "evidence" / "uda_finance_r5_public_v1.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute the one-shot UDA R5 confirmation.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prepared-root", type=Path, default=R5_PREPARED_ROOT)
    parser.add_argument("--index-root", type=Path, default=R5_PRIVATE_ROOT / "indexes")
    parser.add_argument("--out-root", type=Path, default=R5_PRIVATE_ROOT / "confirmation_runs")
    parser.add_argument("--protocol", type=Path, default=R5_PROTOCOL_PATH)
    parser.add_argument("--public-evidence", type=Path, default=DEFAULT_PUBLIC_EVIDENCE)
    parser.add_argument("--execute-confirmation", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.execute_confirmation:
        raise ValueError("R5 requires explicit --execute-confirmation")
    protocol, protocol_sha256 = load_uda_finance_r5_protocol(args.protocol)
    verify_uda_finance_r5_preparation(prepared_root=args.prepared_root)
    cases, cases_sha256 = load_uda_finance_r5_cases(args.prepared_root)
    code_revision = clean_git_revision()
    marker = claim_execution(
        args.out_root,
        run_id=args.run_id,
        code_revision=code_revision,
        protocol_sha256=protocol_sha256,
        cases_sha256=cases_sha256,
    )
    settings = get_settings().model_copy(update={"v2_indexes_dir": args.index_root.resolve()})
    runtime = build_live_runtime(settings)
    candidate_pipeline = FocusedPageFusionPipeline(
        runtime.pipeline,
        source_top_k=protocol.source_top_k,
        candidate_k=protocol.candidate_k,
        max_chunks_per_doc=protocol.max_chunks_per_doc,
        lexical_weight=protocol.lexical_weight,
        original_bm25_weight=protocol.original_bm25_weight,
        rrf_k=protocol.rrf_k,
        parallel_search=False,
        shared_scope_search=protocol.shared_scope_search,
    )
    baseline: list[UdaFinancePageCaseResult] = []
    candidate: list[UdaFinancePageCaseResult] = []
    baseline_calls = candidate_calls = 0
    ordered_cases = sorted(
        cases, key=lambda case: stable_key(protocol.selection_seed, case.case_id)
    )
    for index, case in enumerate(ordered_cases, start=1):
        candidate_first = (
            int(stable_key(protocol.selection_seed, f"arm:{case.case_id}"), 16) % 2 == 0
        )
        arms = (
            (("candidate", candidate_pipeline), ("baseline", runtime.pipeline))
            if candidate_first
            else (("baseline", runtime.pipeline), ("candidate", candidate_pipeline))
        )
        for arm, pipeline in arms:
            before = runtime.counters.embedding_calls
            result = evaluate_uda_finance_pages(
                cases=[case],
                pipeline=pipeline,
                retrieval_arm="dense",
                candidate_k=protocol.baseline_candidate_k,
                max_chunks_per_doc=protocol.baseline_max_chunks_per_doc,
                include_parent=False,
            )[0]
            calls = runtime.counters.embedding_calls - before
            if arm == "baseline":
                baseline.append(result)
                baseline_calls += calls
            else:
                candidate.append(result)
                candidate_calls += calls
        if index in {1, len(ordered_cases)} or index % 20 == 0:
            print(f"R5 paired evaluation {index}/{len(ordered_cases)}", flush=True)
    baseline.sort(key=lambda item: item.case_id)
    candidate.sort(key=lambda item: item.case_id)
    baseline_summary = summarize_uda_finance_pages(baseline, embedding_calls=baseline_calls)
    candidate_summary = summarize_uda_finance_pages(candidate, embedding_calls=candidate_calls)
    baseline_bytes = details_bytes(baseline)
    candidate_bytes = details_bytes(candidate)
    run_dir = args.out_root.resolve() / args.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "dense_chunk.jsonl").write_bytes(baseline_bytes)
    (run_dir / "focused_page_fusion.jsonl").write_bytes(candidate_bytes)
    evidence = build_r5_public_evidence(
        code_revision=code_revision,
        protocol_sha256=protocol_sha256,
        dataset_manifest_sha256=hashlib.sha256(
            (args.prepared_root.resolve() / "external_dataset_manifest.json").read_bytes()
        ).hexdigest(),
        cases_sha256=cases_sha256,
        index_run_id=runtime.snapshot.version.manifest.run_id,
        index_manifest_sha256=runtime.snapshot.version.manifest_sha256,
        embedding_model=runtime.snapshot.version.manifest.embedding.model,
        baseline=baseline,
        candidate=candidate,
        baseline_summary=baseline_summary,
        candidate_summary=candidate_summary,
        baseline_details_sha256=hashlib.sha256(baseline_bytes).hexdigest(),
        candidate_details_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
        protocol=protocol,
    )
    evidence_bytes = canonical_json_bytes(evidence)
    (run_dir / "public_evidence.json").write_bytes(evidence_bytes)
    public_path = args.public_evidence.resolve()
    public_path.parent.mkdir(parents=True, exist_ok=True)
    if public_path.exists():
        raise FileExistsError("R5 public evidence already exists")
    public_path.write_bytes(evidence_bytes)
    complete_execution(
        marker,
        decision=evidence.decision,
        public_evidence_sha256=hashlib.sha256(evidence_bytes).hexdigest(),
    )
    print(
        json.dumps(evidence.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
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
        raise ValueError("R5 confirmation requires a clean tracked Git tree")
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def claim_execution(
    out_root: Path,
    *,
    run_id: str,
    code_revision: str,
    protocol_sha256: str,
    cases_sha256: str,
) -> Path:
    root = Path(out_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "confirmation_execution_v1.json"
    payload = {
        "schema_version": "uda_finance_r5_execution_v1",
        "status": "STARTED",
        "run_id": run_id,
        "code_revision": code_revision,
        "protocol_sha256": protocol_sha256,
        "cases_sha256": cases_sha256,
    }
    with marker.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    return marker


def complete_execution(marker: Path, *, decision: str, public_evidence_sha256: str) -> None:
    payload = json.loads(marker.read_text(encoding="utf-8"))
    if payload.get("status") != "STARTED":
        raise ValueError("R5 execution marker is not STARTED")
    payload.update(
        {
            "status": "COMPLETED",
            "decision": decision,
            "public_evidence_sha256": public_evidence_sha256,
        }
    )
    temp = marker.with_suffix(".tmp")
    with temp.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, marker)


if __name__ == "__main__":
    raise SystemExit(main())
