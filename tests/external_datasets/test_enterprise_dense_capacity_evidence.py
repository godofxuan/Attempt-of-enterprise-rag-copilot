from __future__ import annotations

import json
from pathlib import Path

from scripts.publish_enterprise_dense_capacity import build_public_evidence


ROOT = Path(__file__).resolve().parents[2]


def test_published_dense_capacity_is_complete_and_no_go() -> None:
    payload = json.loads(
        (
            ROOT
            / "docs"
            / "rapid_upgrade"
            / "evidence"
            / "ENTERPRISE_DENSE_CAPACITY_PUBLIC.json"
        ).read_text(encoding="utf-8")
    )

    assert [item["chunk_count"] for item in payload["checkpoints"]] == [
        1_000,
        10_000,
        50_000,
    ]
    assert all(item["error_count"] == 0 for item in payload["checkpoints"])
    decision = payload["capacity_decision"]
    assert decision["decision"] == "FULL_DENSE_NO_GO"
    assert decision["projected_embedding_hours"] > 8
    assert payload["claim_boundary"]["retrieval_quality_measured"] is False
    assert payload["claim_boundary"]["resume_quality_claim_allowed"] is False


def test_dense_publication_rejects_quality_label_consumption() -> None:
    run = {"quality_labels_used": True}

    try:
        build_public_evidence(run, private_summary_sha256="a" * 64)
    except ValueError as exc:
        assert "must not consume quality labels" in str(exc)
    else:
        raise AssertionError("publication accepted a quality-label capacity run")
