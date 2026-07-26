from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.lifecycle.evidence import (
    EXPERIMENT_PREREGISTRATION_FIELDS,
    ExperimentRecord,
    append_jsonl_record,
    load_jsonl_records,
    validate_experiment_history,
)


DATASET_SHA256 = "a" * 64


def _registered_experiment(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "experiment_id": "EXP-LC-001",
        "registered_at": datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc),
        "status": "REGISTERED",
        "hypothesis": "The bounded validator rejects mutated accepted evidence.",
        "baseline": "No lifecycle evidence validator.",
        "intervention": "Strict schemas and accepted-prefix hashes.",
        "controlled_variables": ["dataset", "runtime", "command"],
        "dataset_id": "lifecycle-evidence-fixture-v1",
        "dataset_sha256": DATASET_SHA256,
        "sample_size": 6,
        "repetitions": 1,
        "metrics": ["invalid_records_rejected"],
        "success_thresholds": {"invalid_records_rejected": 1.0},
        "failure_thresholds": {"invalid_records_rejected": 0.99},
        "environment": {"mode": "deterministic"},
        "commands": ["python -m pytest tests/lifecycle -q"],
        "raw_artifact_paths": [],
        "raw_artifact_hashes": [],
        "result_summary": {},
        "uncertainty": {},
        "final_status": None,
        "decision": "",
        "limitations": [],
        "revision_of": None,
        "revision_reason": None,
    }
    record.update(overrides)
    return record


def test_illegal_registered_experiment_with_result_is_rejected() -> None:
    with pytest.raises(ValidationError, match="REGISTERED"):
        ExperimentRecord.model_validate(
            _registered_experiment(
                final_status="SUPPORTED",
                result_summary={"invalid_records_rejected": 1.0},
                decision="Accept the validator.",
            )
        )


def test_missing_preregistration_field_is_rejected() -> None:
    record = _registered_experiment()
    del record["hypothesis"]

    with pytest.raises(ValidationError):
        ExperimentRecord.model_validate(record)


def test_append_jsonl_rejects_duplicate_identifier(tmp_path: Path) -> None:
    destination = tmp_path / "EXPERIMENTS.jsonl"
    record = ExperimentRecord.model_validate(_registered_experiment())

    append_jsonl_record(
        destination,
        record=record,
        model=ExperimentRecord,
        id_field="experiment_id",
    )

    with pytest.raises(ValueError, match="duplicate experiment_id"):
        append_jsonl_record(
            destination,
            record=record,
            model=ExperimentRecord,
            id_field="experiment_id",
        )

    loaded = load_jsonl_records(destination, ExperimentRecord)
    assert loaded == [record]
    stored = destination.read_text(encoding="utf-8")
    assert stored.endswith("\n")
    assert json.loads(stored) == record.model_dump(mode="json")


