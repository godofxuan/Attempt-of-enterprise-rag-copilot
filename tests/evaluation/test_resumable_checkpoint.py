import json
import shutil

import pytest
from pydantic import BaseModel

from app.evaluation.resumable_checkpoint import (
    ResumableCaseCheckpoint,
    run_resumable_cases,
)


class ExampleRow(BaseModel):
    case_id: str
    value: int


def test_completed_rows_survive_process_restart(tmp_path) -> None:
    checkpoint = ResumableCaseCheckpoint.open(
        root=tmp_path,
        run_id="example-run",
        contract={"source_sha256": "a" * 64, "model": "qwen3:8b"},
        expected_case_ids=["case-1", "case-2"],
    )
    checkpoint.append(ExampleRow(case_id="case-1", value=10))
    checkpoint.append(ExampleRow(case_id="case-2", value=20))

    reopened = ResumableCaseCheckpoint.open(
        root=tmp_path,
        run_id="example-run",
        contract={"source_sha256": "a" * 64, "model": "qwen3:8b"},
        expected_case_ids=["case-1", "case-2"],
    )

    assert reopened.load_rows(ExampleRow) == [
        ExampleRow(case_id="case-1", value=10),
        ExampleRow(case_id="case-2", value=20),
    ]


def test_resume_rejects_contract_drift(tmp_path) -> None:
    ResumableCaseCheckpoint.open(
        root=tmp_path,
        run_id="example-run",
        contract={"model_sha256": "a" * 64, "prompt_version": "v1"},
        expected_case_ids=["case-1"],
    )

    with pytest.raises(ValueError, match="contract does not match"):
        ResumableCaseCheckpoint.open(
            root=tmp_path,
            run_id="example-run",
            contract={"model_sha256": "b" * 64, "prompt_version": "v1"},
            expected_case_ids=["case-1"],
        )


def test_sealed_checkpoint_is_auditable_but_cannot_be_extended(
    tmp_path,
) -> None:
    checkpoint = ResumableCaseCheckpoint.open(
        root=tmp_path,
        run_id="example-run",
        contract={"source_sha256": "a" * 64},
        expected_case_ids=["case-1"],
    )
    checkpoint.append(ExampleRow(case_id="case-1", value=10))
    checkpoint.seal(
        final_manifest_sha256="b" * 64,
        final_details_sha256="c" * 64,
    )

    reopened = ResumableCaseCheckpoint.open(
        root=tmp_path,
        run_id="example-run",
        contract={"source_sha256": "a" * 64},
        expected_case_ids=["case-1"],
    )
    assert reopened.load_rows(ExampleRow) == [
        ExampleRow(case_id="case-1", value=10)
    ]
    with pytest.raises(ValueError, match="sealed"):
        reopened.append(ExampleRow(case_id="case-1", value=20))


def test_resume_rejects_a_tampered_completed_row(tmp_path) -> None:
    checkpoint = ResumableCaseCheckpoint.open(
        root=tmp_path,
        run_id="example-run",
        contract={"source_sha256": "a" * 64},
        expected_case_ids=["case-1"],
    )
    checkpoint.append(ExampleRow(case_id="case-1", value=10))
    record_path = (
        tmp_path / "example-run" / "records" / "000001.json"
    )
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["row"]["value"] = 999
    record_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match="row hash mismatch"):
        ResumableCaseCheckpoint.open(
            root=tmp_path,
            run_id="example-run",
            contract={"source_sha256": "a" * 64},
            expected_case_ids=["case-1"],
        )


def test_resumable_runner_does_not_recompute_completed_cases(
    tmp_path,
) -> None:
    checkpoint = ResumableCaseCheckpoint.open(
        root=tmp_path,
        run_id="example-run",
        contract={"source_sha256": "a" * 64},
        expected_case_ids=["case-1", "case-2", "case-3"],
    )
    checkpoint.append(ExampleRow(case_id="case-1", value=10))
    evaluated = []

    rows = run_resumable_cases(
        checkpoint=checkpoint,
        row_type=ExampleRow,
        cases=["case-1", "case-2", "case-3"],
        evaluate=lambda index, case_id: (
            evaluated.append((index, case_id))
            or ExampleRow(case_id=case_id, value=index * 10)
        ),
    )

    assert evaluated == [(1, "case-2"), (2, "case-3")]
    assert [row.case_id for row in rows] == [
        "case-1",
        "case-2",
        "case-3",
    ]


def test_resume_fails_closed_on_an_unexpected_extra_record(tmp_path) -> None:
    checkpoint = ResumableCaseCheckpoint.open(
        root=tmp_path,
        run_id="example-run",
        contract={"source_sha256": "a" * 64},
        expected_case_ids=["case-1"],
    )
    checkpoint.append(ExampleRow(case_id="case-1", value=10))
    records = tmp_path / "example-run" / "records"
    shutil.copyfile(records / "000001.json", records / "000002.json")

    with pytest.raises(ValueError, match="checkpoint"):
        ResumableCaseCheckpoint.open(
            root=tmp_path,
            run_id="example-run",
            contract={"source_sha256": "a" * 64},
            expected_case_ids=["case-1"],
        )
