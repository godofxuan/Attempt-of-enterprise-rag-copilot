try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from app.external_datasets.finqa import (
    DEFAULT_PRIVATE_ROOT,
    DEFAULT_SOURCE_ROOT,
    FINQA_DEV_SHA256,
    FINQA_REVISION,
    load_finqa_split,
    stable_sample_finqa_cases,
)
from app.external_datasets.finqa_diagnostics import (
    FinQADiagnosticManifest,
    diagnose_finqa_case,
    load_verified_finqa_details,
    publish_finqa_diagnostic,
    summarize_finqa_diagnostics,
)
from app.external_datasets.finqa_eval import selected_case_ids_sha256


DEFAULT_DIAGNOSTIC_ROOT = DEFAULT_PRIVATE_ROOT / "diagnostic_runs"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Classify verified FinQA dev failures using official gold programs."
        )
    )
    parser.add_argument("--diagnostic-id", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=DEFAULT_DIAGNOSTIC_ROOT,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    diagnostic_revision = _clean_git_revision()
    source_manifest, evaluations, details_sha256 = (
        load_verified_finqa_details(args.run_dir)
    )
    if source_manifest.split != "dev":
        raise ValueError(
            "FinQA diagnostics refuse test runs to prevent holdout tuning"
        )
    if source_manifest.answer_strategy != "program":
        raise ValueError(
            "FinQA diagnostics require Calculator program-answer runs"
        )
    if source_manifest.dataset_revision != FINQA_REVISION:
        raise ValueError("FinQA diagnostic dataset revision mismatch")

    split_path = (
        args.source_root.resolve() / "dataset" / f"{source_manifest.split}.json"
    )
    cases, split_sha256 = load_finqa_split(
        split_path,
        expected_sha256=FINQA_DEV_SHA256,
    )
    if split_sha256 != source_manifest.split_sha256:
        raise ValueError("FinQA diagnostic split hash mismatch")
    selected = stable_sample_finqa_cases(
        cases,
        count=source_manifest.selected_case_count,
        seed=source_manifest.sample_seed,
    )
    if (
        selected_case_ids_sha256(selected)
        != source_manifest.selected_case_ids_sha256
    ):
        raise ValueError("FinQA diagnostic selected case hash mismatch")
    evaluations_by_id = {row.case_id: row for row in evaluations}
    if len(evaluations_by_id) != len(evaluations) or set(
        evaluations_by_id
    ) != {case.id for case in selected}:
        raise ValueError("FinQA diagnostic source rows do not match sample")

    rows = [
        diagnose_finqa_case(case, evaluations_by_id[case.id])
        for case in selected
    ]
    summary = summarize_finqa_diagnostics(rows)
    source_manifest_sha256 = hashlib.sha256(
        (Path(args.run_dir).resolve() / "manifest.json").read_bytes()
    ).hexdigest()
    manifest = FinQADiagnosticManifest(
        diagnostic_id=args.diagnostic_id,
        source_run_id=source_manifest.run_id,
        source_manifest_sha256=source_manifest_sha256,
        source_details_sha256=details_sha256,
        dataset_revision=source_manifest.dataset_revision,
        split="dev",
        split_sha256=source_manifest.split_sha256,
        selected_case_ids_sha256=source_manifest.selected_case_ids_sha256,
        source_code_revision=source_manifest.code_revision,
        diagnostic_code_revision=diagnostic_revision,
        retrieval_mode=source_manifest.retrieval_mode,
        summary=summary,
    )
    output = publish_finqa_diagnostic(
        root=args.out_root,
        manifest=manifest,
        details=rows,
    )
    print(
        json.dumps(
            {
                "diagnostic_id": args.diagnostic_id,
                "source_run_id": source_manifest.run_id,
                "output_dir": str(output),
                "summary": summary.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _clean_git_revision() -> str:
    root = Path(__file__).resolve().parents[1]
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("FinQA diagnostics require a clean worktree")
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("Git returned an invalid FinQA diagnostic revision")
    return revision


if __name__ == "__main__":
    raise SystemExit(main())
