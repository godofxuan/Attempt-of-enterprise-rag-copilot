from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.evaluation import indirect_injection_holdout as holdout
from app.evaluation.indirect_injection_holdout import (
    REQUIRED_ATTACK_FAMILIES,
    REQUIRED_RUBRIC_DIMENSIONS,
    REQUIRED_SOURCE_SURFACES,
    load_holdout_inputs,
)


HOLDOUT_ID = "r2-s2-holdout-reviewer-a-01"
FROZEN_AT = datetime(2026, 7, 19, 11, 0, 0, tzinfo=timezone.utc)
BASELINE_PATHS = (
    "app/security/retrieved_content.py",
    "app/evaluation/indirect_injection_live_runner.py",
    "app/evaluation/indirect_injection_holdout.py",
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_valid_holdout_package(root: Path) -> Path:
    submission = root / "reviewer-a-submission-01"
    submission.mkdir()
    cases: list[dict[str, object]] = []
    payload_cases: list[dict[str, object]] = []
    for index in range(36):
        label = "attack" if index < 24 else "benign"
        case_id = f"r2s2-holdout-case-{index + 1:03d}"
        payload_key = f"payload-{index + 1:03d}"
        families = (
            [REQUIRED_ATTACK_FAMILIES[index % len(REQUIRED_ATTACK_FAMILIES)]]
            if label == "attack"
            else ["benign_hard_negative"]
        )
        cases.append(
            {
                "case_id": case_id,
                "label": label,
                "families": families,
                "source_surfaces": [
                    REQUIRED_SOURCE_SURFACES[index % len(REQUIRED_SOURCE_SURFACES)]
                ],
                "language": "en" if index % 2 == 0 else "zh",
                "payload_key": payload_key,
            }
        )
        payload_cases.append(
            {
                "case_id": case_id,
                "payload_key": payload_key,
                "payload": {"opaque_fixture_reference": f"fixture-{index + 1:03d}"},
            }
        )
    _write_json(
        submission / "case_catalog.json",
        {
            "schema_version": "indirect_injection_holdout_catalog_v1",
            "holdout_id": HOLDOUT_ID,
            "cases": cases,
        },
    )
    _write_json(
        submission / "payload.json",
        {
            "schema_version": "indirect_injection_holdout_payload_v1",
            "holdout_id": HOLDOUT_ID,
            "cases": payload_cases,
        },
    )
    _write_json(
        submission / "rubric.json",
        {
            "schema_version": "indirect_injection_holdout_rubric_v1",
            "holdout_id": HOLDOUT_ID,
            "primary_reviewer_id": "reviewer-primary-a",
            "secondary_reviewer_id": "reviewer-secondary-b",
            "dimensions": [
                {
                    "name": name,
                    "labels": ["pass", "fail", "uncertain", "not_applicable"],
                    "decision_guidance": (
                        f"Apply the frozen {name} decision rule without changing "
                        "labels after model output is observed."
                    ),
                }
                for name in REQUIRED_RUBRIC_DIMENSIONS
            ],
        },
    )
    return submission


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _baseline():
    return holdout.HoldoutCodeBaseline(
        git_head="a" * 40,
        branch="codex/rag-eval-system",
        tracked_worktree_clean=True,
        artifacts={
            path: {
                "path": path,
                "sha256": hashlib.sha256(path.encode("utf-8")).hexdigest(),
            }
            for path in BASELINE_PATHS
        },
    )


def _attestation():
    return holdout.HoldoutSeparationAttestation(
        author_is_independent_of_guard_implementation=True,
        raw_payload_not_shared_before_freeze=True,
        labels_not_changed_after_model_observation=True,
        single_evaluation_per_code_baseline=True,
    )


def test_load_holdout_inputs_accepts_complete_aligned_package(
    tmp_path: Path,
) -> None:
    submission = write_valid_holdout_package(tmp_path)

    loaded = load_holdout_inputs(submission)

    assert loaded.coverage.case_count == 36
    assert loaded.coverage.attack_case_count == 24
    assert loaded.coverage.benign_case_count == 12
    assert set(loaded.coverage.attack_family_counts) == set(
        REQUIRED_ATTACK_FAMILIES
    )
    assert all(
        count >= 2 for count in loaded.coverage.attack_family_counts.values()
    )
    assert set(loaded.coverage.source_surface_counts) == set(
        REQUIRED_SOURCE_SURFACES
    )
    assert loaded.coverage.language_counts["en"] == 18
    assert loaded.coverage.language_counts["zh"] == 18


def test_holdout_rejects_duplicate_catalog_case_id(tmp_path: Path) -> None:
    submission = write_valid_holdout_package(tmp_path)
    catalog = _read_json(submission / "case_catalog.json")
    catalog["cases"][1]["case_id"] = catalog["cases"][0]["case_id"]
    _write_json(submission / "case_catalog.json", catalog)

    with pytest.raises(ValueError, match="case IDs must be unique"):
        load_holdout_inputs(submission)


def test_holdout_rejects_catalog_payload_identity_mismatch(tmp_path: Path) -> None:
    submission = write_valid_holdout_package(tmp_path)
    payload = _read_json(submission / "payload.json")
    payload["cases"][0]["case_id"] = "r2s2-holdout-unmatched-case"
    _write_json(submission / "payload.json", payload)

    with pytest.raises(ValueError, match="identities must match"):
        load_holdout_inputs(submission)


def test_holdout_rejects_insufficient_case_counts(tmp_path: Path) -> None:
    submission = write_valid_holdout_package(tmp_path)
    for name in ("case_catalog.json", "payload.json"):
        payload = _read_json(submission / name)
        payload["cases"] = payload["cases"][:-1]
        _write_json(submission / name, payload)

    with pytest.raises(ValueError):
        load_holdout_inputs(submission)


def test_holdout_rejects_missing_required_attack_family(tmp_path: Path) -> None:
    submission = write_valid_holdout_package(tmp_path)
    catalog = _read_json(submission / "case_catalog.json")
    missing = REQUIRED_ATTACK_FAMILIES[0]
    replacement = REQUIRED_ATTACK_FAMILIES[1]
    for case in catalog["cases"]:
        if case["label"] == "attack" and missing in case["families"]:
            case["families"] = [replacement]
    _write_json(submission / "case_catalog.json", catalog)

    with pytest.raises(ValueError, match="attack family"):
        load_holdout_inputs(submission)


def test_holdout_rejects_missing_required_source_surface(tmp_path: Path) -> None:
    submission = write_valid_holdout_package(tmp_path)
    catalog = _read_json(submission / "case_catalog.json")
    missing = REQUIRED_SOURCE_SURFACES[-1]
    for case in catalog["cases"]:
        if missing in case["source_surfaces"]:
            case["source_surfaces"] = [REQUIRED_SOURCE_SURFACES[0]]
    _write_json(submission / "case_catalog.json", catalog)

    with pytest.raises(ValueError, match="source surface"):
        load_holdout_inputs(submission)


def test_holdout_rejects_missing_required_language(tmp_path: Path) -> None:
    submission = write_valid_holdout_package(tmp_path)
    catalog = _read_json(submission / "case_catalog.json")
    for case in catalog["cases"]:
        case["language"] = "en"
    _write_json(submission / "case_catalog.json", catalog)

    with pytest.raises(ValueError, match="English and Chinese"):
        load_holdout_inputs(submission)


def test_holdout_rejects_benign_case_without_hard_negative_family(
    tmp_path: Path,
) -> None:
    submission = write_valid_holdout_package(tmp_path)
    catalog = _read_json(submission / "case_catalog.json")
    catalog["cases"][24]["families"] = [REQUIRED_ATTACK_FAMILIES[0]]
    _write_json(submission / "case_catalog.json", catalog)

    with pytest.raises(ValueError, match="benign_hard_negative"):
        load_holdout_inputs(submission)


def test_holdout_rejects_attack_case_with_benign_family(tmp_path: Path) -> None:
    submission = write_valid_holdout_package(tmp_path)
    catalog = _read_json(submission / "case_catalog.json")
    catalog["cases"][0]["families"] = ["benign_hard_negative"]
    _write_json(submission / "case_catalog.json", catalog)

    with pytest.raises(ValueError, match="cannot use benign_hard_negative"):
        load_holdout_inputs(submission)


def test_holdout_rejects_incomplete_rubric(tmp_path: Path) -> None:
    submission = write_valid_holdout_package(tmp_path)
    rubric = _read_json(submission / "rubric.json")
    rubric["dimensions"] = rubric["dimensions"][:-1]
    _write_json(submission / "rubric.json", rubric)

    with pytest.raises(ValueError, match="rubric dimensions"):
        load_holdout_inputs(submission)


def test_holdout_rejects_same_primary_and_secondary_reviewer(
    tmp_path: Path,
) -> None:
    submission = write_valid_holdout_package(tmp_path)
    rubric = _read_json(submission / "rubric.json")
    rubric["secondary_reviewer_id"] = rubric["primary_reviewer_id"]
    _write_json(submission / "rubric.json", rubric)

    with pytest.raises(ValueError, match="reviewers must be distinct"):
        load_holdout_inputs(submission)


def test_holdout_rejects_extra_draft_file(tmp_path: Path) -> None:
    submission = write_valid_holdout_package(tmp_path)
    (submission / "notes.txt").write_text("not admitted\n", encoding="utf-8")

    with pytest.raises(ValueError, match="exactly three input files"):
        load_holdout_inputs(submission)


def test_freeze_and_verify_holdout_bind_inputs_coverage_and_code_baseline(
    tmp_path: Path,
) -> None:
    submission = write_valid_holdout_package(tmp_path)

    manifest_path = holdout.freeze_holdout_submission(
        submission,
        baseline=_baseline(),
        attestation=_attestation(),
        frozen_at_utc=FROZEN_AT,
    )
    verified = holdout.verify_holdout_submission(
        submission,
        baseline=_baseline(),
    )

    assert manifest_path == submission / "freeze_manifest.json"
    assert {path.name for path in submission.iterdir()} == {
        "case_catalog.json",
        "payload.json",
        "rubric.json",
        "freeze_manifest.json",
    }
    assert verified.state == "FROZEN"
    assert verified.submission_id == submission.name
    assert verified.holdout_id == HOLDOUT_ID
    assert verified.coverage.case_count == 36
    assert verified.code_baseline == _baseline()
    for name in ("case_catalog.json", "payload.json", "rubric.json"):
        assert verified.files[name].bytes == (submission / name).stat().st_size
        assert verified.files[name].sha256 == hashlib.sha256(
            (submission / name).read_bytes()
        ).hexdigest()


def test_holdout_freeze_is_immutable(tmp_path: Path) -> None:
    submission = write_valid_holdout_package(tmp_path)
    holdout.freeze_holdout_submission(
        submission,
        baseline=_baseline(),
        attestation=_attestation(),
        frozen_at_utc=FROZEN_AT,
    )

    with pytest.raises(FileExistsError, match="already frozen"):
        holdout.freeze_holdout_submission(
            submission,
            baseline=_baseline(),
            attestation=_attestation(),
            frozen_at_utc=FROZEN_AT,
        )


def test_holdout_verify_rejects_post_freeze_payload_tampering(
    tmp_path: Path,
) -> None:
    submission = write_valid_holdout_package(tmp_path)
    holdout.freeze_holdout_submission(
        submission,
        baseline=_baseline(),
        attestation=_attestation(),
        frozen_at_utc=FROZEN_AT,
    )
    payload = _read_json(submission / "payload.json")
    payload["cases"][0]["payload"]["opaque_fixture_reference"] = "tampered"
    _write_json(submission / "payload.json", payload)

    with pytest.raises(ValueError, match="contradicts current package bytes"):
        holdout.verify_holdout_submission(submission, baseline=_baseline())


def test_holdout_verify_rejects_code_baseline_mismatch(tmp_path: Path) -> None:
    submission = write_valid_holdout_package(tmp_path)
    holdout.freeze_holdout_submission(
        submission,
        baseline=_baseline(),
        attestation=_attestation(),
        frozen_at_utc=FROZEN_AT,
    )
    other_baseline = _baseline().model_copy(update={"git_head": "b" * 40})

    with pytest.raises(ValueError, match="code baseline"):
        holdout.verify_holdout_submission(
            submission,
            baseline=other_baseline,
        )


def test_holdout_verify_rejects_renamed_submission_directory(
    tmp_path: Path,
) -> None:
    submission = write_valid_holdout_package(tmp_path)
    holdout.freeze_holdout_submission(
        submission,
        baseline=_baseline(),
        attestation=_attestation(),
        frozen_at_utc=FROZEN_AT,
    )
    renamed = submission.with_name("renamed-submission-02")
    submission.rename(renamed)

    with pytest.raises(ValueError, match="directory contradicts manifest"):
        holdout.verify_holdout_submission(renamed, baseline=_baseline())


def test_holdout_verify_rejects_extra_frozen_file(tmp_path: Path) -> None:
    submission = write_valid_holdout_package(tmp_path)
    holdout.freeze_holdout_submission(
        submission,
        baseline=_baseline(),
        attestation=_attestation(),
        frozen_at_utc=FROZEN_AT,
    )
    (submission / "results.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="four frozen files"):
        holdout.verify_holdout_submission(submission, baseline=_baseline())


def test_holdout_verify_requires_manifest(tmp_path: Path) -> None:
    submission = write_valid_holdout_package(tmp_path)

    with pytest.raises(FileNotFoundError, match="freeze manifest not found"):
        holdout.verify_holdout_submission(submission, baseline=_baseline())


@pytest.mark.parametrize(
    "field",
    (
        "author_is_independent_of_guard_implementation",
        "raw_payload_not_shared_before_freeze",
        "labels_not_changed_after_model_observation",
        "single_evaluation_per_code_baseline",
    ),
)
def test_holdout_attestation_requires_every_statement_true(field: str) -> None:
    payload = _attestation().model_dump(mode="python")
    payload[field] = False

    with pytest.raises(ValueError):
        holdout.HoldoutSeparationAttestation.model_validate(payload)


def test_holdout_code_baseline_requires_clean_tracked_tree() -> None:
    payload = _baseline().model_dump(mode="python")
    payload["tracked_worktree_clean"] = False

    with pytest.raises(ValueError):
        holdout.HoldoutCodeBaseline.model_validate(payload)
