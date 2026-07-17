try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
import re
import tempfile
from pathlib import Path

from app.config import get_settings
from app.evaluation.ablation import run_ablation
from app.evaluation.contracts import EvaluationRunResult
from app.evaluation.human_review import build_human_review_rows
from app.evaluation.run_manifest import build_run_manifest
from app.evaluation.runtime import (
    build_deterministic_runtime,
    build_live_runtime,
)
from app.evaluation.suite import evaluate_suite
from app.evaluation.writer import publish_run
from scripts.eval_enterprise_v2 import (
    BASE_DIR,
    DEFAULT_CORPUS_DIR,
    DEFAULT_EVAL_DIR,
    DEFAULT_OUT_DIR,
    load_eval_cases,
    verify_frozen_test_hash,
)


_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run controlled Enterprise Agentic RAG v2 ablations."
    )
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument(
        "--mode",
        choices=["deterministic", "live"],
        default="deterministic",
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--eval-dir", type=Path, default=DEFAULT_EVAL_DIR)
    parser.add_argument("--index-root", type=Path)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=20)
    parser.add_argument(
        "--human-review",
        action="store_true",
        help="Also write a private blank human-review sheet for this split.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _validate_args(args)
    out_root = args.out_dir.resolve()
    target = (out_root / args.run_id).resolve()
    if target.parent != out_root:
        raise ValueError("run ID resolves outside output root")
    if target.exists():
        raise FileExistsError(f"output run already exists: {target}")
    if args.split == "test":
        verify_frozen_test_hash(args.eval_dir)
    dataset_path, cases = load_eval_cases(args.eval_dir, args.split)
    corpus_dir = args.corpus_dir.resolve()
    if not (corpus_dir / "manifest.json").is_file():
        raise FileNotFoundError(f"corpus manifest not found: {corpus_dir}")

    if args.mode == "deterministic":
        with tempfile.TemporaryDirectory(prefix="e4-ablation-runtime-") as temp_dir:
            runtime = build_deterministic_runtime(corpus_dir, Path(temp_dir))
            output = _run_and_publish(
                args,
                cases,
                dataset_path,
                corpus_dir,
                runtime,
                out_root,
            )
    else:
        settings = get_settings()
        if args.index_root is not None:
            settings = settings.model_copy(
                update={"v2_indexes_dir": args.index_root.resolve()}
            )
        runtime = build_live_runtime(settings)
        output = _run_and_publish(
            args,
            cases,
            dataset_path,
            corpus_dir,
            runtime,
            out_root,
        )

    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "suite": "ablation",
                "split": args.split,
                "mode": args.mode,
                "output_dir": str(output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _run_and_publish(
    args: argparse.Namespace,
    cases,
    dataset_path: Path,
    corpus_dir: Path,
    runtime,
    out_root: Path,
) -> Path:
    ablation = run_ablation(
        cases,
        runtime,
        top_k=args.top_k,
        candidate_k=args.candidate_k,
    )
    base = evaluate_suite(
        cases,
        runtime,
        run_id=args.run_id,
        suite="retrieval",
        split=args.split,
        top_k=args.top_k,
        candidate_k=args.candidate_k,
        bootstrap_iterations=0,
    )
    payload = base.model_dump(mode="json")
    payload["suite"] = "ablation"
    payload["summary"] = {
        **base.summary,
        "ablation_failure_case_ids": ablation.failure_case_ids,
        "variant_count": len(ablation.rows),
    }
    payload["config"] = {
        **base.config,
        "evaluation_kind": "controlled_ablation",
    }
    result = EvaluationRunResult.model_validate(payload)
    review_rows = []
    if args.human_review:
        review_details = [
            detail.model_copy(
                update={
                    "actual_mode": ablation.actual_mode_by_case.get(
                        detail.case_id, detail.actual_mode
                    )
                }
            )
            for detail in result.details
        ]
        review_rows = build_human_review_rows(
            cases,
            review_details,
            ablation.answer_by_case,
        )
    manifest = build_run_manifest(
        run_id=args.run_id,
        suite="ablation",
        split=args.split,
        mode=args.mode,
        dataset_path=dataset_path,
        corpus_dir=corpus_dir,
        index_root=runtime.index_root,
        config={
            "split": args.split,
            "mode": args.mode,
            "top_k": args.top_k,
            "candidate_k": args.candidate_k,
            "variants": [row.variant for row in ablation.rows],
            "human_review": args.human_review,
        },
        runtime=runtime.metadata(),
        repository_root=BASE_DIR,
    )
    return publish_run(
        out_root,
        manifest,
        result,
        ablation_rows=ablation.rows,
        human_review_rows=review_rows,
    )


def _validate_args(args: argparse.Namespace) -> None:
    if args.run_id in {".", ".."} or not _RUN_ID_PATTERN.fullmatch(args.run_id):
        raise ValueError("run ID contains unsafe characters")
    if args.top_k < 1 or args.top_k > 20:
        raise ValueError("top-k must be between 1 and 20")
    if args.candidate_k < args.top_k or args.candidate_k > 200:
        raise ValueError("candidate-k must be between top-k and 200")


if __name__ == "__main__":
    raise SystemExit(main())
