from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.evaluation.quality_judge import (
    QualityJudgeRun,
    publish_quality_judge_calibration,
    verify_quality_judge_calibration,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Calibrate version-pinned local LLM judge runs against immutable "
            "human consensus evidence."
        )
    )
    parser.add_argument("--calibration-id", required=True)
    parser.add_argument("--human-evidence-dir", type=Path, required=True)
    parser.add_argument(
        "--judge-run",
        type=Path,
        action="append",
        required=True,
        help="Repeat for each independently executed judge trial.",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    judge_runs = [_load_run(path) for path in args.judge_run]
    output = publish_quality_judge_calibration(
        args.out_dir,
        calibration_id=args.calibration_id,
        human_evidence_dir=args.human_evidence_dir,
        judge_runs=judge_runs,
        created_at_utc=datetime.now(timezone.utc),
    )
    result = verify_quality_judge_calibration(
        output,
        args.human_evidence_dir,
    )
    print(
        json.dumps(
            {
                "calibration_id": args.calibration_id,
                "output_dir": str(output),
                "status": result.status,
                "trial_count": result.trial_count,
                "item_count": result.item_count,
                "raw_label_agreement": result.raw_label_agreement,
                "overall_acceptability_agreement": (
                    result.overall_acceptability_agreement
                ),
                "cohens_kappa": result.cohens_kappa,
                "judge_stability": result.judge_stability,
                "false_pass_count": result.false_pass_count,
                "security_false_pass_count": (
                    result.security_false_pass_count
                ),
                "release_authority": result.release_authority,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _load_run(path: Path) -> QualityJudgeRun:
    resolved = path.resolve()
    if resolved.is_symlink() or not resolved.is_file():
        raise FileNotFoundError(f"quality judge run not found: {resolved}")
    return QualityJudgeRun.model_validate_json(
        resolved.read_text(encoding="utf-8")
    )


if __name__ == "__main__":
    raise SystemExit(main())
