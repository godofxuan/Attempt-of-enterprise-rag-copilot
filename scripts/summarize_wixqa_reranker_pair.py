from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from app.evaluation.wixqa_paired_reranker import summarize_wixqa_reranker_pair


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create aggregate-only paired WixQA reranker statistics."
    )
    parser.add_argument("--details", type=Path, required=True)
    parser.add_argument("--expected-case-count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20_260_902)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = summarize_wixqa_reranker_pair(
        args.details,
        expected_case_count=args.expected_case_count,
        bootstrap_iterations=args.bootstrap_iterations,
        seed=args.seed,
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    output.write_text(content, encoding="utf-8")
    print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
