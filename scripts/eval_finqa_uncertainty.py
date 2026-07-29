try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from app.external_datasets.finqa import (
    DEFAULT_PRIVATE_ROOT,
    DEFAULT_SOURCE_ROOT,
    FINQA_DEV_SHA256,
    FINQA_REVISION,
    load_finqa_split,
)
from app.external_datasets.finqa_adjudication import (
    FinQAAdjudicationCaseEvaluation,
    verify_finqa_adjudication_run,
)
from app.external_datasets.finqa_uncertainty import (
    FinQAUncertaintyRunManifest,
    assess_finqa_runtime_uncertainty,
    evaluate_finqa_uncertainty_case,
    publish_finqa_uncertainty_run,
    summarize_finqa_uncertainty_cases,
)


DEFAULT_UNCERTAINTY_ROOT = DEFAULT_PRIVATE_ROOT / "uncertainty_runs"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate a gold-free runtime uncertainty trigger against an "
            "immutable FinQA adjudication run."
        )
    )
    parser.add_argument("--uncertainty-run-id", required=True)
    parser.add_argument(
        "--source-adjudication-run-dir",
        type=Path,
        required=True,
    )
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=DEFAULT_UNCERTAINTY_ROOT,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code_revision = _clean_git_revision()
    source_dir = args.source_adjudication_run_dir.resolve()
    source_manifest = verify_finqa_adjudication_run(source_dir)
    if (
        source_manifest.split != "dev"
        or source_manifest.dataset_revision != FINQA_REVISION
    ):
        raise ValueError("FinQA uncertainty accepts only pinned dev runs")

    details_bytes = (source_dir / "details.jsonl").read_bytes()
    details_sha256 = hashlib.sha256(details_bytes).hexdigest()
    if details_sha256 != source_manifest.artifacts["details.jsonl"]:
        raise ValueError("FinQA adjudication details changed after verification")
    source_rows = [
        FinQAAdjudicationCaseEvaluation.model_validate_json(line)
        for line in details_bytes.decode("utf-8").splitlines()
        if line
    ]

    split_path = args.source_root.resolve() / "dataset" / "dev.json"
    cases, split_sha256 = load_finqa_split(
        split_path,
        expected_sha256=FINQA_DEV_SHA256,
    )
    if split_sha256 != source_manifest.split_sha256:
        raise ValueError("FinQA uncertainty split hash mismatch")
    cases_by_id = {case.id: case for case in cases}
    if len(cases_by_id) != len(cases):
        raise ValueError("FinQA dev case IDs are not unique")
    try:
        selected_cases = [cases_by_id[row.case_id] for row in source_rows]
    except KeyError as exc:
        raise ValueError(
            "FinQA uncertainty source references an unknown case"
        ) from exc

    rows = []
    for case, source in zip(selected_cases, source_rows, strict=True):
        signal = assess_finqa_runtime_uncertainty(case, source.baseline)
        rows.append(evaluate_finqa_uncertainty_case(source, signal))
    summary = summarize_finqa_uncertainty_cases(rows)
    source_manifest_sha256 = hashlib.sha256(
        (source_dir / "manifest.json").read_bytes()
    ).hexdigest()
    manifest = FinQAUncertaintyRunManifest(
        uncertainty_run_id=args.uncertainty_run_id,
        source_adjudication_run_id=source_manifest.adjudication_run_id,
        source_adjudication_manifest_sha256=source_manifest_sha256,
        source_adjudication_details_sha256=details_sha256,
        dataset_revision=source_manifest.dataset_revision,
        split="dev",
        split_sha256=source_manifest.split_sha256,
        selected_case_ids_sha256=source_manifest.selected_case_ids_sha256,
        selected_case_count=source_manifest.selected_case_count,
        retrieval_mode=source_manifest.retrieval_mode,
        source_adjudication_code_revision=(
            source_manifest.adjudication_code_revision
        ),
        uncertainty_code_revision=code_revision,
        summary=summary,
    )
    output = publish_finqa_uncertainty_run(
        root=args.out_root,
        manifest=manifest,
        details=rows,
    )
    print(
        json.dumps(
            {
                "uncertainty_run_id": args.uncertainty_run_id,
                "source_adjudication_run_id": (
                    source_manifest.adjudication_run_id
                ),
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
        raise RuntimeError(
            "FinQA uncertainty evaluation requires a clean Git worktree"
        )
    if not revision or len(revision) != 40:
        raise RuntimeError("FinQA uncertainty Git revision is unavailable")
    return revision


if __name__ == "__main__":
    raise SystemExit(main())
