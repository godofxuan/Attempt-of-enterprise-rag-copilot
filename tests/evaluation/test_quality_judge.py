from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.evaluation.quality_judge import (
    QualityJudgeCalibration,
    QualityJudgeRun,
    calibrate_quality_judge,
    publish_quality_judge_calibration,
    verify_quality_judge_calibration,
)
from app.evaluation.quality_review import (
    QualityJudgement,
    QualityReviewSubmission,
    RetrievalRelevanceJudgement,
    publish_quality_review_evidence,
    publish_quality_review_packet,
    publish_quality_review_submission,
)
from tests.evaluation.test_quality_review import IDENTITY_DOMAIN, packet_spec


def matching_judgement() -> QualityJudgement:
    return QualityJudgement(
        review_item_id="qri_4c5db720f312",
        retrieval_relevance=[
            RetrievalRelevanceJudgement(source_id="Source A", grade="2")
        ],
        factual_correctness="pass",
        completeness="pass",
        citation_support="pass",
        refusal_appropriateness="not_applicable",
        access_safety="pass",
        overall_acceptability="pass",
        primary_failure_stage="none",
        rationale="The response is supported by the reference.",
    )


def security_failure_judgement() -> QualityJudgement:
    return QualityJudgement(
        review_item_id="qri_4c5db720f312",
        retrieval_relevance=[
            RetrievalRelevanceJudgement(source_id="Source A", grade="2")
        ],
        factual_correctness="fail",
        completeness="pass",
        citation_support="pass",
        refusal_appropriateness="not_applicable",
        access_safety="fail",
        overall_acceptability="fail",
        primary_failure_stage="access_safety",
        rationale="The response discloses content that must remain protected.",
    )


def fixture_human_evidence(
    tmp_path: Path,
    *,
    fixture_only: bool = True,
    judgement: QualityJudgement | None = None,
) -> Path:
    judgement = judgement or matching_judgement()
    packet_dir = publish_quality_review_packet(tmp_path / "packets", packet_spec())
    packet_hash = hashlib.sha256(
        (packet_dir / "manifest.json").read_bytes()
    ).hexdigest()
    submission_paths = []
    for reviewer_hash in ("c" * 64, "d" * 64):
        submission_paths.append(
            publish_quality_review_submission(
                tmp_path / "submissions",
                packet_dir,
                QualityReviewSubmission(
                    packet_id="quality-calibration-001",
                    packet_manifest_sha256=packet_hash,
                    reviewer_id_hash=reviewer_hash,
                    reviewer_identity_domain_sha256=IDENTITY_DOMAIN,
                    submitted_at_utc=datetime(
                        2026,
                        7,
                        27,
                        1,
                        tzinfo=timezone.utc,
                    ),
                    blindness_attestation=True,
                    independence_attestation=True,
                    fixture_only=fixture_only,
                    judgements=[judgement],
                ),
            )
        )
    return publish_quality_review_evidence(
        tmp_path / "evidence",
        evidence_id=(
            "human-fixture-001"
            if fixture_only
            else "human-calibration-001"
        ),
        packet_dir=packet_dir,
        submission_paths=submission_paths,
        adjudication=None,
        created_at_utc=datetime(2026, 7, 27, 2, tzinfo=timezone.utc),
    )


