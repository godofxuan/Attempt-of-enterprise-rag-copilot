from __future__ import annotations

import csv
import hashlib
import hmac
from pathlib import Path

import pytest

from app.evaluation.quality_review import (
    publish_quality_review_packet,
    verify_quality_review_submission,
)
from scripts import submit_quality_review
from tests.evaluation.test_quality_review import packet_spec


def test_cli_converts_completed_template_to_pseudonymous_submission(
    tmp_path: Path,
) -> None:
    packet_dir = publish_quality_review_packet(tmp_path / "packets", packet_spec())
    template = packet_dir / "submission_template.csv"
    completed = tmp_path / "completed.csv"
    with template.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        fields = list(reader.fieldnames or ())
        rows = list(reader)
    rows[0].update(
        {
            "retrieval_relevance_json": (
                '[{"source_id":"Source A","grade":"2"}]'
            ),
            "factual_correctness": "pass",
            "completeness": "pass",
            "citation_support": "pass",
            "refusal_appropriateness": "not_applicable",
            "access_safety": "pass",
            "overall_acceptability": "pass",
            "primary_failure_stage": "none",
            "rationale": "The answer is fully supported.",
        }
    )
    with completed.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    identity = tmp_path / "reviewer-id.txt"
    identity.write_text("reviewer-one\n", encoding="utf-8")
    salt = tmp_path / "reviewer-salt.bin"
    salt.write_bytes(b"\0" * 32)
    arguments = [
        "--packet-dir",
        str(packet_dir),
        "--completed-template",
        str(completed),
        "--reviewer-id-file",
        str(identity),
        "--reviewer-salt-file",
        str(salt),
        "--out-dir",
        str(tmp_path / "submissions"),
        "--attest-blind",
        "--attest-independent",
        "--fixture-only",
    ]
    with pytest.raises(ValueError, match="weak"):
        submit_quality_review.main(arguments)
    assert not (tmp_path / "submissions").exists()

    salt_bytes = bytes(range(32))
    salt.write_bytes(salt_bytes)
    expected_reviewer_hash = hmac.new(
        salt_bytes,
        b"reviewer-one",
        hashlib.sha256,
    ).hexdigest()
    expected_identity_domain = hashlib.sha256(salt_bytes).hexdigest()

    result = submit_quality_review.main(arguments)

    assert result == 0
    submission_path = next(
        (tmp_path / "submissions").glob("*/submission.json")
    )
    verified = verify_quality_review_submission(submission_path, packet_dir)
    assert verified.reviewer_id_hash == expected_reviewer_hash
    assert (
        verified.reviewer_identity_domain_sha256
        == expected_identity_domain
    )
    assert verified.fixture_only is True
    submission_text = submission_path.read_text(encoding="utf-8")
    assert "reviewer-one" not in submission_text
