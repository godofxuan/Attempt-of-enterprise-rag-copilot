from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import csv
import hashlib
import hmac
import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.evaluation.quality_review import (
    QUALITY_REVIEW_SUBMISSION_FIELDS,
    QualityJudgement,
    QualityReviewSubmission,
    publish_quality_review_submission,
    verify_quality_review_packet,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a completed quality-review template and publish an "
            "immutable pseudonymous submission."
        )
    )
    parser.add_argument("--packet-dir", type=Path, required=True)
    parser.add_argument("--completed-template", type=Path, required=True)
    parser.add_argument("--reviewer-id-file", type=Path, required=True)
    parser.add_argument(
        "--identity-pepper-file",
        "--reviewer-salt-file",
        dest="identity_pepper_file",
        type=Path,
        required=True,
        help=(
            "Coordinator-held CSPRNG key shared across all reviewers in one "
            "review campaign."
        ),
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--attest-blind", action="store_true")
    parser.add_argument("--attest-independent", action="store_true")
    parser.add_argument("--fixture-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.attest_blind or not args.attest_independent:
        raise ValueError(
            "quality review requires both blind and independent attestations"
        )

    packet_dir = args.packet_dir.resolve()
    template_path = args.completed_template.resolve()
    reviewer_id_path = args.reviewer_id_file.resolve()
    identity_pepper_path = args.identity_pepper_file.resolve()
    for path in (template_path, reviewer_id_path, identity_pepper_path):
        _require_regular_file(path)

    manifest = verify_quality_review_packet(packet_dir)
    judgements = _load_completed_judgements(template_path)
    reviewer_id = unicodedata.normalize(
        "NFKC",
        reviewer_id_path.read_text(encoding="utf-8"),
    ).strip().casefold()
    if not reviewer_id:
        raise ValueError("quality review reviewer identity file is blank")
    identity_pepper = identity_pepper_path.read_bytes()
    if len(identity_pepper) < 32:
        raise ValueError(
            "quality review identity pepper must contain 32 bytes"
        )
    if len(set(identity_pepper)) < 8:
        raise ValueError(
            "quality review identity pepper is obviously weak; use a CSPRNG"
        )
    reviewer_identity_domain_sha256 = hashlib.sha256(
        identity_pepper
    ).hexdigest()
    reviewer_id_hash = hmac.new(
        identity_pepper,
        reviewer_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    submission = QualityReviewSubmission(
        packet_id=manifest.packet_id,
        packet_manifest_sha256=_sha256(packet_dir / "manifest.json"),
        reviewer_id_hash=reviewer_id_hash,
        reviewer_identity_domain_sha256=reviewer_identity_domain_sha256,
        submitted_at_utc=datetime.now(timezone.utc),
        blindness_attestation=True,
        independence_attestation=True,
        fixture_only=args.fixture_only,
        judgements=judgements,
    )
    submission_path = publish_quality_review_submission(
        args.out_dir,
        packet_dir,
        submission,
    )
    print(
        json.dumps(
            {
                "packet_id": manifest.packet_id,
                "reviewer_id_hash": reviewer_id_hash,
                "reviewer_identity_domain_sha256": (
                    reviewer_identity_domain_sha256
                ),
                "fixture_only": args.fixture_only,
                "judgement_count": len(judgements),
                "submission_path": str(submission_path),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _load_completed_judgements(path: Path) -> list[QualityJudgement]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != QUALITY_REVIEW_SUBMISSION_FIELDS:
            raise ValueError("completed quality-review template fields mismatch")
        rows = list(reader)
    if not rows:
        raise ValueError("completed quality-review template has no rows")

    judgements: list[QualityJudgement] = []
    for row_number, row in enumerate(rows, start=2):
        for controlled_field in (
            "reviewer_id_hash",
            "blindness_attestation",
            "independence_attestation",
            "submitted_at_utc",
        ):
            if row[controlled_field]:
                raise ValueError(
                    f"template row {row_number} must not set {controlled_field}"
                )
        relevance = _load_json_array(
            row["retrieval_relevance_json"],
            row_number=row_number,
        )
        payload: dict[str, Any] = {
            "review_item_id": row["review_item_id"],
            "retrieval_relevance": relevance,
            "factual_correctness": row["factual_correctness"],
            "completeness": row["completeness"],
            "citation_support": row["citation_support"],
            "refusal_appropriateness": row["refusal_appropriateness"],
            "access_safety": row["access_safety"],
            "overall_acceptability": row["overall_acceptability"],
            "primary_failure_stage": row["primary_failure_stage"],
            "rationale": row["rationale"],
        }
        judgements.append(QualityJudgement.model_validate(payload))
    return judgements


def _load_json_array(value: str, *, row_number: int) -> list[Any]:
    if not value:
        raise ValueError(
            f"template row {row_number} retrieval_relevance_json is blank"
        )
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"template row {row_number} retrieval_relevance_json is invalid"
        ) from exc
    if not isinstance(parsed, list):
        raise ValueError(
            f"template row {row_number} retrieval_relevance_json must be an array"
        )
    return parsed


def _require_regular_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"required regular file not found: {path}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