def test_three_matching_judge_trials_remain_fixture_only(
    tmp_path: Path,
) -> None:
    evidence_dir = fixture_human_evidence(tmp_path)
    evidence_hash = hashlib.sha256(
        (evidence_dir / "manifest.json").read_bytes()
    ).hexdigest()
    packet_manifest = next(
        (evidence_dir / "packet").glob("*/manifest.json")
    )
    packet_hash = hashlib.sha256(packet_manifest.read_bytes()).hexdigest()
    judge_runs = [
        QualityJudgeRun(
            run_id=f"judge-fixture-{trial}",
            human_evidence_manifest_sha256=evidence_hash,
            packet_id="quality-calibration-001",
            packet_manifest_sha256=packet_hash,
            provider="ollama_local",
            judge_model_name="judge-fixture",
            judge_model_digest="a" * 64,
            judge_model_family="fixture-family",
            answer_model_family="different-fixture-family",
            prompt_sha256="b" * 64,
            inference_config_sha256="c" * 64,
            trial_index=trial,
            created_at_utc=datetime(
                2026,
                7,
                27,
                3 + trial,
                tzinfo=timezone.utc,
            ),
            retrieved_content_is_data_attestation=True,
            security_gate_authority="none",
            fixture_only=True,
            judgements=[matching_judgement()],
        )
        for trial in range(3)
    ]

    calibration = calibrate_quality_judge(evidence_dir, judge_runs)

    assert isinstance(calibration, QualityJudgeCalibration)
    assert calibration.status == "FIXTURE_ONLY"
    assert calibration.trial_count == 3
    assert calibration.raw_label_agreement == 1.0
    assert calibration.overall_acceptability_agreement == 1.0
    assert calibration.judge_stability == 1.0
    assert calibration.false_pass_count == 0
    assert calibration.security_false_pass_count == 0
    assert calibration.release_authority is False

    calibration_dir = publish_quality_judge_calibration(
        tmp_path / "judge-calibrations",
        calibration_id="judge-calibration-fixture-001",
        human_evidence_dir=evidence_dir,
        judge_runs=judge_runs,
        created_at_utc=datetime(2026, 7, 27, 7, tzinfo=timezone.utc),
    )
    recomputed = verify_quality_judge_calibration(
        calibration_dir,
        evidence_dir,
    )
    assert recomputed == calibration


def test_same_family_judge_is_inconclusive(
    tmp_path: Path,
) -> None:
    evidence_dir = fixture_human_evidence(tmp_path, fixture_only=False)
    evidence_hash = hashlib.sha256(
        (evidence_dir / "manifest.json").read_bytes()
    ).hexdigest()
    packet_manifest = next(
        (evidence_dir / "packet").glob("*/manifest.json")
    )
    packet_hash = hashlib.sha256(packet_manifest.read_bytes()).hexdigest()
    runs = [
        QualityJudgeRun(
            run_id=f"same-family-{trial}",
            human_evidence_manifest_sha256=evidence_hash,
            packet_id="quality-calibration-001",
            packet_manifest_sha256=packet_hash,
            provider="ollama_local",
            judge_model_name="same-family-judge",
            judge_model_digest="a" * 64,
            judge_model_family="shared-family",
            answer_model_family="shared-family",
            prompt_sha256="b" * 64,
            inference_config_sha256="c" * 64,
            trial_index=trial,
            created_at_utc=datetime(
                2026,
                7,
                27,
                3 + trial,
                tzinfo=timezone.utc,
            ),
            retrieved_content_is_data_attestation=True,
            security_gate_authority="none",
            fixture_only=False,
            judgements=[matching_judgement()],
        )
        for trial in range(3)
    ]

    calibration = calibrate_quality_judge(evidence_dir, runs)

    assert calibration.status == "INCONCLUSIVE"
    assert "same_model_family_correlation" in calibration.risk_flags
    assert "same_model_family_correlation" in calibration.decision_reasons


def test_judge_stability_uses_all_trial_pairs(
    tmp_path: Path,
) -> None:
    evidence_dir = fixture_human_evidence(tmp_path)
    evidence_hash = hashlib.sha256(
        (evidence_dir / "manifest.json").read_bytes()
    ).hexdigest()
    packet_manifest = next(
        (evidence_dir / "packet").glob("*/manifest.json")
    )
    packet_hash = hashlib.sha256(packet_manifest.read_bytes()).hexdigest()
    trial_judgements = [
        matching_judgement(),
        security_failure_judgement(),
        security_failure_judgement(),
    ]
    runs = [
        QualityJudgeRun(
            run_id=f"pairwise-stability-{trial}",
            human_evidence_manifest_sha256=evidence_hash,
            packet_id="quality-calibration-001",
            packet_manifest_sha256=packet_hash,
            provider="ollama_local",
            judge_model_name="judge-model",
            judge_model_digest="a" * 64,
            judge_model_family="judge-family",
            answer_model_family="answer-family",
            prompt_sha256="b" * 64,
            inference_config_sha256="c" * 64,
            trial_index=trial,
            created_at_utc=datetime(
                2026,
                7,
                27,
                3 + trial,
                tzinfo=timezone.utc,
            ),
            retrieved_content_is_data_attestation=True,
            security_gate_authority="none",
            fixture_only=True,
            judgements=[judgement],
        )
        for trial, judgement in enumerate(trial_judgements)
    ]

    calibration = calibrate_quality_judge(evidence_dir, runs)

    assert calibration.status == "FIXTURE_ONLY"
    assert calibration.judge_stability == pytest.approx(2 / 3)


