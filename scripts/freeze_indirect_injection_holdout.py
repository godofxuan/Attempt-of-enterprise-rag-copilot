from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from app.evaluation.indirect_injection_holdout import (
    HoldoutSeparationAttestation,
    current_holdout_code_baseline,
    freeze_holdout_submission,
    verify_holdout_submission,
)


BASE_DIR = Path(__file__).resolve().parent.parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze an independently authored local indirect-injection holdout "
            "without printing or committing raw payload content."
        )
    )
    parser.add_argument("submission_dir", type=Path)
    parser.add_argument("--frozen-at-utc", required=True)
    parser.add_argument("--author-independent", action="store_true")
    parser.add_argument("--payload-not-shared", action="store_true")
    parser.add_argument("--labels-not-tuned", action="store_true")
    parser.add_argument("--single-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    attestation_values = (
        args.author_independent,
        args.payload_not_shared,
        args.labels_not_tuned,
        args.single_run,
    )
    if not all(attestation_values):
        raise ValueError("holdout freeze requires all four separation attestations")
    baseline = current_holdout_code_baseline(BASE_DIR)
    attestation = HoldoutSeparationAttestation(
        author_is_independent_of_guard_implementation=True,
        raw_payload_not_shared_before_freeze=True,
        labels_not_changed_after_model_observation=True,
        single_evaluation_per_code_baseline=True,
    )
    frozen_at_utc = datetime.fromisoformat(
        args.frozen_at_utc.replace("Z", "+00:00")
    )
    freeze_holdout_submission(
        args.submission_dir,
        baseline=baseline,
        attestation=attestation,
        frozen_at_utc=frozen_at_utc,
    )
    manifest = verify_holdout_submission(
        args.submission_dir,
        baseline=baseline,
    )
    print(json.dumps(_receipt(manifest), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _receipt(manifest) -> dict[str, object]:
    return {
        "state": manifest.state,
        "submission_id": manifest.submission_id,
        "holdout_id": manifest.holdout_id,
        "case_count": manifest.coverage.case_count,
        "attack_case_count": manifest.coverage.attack_case_count,
        "benign_case_count": manifest.coverage.benign_case_count,
        "case_identity_sha256": manifest.coverage.case_identity_sha256,
        "input_sha256": {
            name: evidence.sha256 for name, evidence in manifest.files.items()
        },
        "git_head": manifest.code_baseline.git_head,
        "branch": manifest.code_baseline.branch,
    }


if __name__ == "__main__":
    raise SystemExit(main())
