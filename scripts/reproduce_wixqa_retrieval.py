from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_PROTOCOL = Path(
    "docs/enterprise_eval/evidence/WIXQA_RETRIEVAL_PROTOCOL_V1.json"
)
DEFAULT_PUBLIC_OUTPUT = Path(
    "docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reproduce the frozen WixQA retrieval baseline end to end."
    )
    parser.add_argument("--run-prefix", required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument(
        "--source-root", type=Path, default=Path(".private/external/wixqa/source")
    )
    parser.add_argument(
        "--index-root", type=Path, default=Path(".private/external/wixqa/indexes")
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path(".private/external/wixqa/eval_runs")
    )
    parser.add_argument("--public-output", type=Path, default=DEFAULT_PUBLIC_OUTPUT)
    parser.add_argument("--reuse-verified-index", action="store_true")
    parser.add_argument("--publish-existing", action="store_true")
    return parser


def command_plan(args: argparse.Namespace) -> list[list[str]]:
    python = sys.executable
    run_ids = {
        cohort: f"{args.run_prefix}-{cohort}" for cohort in _cohorts()
    }
    commands: list[list[str]] = []
    if not args.publish_existing:
        commands.append(
            [
                python,
                "-m",
                "scripts.download_wixqa",
                "--source-root",
                str(args.source_root),
            ]
        )
        if not args.reuse_verified_index:
            commands.append(
                [
                    python,
                    "-m",
                    "scripts.build_wixqa_index",
                    "--source-root",
                    str(args.source_root),
                    "--output-root",
                    str(args.index_root),
                    "--run-id",
                    f"{args.run_prefix}-index",
                ]
            )
        for cohort in _cohorts():
            command = [
                python,
                "-m",
                "scripts.eval_wixqa_retrieval",
                "--cohort",
                cohort,
                "--source-root",
                str(args.source_root),
                "--index-root",
                str(args.index_root),
                "--output-root",
                str(args.output_root),
                "--run-id",
                run_ids[cohort],
            ]
            if cohort == "expertwritten":
                command.append("--consume-fixed-external")
            commands.append(command)

    metadata = args.output_root / f"{args.run_prefix}-machine.json"
    commands.append(
        [
            python,
            "-m",
            "scripts.publish_wixqa_retrieval_eval",
            "--protocol",
            str(args.protocol),
            "--synthetic-summary",
            str(args.output_root / run_ids["synthetic"] / "summary.json"),
            "--simulated-summary",
            str(args.output_root / run_ids["simulated"] / "summary.json"),
            "--expertwritten-summary",
            str(args.output_root / run_ids["expertwritten"] / "summary.json"),
            "--reproduction-metadata",
            str(metadata),
            "--output",
            str(args.public_output),
        ]
    )
    return commands


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.output_root.mkdir(parents=True, exist_ok=True)
    metadata_path = args.output_root / f"{args.run_prefix}-machine.json"
    metadata_path.write_text(
        json.dumps(_machine_metadata(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for command in command_plan(args):
        subprocess.run(command, check=True)
    return 0


def _machine_metadata() -> dict[str, object]:
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, encoding="utf-8"
        ).strip(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor() or "UNKNOWN",
        "latency_comparability": "MACHINE_SPECIFIC",
        "fixed_labels": "REGRESSION_REPLAY_NOT_NEW_HOLDOUT",
    }


def _cohorts() -> tuple[str, ...]:
    return ("synthetic", "simulated", "expertwritten")


if __name__ == "__main__":
    raise SystemExit(main())