def test_experiment_revision_cannot_change_preregistered_field() -> None:
    registered = ExperimentRecord.model_validate(_registered_experiment())
    completed = ExperimentRecord.model_validate(
        _registered_experiment(
            experiment_id="EXP-LC-002",
            status="COMPLETED",
            intervention="A silently changed intervention.",
            raw_artifact_paths=["artifacts/lifecycle/g1/result.json"],
            raw_artifact_hashes=["b" * 64],
            result_summary={"invalid_records_rejected": 1.0},
            uncertainty={"method": "exact deterministic fixture"},
            final_status="SUPPORTED",
            decision="Accept the validator.",
            revision_of="EXP-LC-001",
            revision_reason="Record the observed result.",
        )
    )

    with pytest.raises(ValueError, match="preregistered field intervention"):
        validate_experiment_history([registered, completed])


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "status": "RUNNING",
                "revision_of": "EXP-LC-100",
                "revision_reason": "Execution started.",
            },
            "RUNNING v2 experiment requires started_at",
        ),
        (
            {
                "status": "RUNNING",
                "started_at": datetime(2026, 7, 26, 8, 1),
                "revision_of": "EXP-LC-100",
                "revision_reason": "Execution started.",
            },
            "started_at must include a timezone",
        ),
        (
            {
                "status": "RUNNING",
                "started_at": datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc),
                "revision_of": "EXP-LC-100",
                "revision_reason": "Execution started.",
            },
            "registered_at must be earlier than started_at",
        ),
        (
            {
                "status": "COMPLETED",
                "started_at": datetime(
                    2026, 7, 26, 8, 1, tzinfo=timezone.utc
                ),
                "result_summary": {"invalid_records_rejected": 1.0},
                "final_status": "SUPPORTED",
                "decision": "Accept the validator.",
                "revision_of": "EXP-LC-101",
                "revision_reason": "Record the observed result.",
            },
            "COMPLETED v2 experiment requires completed_at",
        ),
        (
            {
                "status": "COMPLETED",
                "started_at": datetime(
                    2026, 7, 26, 8, 1, tzinfo=timezone.utc
                ),
                "completed_at": datetime(
                    2026, 7, 26, 8, 1, tzinfo=timezone.utc
                ),
                "result_summary": {"invalid_records_rejected": 1.0},
                "final_status": "SUPPORTED",
                "decision": "Accept the validator.",
                "revision_of": "EXP-LC-101",
                "revision_reason": "Record the observed result.",
            },
            "started_at must be earlier than completed_at",
        ),
    ],
)
def test_v2_transition_timestamps_reject_missing_or_unordered_values(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        ExperimentRecord.model_validate(
            _registered_experiment(
                schema_version=2,
                experiment_id="EXP-LC-102",
                **overrides,
            )
        )


def test_repository_legacy_and_v2_transition_histories_are_both_valid() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    records = load_jsonl_records(
        repository_root / "docs" / "lifecycle" / "EXPERIMENTS.jsonl",
        ExperimentRecord,
    )

    validate_experiment_history(records)
    legacy_records = records[:6]
    current_records = records[6:]
    assert len(legacy_records) == 6
    assert {record.schema_version for record in legacy_records} == {1}
    assert all(record.started_at is None for record in legacy_records)
    assert all(record.completed_at is None for record in legacy_records)
    assert [record.experiment_id for record in current_records] == [
        "EXP-LC-007",
        "EXP-LC-008",
        "EXP-LC-009",
    ]
    assert {record.schema_version for record in current_records} == {2}
    assert [record.status.value for record in current_records] == [
        "REGISTERED",
        "RUNNING",
        "COMPLETED",
    ]

    registered = ExperimentRecord.model_validate(
        _registered_experiment(
            schema_version=2,
            experiment_id="EXP-LC-100",
        )
    )
    running = ExperimentRecord.model_validate(
        _registered_experiment(
            schema_version=2,
            experiment_id="EXP-LC-101",
            status="RUNNING",
            started_at=datetime(2026, 7, 26, 8, 1, tzinfo=timezone.utc),
            revision_of="EXP-LC-100",
            revision_reason="Execution started.",
        )
    )
    completed = ExperimentRecord.model_validate(
        _registered_experiment(
            schema_version=2,
            experiment_id="EXP-LC-102",
            status="COMPLETED",
            started_at=datetime(2026, 7, 26, 8, 1, tzinfo=timezone.utc),
            completed_at=datetime(2026, 7, 26, 8, 2, tzinfo=timezone.utc),
            raw_artifact_paths=["artifacts/lifecycle/g10/result.json"],
            raw_artifact_hashes=["b" * 64],
            result_summary={"invalid_records_rejected": 1.0},
            uncertainty={"method": "exact deterministic fixture"},
            final_status="SUPPORTED",
            decision="Accept the validator.",
            revision_of="EXP-LC-101",
            revision_reason="Record the observed result.",
        )
    )

    validate_experiment_history([registered, running, completed])
    assert "started_at" not in EXPERIMENT_PREREGISTRATION_FIELDS
    assert "completed_at" not in EXPERIMENT_PREREGISTRATION_FIELDS


def test_v2_completed_record_must_revise_running_transition() -> None:
    registered = ExperimentRecord.model_validate(
        _registered_experiment(
            schema_version=2,
            experiment_id="EXP-LC-100",
        )
    )
    completed = ExperimentRecord.model_validate(
        _registered_experiment(
            schema_version=2,
            experiment_id="EXP-LC-102",
            status="COMPLETED",
            started_at=datetime(2026, 7, 26, 8, 1, tzinfo=timezone.utc),
            completed_at=datetime(2026, 7, 26, 8, 2, tzinfo=timezone.utc),
            raw_artifact_paths=["artifacts/lifecycle/g10/result.json"],
            raw_artifact_hashes=["b" * 64],
            result_summary={"invalid_records_rejected": 1.0},
            uncertainty={"method": "exact deterministic fixture"},
            final_status="SUPPORTED",
            decision="Accept the validator.",
            revision_of="EXP-LC-100",
            revision_reason="Record the observed result.",
        )
    )

    with pytest.raises(
        ValueError,
        match="invalid parent status",
    ):
        validate_experiment_history([registered, completed])
