from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.external_aggregate_export import (
    AggregateEvidenceReference,
    AggregateEvidenceVerificationError,
    load_and_verify_aggregate_reference,
)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _write_fixture(root: Path) -> tuple[Path, Path]:
    artifact = root / "docs" / "evidence.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(
        _json_bytes(
            {
                "decision": "VALIDATION_REJECTED",
                "metrics": {"recall_at_5": 0.6},
                "protocol_sha256": "2" * 64,
            }
        )
    )
    reference = root / "reference.json"
    reference.write_bytes(
        _json_bytes(
            {
                "allowed_claims": ["The validation candidate was rejected."],
                "artifact_path": "docs/evidence.json",
                "artifact_schema": "example_aggregate_v1",
                "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "case_count": 200,
                "contains_private_case_payload": False,
                "decision": "VALIDATION_REJECTED",
                "evidence_id": "test-evidence-v1",
                "evidence_scope": "Aggregate retrieval validation metrics.",
                "forbidden_claims": ["The candidate improved the frozen test."],
                "formal_case_results": "INPUT_REQUIRED",
                "payload_granularity": "aggregate_only",
                "producing_code_sha": "3" * 40,
                "protocol_sha256": "2" * 64,
                "schema_version": "enterprise-rag.aggregate-evidence-reference/1.0",
                "source_ci": {
                    "conclusion": "success",
                    "run_id": 123,
                    "status": "completed",
                    "url": "https://github.com/acme/rag/actions/runs/123",
                },
                "source_repository": "https://github.com/acme/rag",
                "source_sha": "1" * 40,
            }
        )
    )
    return artifact, reference


def test_aggregate_reference_verifies_digest_and_claim_boundary(tmp_path: Path) -> None:
    _, reference_path = _write_fixture(tmp_path)

    reference = load_and_verify_aggregate_reference(
        reference_path,
        repository_root=tmp_path,
    )

    assert reference.evidence_id == "test-evidence-v1"
    assert reference.formal_case_results == "INPUT_REQUIRED"


def test_aggregate_reference_rejects_artifact_tampering(tmp_path: Path) -> None:
    artifact, reference_path = _write_fixture(tmp_path)
    artifact.write_text("{}\n", encoding="utf-8")

    with pytest.raises(AggregateEvidenceVerificationError, match="SHA-256 mismatch"):
        load_and_verify_aggregate_reference(reference_path, repository_root=tmp_path)


def test_aggregate_reference_rejects_private_case_payload(tmp_path: Path) -> None:
    artifact, reference_path = _write_fixture(tmp_path)
    artifact.write_bytes(
        _json_bytes(
            {
                "decision": "VALIDATION_REJECTED",
                "protocol_sha256": "2" * 64,
                "questions": ["private question"],
            }
        )
    )
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    reference["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    reference_path.write_bytes(_json_bytes(reference))

    with pytest.raises(AggregateEvidenceVerificationError, match="private payload keys"):
        load_and_verify_aggregate_reference(reference_path, repository_root=tmp_path)


def test_aggregate_reference_rejects_path_traversal(tmp_path: Path) -> None:
    _, reference_path = _write_fixture(tmp_path)
    payload = json.loads(reference_path.read_text(encoding="utf-8"))
    payload["artifact_path"] = "../evidence.json"

    with pytest.raises(ValidationError, match="artifact_path"):
        AggregateEvidenceReference.model_validate(payload)


def test_aggregate_reference_rejects_unknown_fields(tmp_path: Path) -> None:
    _, reference_path = _write_fixture(tmp_path)
    payload = json.loads(reference_path.read_text(encoding="utf-8"))
    payload["unexpected"] = True

    with pytest.raises(ValidationError, match="extra_forbidden"):
        AggregateEvidenceReference.model_validate(payload)
