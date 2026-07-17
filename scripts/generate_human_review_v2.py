try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path

from app.config import get_settings
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
        description="Generate a private blank dev+test human-review sheet."
    )
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
    parser.add_argument("--min-rows", type=int, default=30)
    parser.add_argument("--max-rows", type=int, default=50)
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
    verify_frozen_test_hash(args.eval_dir)
    dev_path, dev_cases = load_eval_cases(args.eval_dir, "dev")
    test_path, test_cases = load_eval_cases(args.eval_dir, "test")
    cases = [*dev_cases, *test_cases]
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("dev and test case IDs must be disjoint")
    corpus_dir = args.corpus_dir.resolve()
    if not (corpus_dir / "manifest.json").is_file():
        raise FileNotFoundError(f"corpus manifest not found: {corpus_dir}")

    if args.mode == "deterministic":
        with tempfile.TemporaryDirectory(prefix="e4-human-review-runtime-") as temp_dir:
            runtime = build_deterministic_runtime(corpus_dir, Path(temp_dir))
            output = _run_and_publish(
                args,
                cases,
                dev_path,
                test_path,
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
            dev_path,
            test_path,
            corpus_dir,
            runtime,
            out_root,
        )
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "suite": "human_review",
                "split": "regression",
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
    dev_path: Path,
    test_path: Path,
    corpus_dir: Path,
    runtime,
    out_root: Path,
) -> Path:
    private_answers: dict[str, str] = {}
    base = evaluate_suite(
        cases,
        runtime,
        run_id=args.run_id,
        suite="all",
        split="regression",
        top_k=args.top_k,
        candidate_k=args.candidate_k,
        bootstrap_iterations=0,
        response_sink=private_answers,
    )
    review_rows = build_human_review_rows(
        cases,
        base.details,
        private_answers,
        min_rows=args.min_rows,
        max_rows=args.max_rows,
    )
    payload = base.model_dump(mode="json")
    payload["suite"] = "human_review"
    payload["summary"] = {
        **base.summary,
        "human_review_row_count": len(review_rows),
        "human_judgements_completed": 0,
    }
    payload["config"] = {
        **base.config,
        "review_scope": "dev+test regression",
        "min_rows": args.min_rows,
        "max_rows": args.max_rows,
    }
    result = EvaluationRunResult.model_validate(payload)
    dev_payload = json.loads(dev_path.read_text(encoding="utf-8"))
    test_payload = json.loads(test_path.read_text(encoding="utf-8"))
    datasets = [
        {
            "split": "dev",
            "path": str(dev_path),
            "sha256": _sha256(dev_path),
            "case_count": len(dev_payload),
        },
        {
            "split": "test",
            "path": str(test_path),
            "sha256": _sha256(test_path),
            "case_count": len(test_payload),
        },
    ]
    manifest = build_run_manifest(
        run_id=args.run_id,
        suite="human_review",
        split="regression",
        mode=args.mode,
        dataset_path=test_path,
        corpus_dir=corpus_dir,
        index_root=runtime.index_root,
        config={
            "datasets": datasets,
            "review_row_count": len(review_rows),
            "human_judgements_completed": 0,
            "top_k": args.top_k,
            "candidate_k": args.candidate_k,
        },
        runtime=runtime.metadata(),
        repository_root=BASE_DIR,
    )
    return publish_run(
        out_root,
        manifest,
        result,
        human_review_rows=review_rows,
    )


def _validate_args(args: argparse.Namespace) -> None:
    if args.run_id in {".", ".."} or not _RUN_ID_PATTERN.fullmatch(args.run_id):
        raise ValueError("run ID contains unsafe characters")
    if args.top_k < 1 or args.top_k > 20:
        raise ValueError("top-k must be between 1 and 20")
    if args.candidate_k < args.top_k or args.candidate_k > 200:
        raise ValueError("candidate-k must be between top-k and 200")
    if args.min_rows < 1 or args.max_rows < args.min_rows:
        raise ValueError("human review row bounds are invalid")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
