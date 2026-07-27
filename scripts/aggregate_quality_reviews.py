from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.evaluation.quality_review import (
    QualityReviewAdjudication,
    publish_quality_review_evidence,
    verify_quality_review_evidence,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Publish and independently recompute an immutable quality-review "
            "evidence bundle."
        )
    )
    parser.add_argument("--evidence-id", required=True)
    parser.add_argument("--packet-dir", type=Path, required=True)
    parser.add_argument(
        "--submission",
        type=Path,
        action="append",
        required=True,
        help="Repeat exactly twice with two independent reviewer submissions.",
    )
    parser.add_argument("--adjudication", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if len(args.submission) != 2:
        raise ValueError("quality review v1 requires exactly two submissions")
    adjudication = _load_adjudication(args.adjudication)
    evidence_dir = publish_quality_review_evidence(
        args.out_dir,
        evidence_id=args.evidence_id,
        packet_dir=args.packet_dir,
        submission_paths=args.submission,
        adjudication=adjudication,
        created_at_utc=datetime.now(timezone.utc),
    )
    summary = verify_quality_review_evidence(evidence_dir)
    print(
        json.dumps(
            {
                "evidence_id": args.evidence_id,
                "evidence_dir": str(evidence_dir),
                "review_status": summary.review_status,
                "claim_status": summary.claim_status,
                "release_gate_reasons": summary.release_gate_reasons,
                "item_count": summary.item_count,
                "raw_label_agreement": summary.raw_label_agreement,
                "cohens_kappa": summary.cohens_kappa,
                "retrieval_weighted_kappa": (
                    summary.retrieval_weighted_kappa
                ),
                "mean_relevance_precision_at_5": (
                    summary.mean_relevance_precision_at_5
                ),
                "mean_relevance_recall_at_5": (
                    summary.mean_relevance_recall_at_5
                ),
                "mean_ndcg_at_5": summary.mean_ndcg_at_5,
                "overall_acceptance_rate": summary.overall_acceptance_rate,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _load_adjudication(path: Path | None) -> QualityReviewAdjudication | None:
    if path is None:
        return None
    resolved = path.resolve()
    if resolved.is_symlink() or not resolved.is_file():
        raise FileNotFoundError(
            f"quality review adjudication not found: {resolved}"
        )
    return QualityReviewAdjudication.model_validate_json(
        resolved.read_text(encoding="utf-8")
    )


if __name__ == "__main__":
    raise SystemExit(main())
