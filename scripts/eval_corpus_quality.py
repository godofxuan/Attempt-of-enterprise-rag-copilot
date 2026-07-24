from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts import _bootstrap  # noqa: F401

from app.corpus.catalog import CORPUS_PROFILE_IDS, load_corpus_preset
from app.corpus.quality import (
    evaluate_corpus_quality,
    evaluate_materialized_corpus_quality,
)
from app.domain.documents import DocumentParseError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate deterministic enterprise corpus quality gates.",
    )
    parser.add_argument(
        "--profile",
        choices=CORPUS_PROFILE_IDS,
        default="expanded",
        help="Checked-in corpus preset to evaluate.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional UTF-8 JSON evidence file.",
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        help="Validate an actual generated corpus and bind its manifest hash.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing output evidence file.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        facts, profile = load_corpus_preset(args.profile)
        if args.corpus_dir is None:
            report = evaluate_corpus_quality(facts, profile)
        else:
            report = evaluate_materialized_corpus_quality(
                facts,
                profile,
                args.corpus_dir,
            )
        payload = (
            json.dumps(
                report.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        if args.output is not None:
            output_path = args.output.resolve()
            if output_path.exists() and not args.force:
                raise FileExistsError(
                    f"output evidence already exists: {output_path}"
                )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(payload, encoding="utf-8", newline="\n")
    except (DocumentParseError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(payload, end="")
    return 0 if report.release_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
