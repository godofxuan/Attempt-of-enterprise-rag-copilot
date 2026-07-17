import argparse
import json
import sys
from pathlib import Path

from scripts import _bootstrap  # noqa: F401

from app.corpus.artifacts import preview_corpus, write_corpus
from app.corpus.generator import load_facts, load_profile


ROOT = Path(__file__).resolve().parent.parent
FACTS_PATH = ROOT / "data" / "v2" / "facts" / "company_facts_v1.json"
CONFIG_DIR = ROOT / "data" / "v2" / "config"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic synthetic enterprise corpus.",
    )
    parser.add_argument(
        "--profile",
        choices=("demo", "benchmark"),
        default="demo",
        help="Checked-in corpus profile to use.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Override the checked-in profile seed.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory. Required unless --dry-run is used.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report exact counts without writing files.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace only a directory marked by this generator's manifest.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.output_dir is None and not args.dry_run:
        parser.error("--output-dir is required unless --dry-run is used")
    if args.force and args.dry_run:
        parser.error("--force cannot be combined with --dry-run")

    facts = load_facts(FACTS_PATH)
    profile = load_profile(CONFIG_DIR / f"{args.profile}.json")
    seed = profile.seed if args.seed is None else args.seed
    try:
        if args.dry_run:
            summary = preview_corpus(facts, profile, seed=seed)
        else:
            manifest = write_corpus(
                args.output_dir,
                facts,
                profile,
                seed=seed,
                force=args.force,
            )
            summary = {
                "profile_id": manifest.profile_id,
                "seed": manifest.seed,
                "document_count": manifest.document_count,
                "eval_dev_count": profile.eval_dev_count,
                "eval_test_count": profile.eval_test_count,
                "counts_by_format": manifest.counts_by_format,
                "counts_by_source_type": manifest.counts_by_source_type,
                "counts_by_variant": manifest.counts_by_variant,
                "facts_sha256": manifest.facts_sha256,
                "profile_sha256": manifest.profile_sha256,
                "output_dir": str(args.output_dir.resolve()),
                "written": True,
            }
    except (FileExistsError, PermissionError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