def test_security_false_passes_are_counted_and_fail_calibration(
    tmp_path: Path,
) -> None:
    evidence_dir = fixture_human_evidence(
        tmp_path,
        fixture_only=False,
        judgement=security_failure_judgement(),
    )
    evidence_hash = hashlib.sha256(
        (evidence_dir / "manifest.json").read_bytes()
    ).hexdigest()
    packet_manifest = next(
        (evidence_dir / "packet").glob("*/manifest.json")
    )
    packet_hash = hashlib.sha256(packet_manifest.read_bytes()).hexdigest()
    runs = [
        QualityJudgeRun(
            run_id=f"security-false-pass-{trial}",
            human_evidence_manifest_sha256=evidence_hash,
            packet_id="quality-calibration-001",
            packet_manifest_sha256=packet_hash,
            provider="ollama_local",
            judge_model_name="judge-model",
            judge_model_digest="a" * 64,
            judge_model_family="judge-family",
            answer_model_family="answer-family",
            prompt_sha256="b" * 64,
            inference_config_sha256="c" * 64,
            trial_index=trial,
            created_at_utc=datetime(
                2026,
                7,
                27,
                3 + trial,
                tzinfo=timezone.utc,
            ),
            retrieved_content_is_data_attestation=True,
            security_gate_authority="none",
            fixture_only=False,
            judgements=[matching_judgement()],
        )
        for trial in range(3)
    ]

    calibration = calibrate_quality_judge(evidence_dir, runs)

    assert calibration.status == "FAILED"
    assert calibration.false_pass_count == 3
    assert calibration.security_false_pass_count == 3
    assert (
        "security_false_pass_count_above_maximum"
        in calibration.decision_reasons
    )


def test_one_real_judge_trial_is_inconclusive_even_when_labels_match(
    tmp_path: Path,
) -> None:
    evidence_dir = fixture_human_evidence(tmp_path, fixture_only=False)
    evidence_hash = hashlib.sha256(
        (evidence_dir / "manifest.json").read_bytes()
    ).hexdigest()
    packet_manifest = next(
        (evidence_dir / "packet").glob("*/manifest.json")
    )
    run = QualityJudgeRun(
        run_id="judge-single-trial",
        human_evidence_manifest_sha256=evidence_hash,
        packet_id="quality-calibration-001",
        packet_manifest_sha256=hashlib.sha256(
            packet_manifest.read_bytes()
        ).hexdigest(),
        provider="ollama_local",
        judge_model_name="judge-fixture",
        judge_model_digest="a" * 64,
        judge_model_family="judge-family",
        answer_model_family="answer-family",
        prompt_sha256="b" * 64,
        inference_config_sha256="c" * 64,
        trial_index=0,
        created_at_utc=datetime(2026, 7, 27, 3, tzinfo=timezone.utc),
        retrieved_content_is_data_attestation=True,
        security_gate_authority="none",
        fixture_only=False,
        judgements=[matching_judgement()],
    )

    calibration = calibrate_quality_judge(evidence_dir, [run])

    assert calibration.status == "INCONCLUSIVE"
    assert "judge_trial_count_below_minimum" in calibration.decision_reasons
    assert "judge_stability_undefined" in calibration.decision_reasons
    assert calibration.release_authority is False
