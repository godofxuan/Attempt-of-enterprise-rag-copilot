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
from app.corpus.schemas import EvalCase
from app.evaluation.run_manifest import build_run_manifest
from app.evaluation.runtime import (
    build_deterministic_runtime,
    build_live_runtime,
)
from app.evaluation.suite import evaluate_suite
from app.evaluation.writer import publish_run


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS_DIR = BASE_DIR / "data" / "generated" / "demo"
DEFAULT_EVAL_DIR = BASE_DIR / "data" / "v2" / "eval"
DEFAULT_OUT_DIR = BASE_DIR / "eval_runs"
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run layered Enterprise Agentic RAG v2 evaluation."
    )
    parser.add_argument(
        "--suite",
        choices=["retrieval", "answer", "agent", "security", "all"],
        default="all",
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
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260716)
    return parser


def load_eval_cases(eval_dir: Path, split: str) -> tuple[Path, list[EvalCase]]:
    path = Path(eval_dir).resolve() / f"{split}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("evaluation dataset must be a JSON array")
    return path, [EvalCase.model_validate(item) for item in payload]


def verify_frozen_test_hash(eval_dir: Path) -> tuple[str, str]:
    eval_dir = Path(eval_dir).resolve()
    manifest_path = eval_dir / "test_manifest.sha256"
    test_path = eval_dir / "test.json"
    line = manifest_path.read_text(encoding="utf-8").strip()
    parts = line.split()
    if (
        len(parts) != 2
        or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0])
        or parts[1] != "test.json"
    ):
        raise ValueError("invalid frozen test hash manifest")
    expected = parts[0].casefold()
    actual = hashlib.sha256(test_path.read_bytes()).hexdigest()
    if expected != actual:
        raise ValueError(
            f"frozen test hash mismatch: expected {expected}, actual {actual}"
        )
    return expected, actual


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
        with tempfile.TemporaryDirectory(prefix="e4-eval-runtime-") as temp_dir:
            runtime = build_deterministic_runtime(
                corpus_dir,
                Path(temp_dir),
            )
            output = _evaluate_and_publish(
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
        output = _evaluate_and_publish(
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
                "suite": args.suite,
                "split": args.split,
                "mode": args.mode,
                "output_dir": str(output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _evaluate_and_publish(
    args: argparse.Namespace,
    cases: list[EvalCase],
    dataset_path: Path,
    corpus_dir: Path,
    runtime,
    out_root: Path,
) -> Path:
    result = evaluate_suite(
        cases,
        runtime,
        run_id=args.run_id,
        suite=args.suite,
        split=args.split,
        top_k=args.top_k,
        candidate_k=args.candidate_k,
        bootstrap_iterations=args.bootstrap_iterations,
        bootstrap_seed=args.bootstrap_seed,
    )
    config = {
        **result.config,
        "suite": args.suite,
        "split": args.split,
        "mode": args.mode,
        "dataset_file": dataset_path.name,
    }
    manifest = build_run_manifest(
        run_id=args.run_id,
        suite=args.suite,
        split=args.split,
        mode=args.mode,
        dataset_path=dataset_path,
        corpus_dir=corpus_dir,
        index_root=runtime.index_root,
        config=config,
        runtime=runtime.metadata(),
        repository_root=BASE_DIR,
    )
    return publish_run(out_root, manifest, result)


def _validate_args(args: argparse.Namespace) -> None:
    if args.run_id in {".", ".."} or not _RUN_ID_PATTERN.fullmatch(args.run_id):
        raise ValueError("run ID contains unsafe characters")
    if args.top_k < 1 or args.top_k > 20:
        raise ValueError("top-k must be between 1 and 20")
    if args.candidate_k < args.top_k or args.candidate_k > 200:
        raise ValueError("candidate-k must be between top-k and 200")
    if args.bootstrap_iterations < 0:
        raise ValueError("bootstrap iterations must be non-negative")


if __name__ == "__main__":
    raise SystemExit(main())
