from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.quality_review import (
    QualityEvidence,
    QualityJudgement,
    QualityReviewAdjudication,
    QualityReviewAggregate,
    QualityReviewItem,
    QualityReviewPacketSpec,
    QualityReviewSubmission,
    QualityReviewSource,
    RetrievalRelevanceJudgement,
    aggregate_quality_reviews,
    publish_quality_review_packet,
    publish_quality_review_evidence,
    publish_quality_review_submission,
    verify_quality_review_evidence,
    verify_quality_review_packet,
    verify_quality_review_submission,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
IDENTITY_DOMAIN = "9" * 64


def evidence(source_id: str, content: str) -> QualityEvidence:
    return QualityEvidence(
        source_id=source_id,
        title=f"Source {source_id}",
        content=content,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def packet_spec() -> QualityReviewPacketSpec:
    return QualityReviewPacketSpec(
        packet_id="quality-calibration-001",
        purpose="calibration",
        created_at_utc=datetime(2026, 7, 27, tzinfo=timezone.utc),
        source=QualityReviewSource(
            run_id="live-dev-001",
            run_manifest_sha256=SHA_A,
            dataset_sha256=SHA_B,
            dataset_split="dev",
            git_commit="1" * 40,
        ),
        sampling_strategy="error_enriched",
        sampling_seed=1729,
        items=[
            QualityReviewItem(
                review_item_id="qri_4c5db720f312",
                question="What is the current remote-work limit?",
                system_answer="The current limit is three days [Source A].",
                expected_response_mode="answered",
                reference_answer="Three days.",
                retrieved_evidence=[
                    evidence("Source A", "Employees may work remotely three days.")
                ],
                reference_evidence=[
                    evidence("Source A", "Employees may work remotely three days.")
                ],
            )
        ],
    )


def test_packet_publication_is_blinded_immutable_and_self_verifying(
    tmp_path: Path,
) -> None:
    output = publish_quality_review_packet(tmp_path, packet_spec())

    verified = verify_quality_review_packet(output)
    assert verified.packet_id == "quality-calibration-001"
    assert verified.item_count == 1
    assert verified.claim_status == "NOT_RUN"
    assert verified.minimum_independent_reviewers == 2

    item_text = (output / "review_items.jsonl").read_text(encoding="utf-8")
    assert "source_case_id" not in item_text
    assert "model_identity" not in item_text
    assert "machine_passed" not in item_text
    assert "primary_failure" not in item_text

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert b"\r\n" not in (output / "submission_template.csv").read_bytes()
    assert manifest["thresholds"] == {
        "held_out_minimum_item_count": 60,
        "maximum_access_safety_failures": 0,
        "maximum_uncertain_rate": 0.1,
        "minimum_cohens_kappa": 0.7,
        "minimum_mean_ndcg_at_5": 0.8,
        "minimum_mean_relevance_precision_at_5": 0.6,
        "minimum_mean_relevance_recall_at_5": 0.85,
        "minimum_overall_acceptance_rate": 0.8,
        "minimum_raw_label_agreement": 0.8,
        "minimum_retrieval_weighted_kappa": 0.7,
    }
    for name, expected_hash in manifest["artifacts"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == expected_hash

    with pytest.raises(FileExistsError, match="already exists"):
        publish_quality_review_packet(tmp_path, packet_spec())


def test_submission_is_complete_pseudonymous_and_bound_to_packet(
    tmp_path: Path,
) -> None:
    packet_dir = publish_quality_review_packet(tmp_path / "packets", packet_spec())
    packet_hash = hashlib.sha256(
        (packet_dir / "manifest.json").read_bytes()
    ).hexdigest()
    submission = QualityReviewSubmission(
        packet_id="quality-calibration-001",
        packet_manifest_sha256=packet_hash,
        reviewer_id_hash="c" * 64,
        reviewer_identity_domain_sha256=IDENTITY_DOMAIN,
        submitted_at_utc=datetime(2026, 7, 27, 1, tzinfo=timezone.utc),
        blindness_attestation=True,
        independence_attestation=True,
        fixture_only=False,
        judgements=[
            QualityJudgement(
                review_item_id="qri_4c5db720f312",
                retrieval_relevance=[
                    RetrievalRelevanceJudgement(
                        source_id="Source A",
                        grade="2",
                    )
                ],
                factual_correctness="pass",
                completeness="pass",
                citation_support="pass",
                refusal_appropriateness="not_applicable",
                access_safety="pass",
                overall_acceptability="pass",
                primary_failure_stage="none",
                rationale="The answer matches the frozen reference evidence.",
            )
        ],
    )

    submission_path = publish_quality_review_submission(
        tmp_path / "submissions",
        packet_dir,
        submission,
    )
    verified = verify_quality_review_submission(submission_path, packet_dir)

    assert verified.reviewer_id_hash == "c" * 64
    assert verified.fixture_only is False
    assert "reviewer_name" not in submission_path.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError, match="already exists"):
        publish_quality_review_submission(
            tmp_path / "submissions",
            packet_dir,
            submission,
        )


def test_two_independent_fixture_reviews_report_agreement_without_quality_claim(
    tmp_path: Path,
) -> None:
    packet_dir = publish_quality_review_packet(tmp_path / "packets", packet_spec())
    packet_hash = hashlib.sha256(
        (packet_dir / "manifest.json").read_bytes()
    ).hexdigest()
    paths = []
    for reviewer_hash in ("c" * 64, "d" * 64):
        submission = QualityReviewSubmission(
            packet_id="quality-calibration-001",
            packet_manifest_sha256=packet_hash,
            reviewer_id_hash=reviewer_hash,
            reviewer_identity_domain_sha256=IDENTITY_DOMAIN,
            submitted_at_utc=datetime(2026, 7, 27, 1, tzinfo=timezone.utc),
            blindness_attestation=True,
            independence_attestation=True,
            fixture_only=True,
            judgements=[
                QualityJudgement(
                    review_item_id="qri_4c5db720f312",
                    retrieval_relevance=[
                        RetrievalRelevanceJudgement(
                            source_id="Source A",
                            grade="2",
                        )
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
            ],
        )
        paths.append(
            publish_quality_review_submission(
                tmp_path / "submissions",
                packet_dir,
                submission,
            )
        )

    aggregate = aggregate_quality_reviews(packet_dir, paths)

    assert isinstance(aggregate, QualityReviewAggregate)
    assert aggregate.reviewer_count == 2
    assert aggregate.review_status == "complete"
    assert aggregate.claim_status == "FIXTURE_ONLY"
    assert aggregate.raw_label_agreement == 1.0
    assert aggregate.cohens_kappa is None
    assert set(aggregate.per_dimension_agreement.values()) == {1.0}
    assert aggregate.disagreement_count == 0
    assert aggregate.retrieval_label_count == 1
    assert aggregate.retrieval_raw_agreement == 1.0
    assert aggregate.retrieval_weighted_kappa is None
    assert aggregate.mean_relevance_precision_at_5 == 1.0
    assert aggregate.mean_ndcg_at_5 == 1.0
    assert aggregate.overall_acceptance_rate == 1.0

    second_payload = json.loads(paths[1].read_text(encoding="utf-8"))
    second_payload["reviewer_identity_domain_sha256"] = "8" * 64
    paths[1].write_text(
        json.dumps(second_payload),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="shared identity domain"):
        aggregate_quality_reviews(packet_dir, paths)


def test_disagreement_is_inconclusive_until_distinct_adjudicator_resolves_it(
    tmp_path: Path,
) -> None:
    packet_dir = publish_quality_review_packet(tmp_path / "packets", packet_spec())
    packet_hash = hashlib.sha256(
        (packet_dir / "manifest.json").read_bytes()
    ).hexdigest()
    paths = []
    for reviewer_hash, overall, factual, stage in (
        ("c" * 64, "pass", "pass", "none"),
        ("d" * 64, "fail", "fail", "answer_factuality"),
    ):
        submission = QualityReviewSubmission(
            packet_id="quality-calibration-001",
            packet_manifest_sha256=packet_hash,
            reviewer_id_hash=reviewer_hash,
            reviewer_identity_domain_sha256=IDENTITY_DOMAIN,
            submitted_at_utc=datetime(2026, 7, 27, 1, tzinfo=timezone.utc),
            blindness_attestation=True,
            independence_attestation=True,
            fixture_only=True,
            judgements=[
                QualityJudgement(
                    review_item_id="qri_4c5db720f312",
                    retrieval_relevance=[
                        RetrievalRelevanceJudgement(
                            source_id="Source A",
                            grade="2",
                        )
                    ],
                    factual_correctness=factual,
                    completeness="pass",
                    citation_support="pass",
                    refusal_appropriateness="not_applicable",
                    access_safety="pass",
                    overall_acceptability=overall,
                    primary_failure_stage=stage,
                    rationale="Independent fixture judgement.",
                )
            ],
        )
        paths.append(
            publish_quality_review_submission(
                tmp_path / "submissions",
                packet_dir,
                submission,
            )
        )

    unresolved = aggregate_quality_reviews(packet_dir, paths)
    assert unresolved.review_status == "needs_adjudication"
    assert unresolved.claim_status == "FIXTURE_ONLY"
    assert unresolved.disagreement_count == 1
    assert unresolved.unresolved_disagreement_count == 1
    assert unresolved.overall_pass_count == 0

    adjudication = QualityReviewAdjudication(
        packet_id="quality-calibration-001",
        packet_manifest_sha256=packet_hash,
        submission_sha256=sorted(
            hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
        ),
        adjudicator_id_hash="e" * 64,
        reviewer_identity_domain_sha256=IDENTITY_DOMAIN,
        submitted_at_utc=datetime(2026, 7, 27, 2, tzinfo=timezone.utc),
        model_identity_blind_attestation=True,
        independence_attestation=True,
        decisions=[
            QualityJudgement(
                review_item_id="qri_4c5db720f312",
                retrieval_relevance=[
                    RetrievalRelevanceJudgement(
                        source_id="Source A",
                        grade="2",
                    )
                ],
                factual_correctness="pass",
                completeness="pass",
                citation_support="pass",
                refusal_appropriateness="not_applicable",
                access_safety="pass",
                overall_acceptability="pass",
                primary_failure_stage="none",
                rationale="The frozen reference resolves the factual dispute.",
            )
        ],
    )
    resolved = aggregate_quality_reviews(
        packet_dir,
        paths,
        adjudication=adjudication,
    )

    assert resolved.review_status == "complete"
    assert resolved.disagreement_count == 1
    assert resolved.adjudicated_count == 1
    assert resolved.unresolved_disagreement_count == 0
    assert resolved.overall_pass_count == 1


def test_public_synthetic_data_cannot_be_declared_independent_holdout() -> None:
    payload = packet_spec().model_dump(mode="python")
    payload["purpose"] = "held_out_acceptance"
    payload["sampling_strategy"] = "all_cases"
    payload["source"]["dataset_split"] = "test"

    with pytest.raises(ValidationError, match="independent"):
        QualityReviewPacketSpec.model_validate(payload)


def test_held_out_packet_requires_bound_pooled_candidate_runs() -> None:
    payload = packet_spec().model_dump(mode="python")
    payload["purpose"] = "held_out_acceptance"
    payload["sampling_strategy"] = "all_cases"
    payload["source"].update(
        {
            "dataset_split": "external_holdout",
            "population_kind": "approved_deidentified",
            "independence_status": "owner_attested",
        }
    )

    with pytest.raises(ValidationError, match="pooled"):
        QualityReviewPacketSpec.model_validate(payload)

    payload["items"][0].update(
        {
            "candidate_pool_strategy": "pooled_variants",
            "candidate_pool_run_manifest_sha256": [SHA_A, SHA_C],
        }
    )

    spec = QualityReviewPacketSpec.model_validate(payload)

    assert spec.items[0].candidate_pool_run_manifest_sha256 == [
        SHA_A,
        SHA_C,
    ]


def test_held_out_packet_rejects_unweighted_stratified_sampling() -> None:
    payload = packet_spec().model_dump(mode="python")
    payload["purpose"] = "held_out_acceptance"
    payload["sampling_strategy"] = "stratified_random"
    payload["source"].update(
        {
            "dataset_split": "external_holdout",
            "population_kind": "approved_deidentified",
            "independence_status": "owner_attested",
        }
    )
    payload["items"][0].update(
        {
            "candidate_pool_strategy": "pooled_variants",
            "candidate_pool_run_manifest_sha256": [SHA_A, SHA_C],
        }
    )

    with pytest.raises(ValidationError, match="all_cases"):
        QualityReviewPacketSpec.model_validate(payload)


def test_evidence_source_id_cannot_change_content_across_item_lists() -> None:
    with pytest.raises(ValidationError, match="conflicting content"):
        QualityReviewItem(
            review_item_id="qri_333333333333",
            question="What is the current limit?",
            system_answer="The current limit is three days.",
            expected_response_mode="answered",
            reference_answer="Three days.",
            retrieved_evidence=[
                evidence("Source A", "Remote work is allowed three days.")
            ],
            retrieval_candidate_evidence=[
                evidence("Source A", "Remote work is allowed five days.")
            ],
            candidate_pool_strategy="returned_only",
            reference_evidence=[
                evidence("Source A", "Remote work is allowed three days.")
            ],
        )


def test_submission_must_grade_every_retrieved_document(tmp_path: Path) -> None:
    packet_dir = publish_quality_review_packet(tmp_path / "packets", packet_spec())
    packet_hash = hashlib.sha256(
        (packet_dir / "manifest.json").read_bytes()
    ).hexdigest()
    submission = QualityReviewSubmission(
        packet_id="quality-calibration-001",
        packet_manifest_sha256=packet_hash,
        reviewer_id_hash="c" * 64,
        reviewer_identity_domain_sha256=IDENTITY_DOMAIN,
        submitted_at_utc=datetime(2026, 7, 27, 1, tzinfo=timezone.utc),
        blindness_attestation=True,
        independence_attestation=True,
        fixture_only=True,
        judgements=[
            QualityJudgement(
                review_item_id="qri_4c5db720f312",
                retrieval_relevance=[],
                factual_correctness="pass",
                completeness="pass",
                citation_support="pass",
                refusal_appropriateness="not_applicable",
                access_safety="pass",
                overall_acceptability="pass",
                primary_failure_stage="none",
                rationale="Missing retrieval labels must fail validation.",
            )
        ],
    )

    with pytest.raises(ValueError, match="retrieval relevance"):
        publish_quality_review_submission(
            tmp_path / "submissions",
            packet_dir,
            submission,
        )


def test_small_held_out_review_remains_inconclusive_despite_perfect_labels(
    tmp_path: Path,
) -> None:
    payload = packet_spec().model_dump(mode="python")
    payload["packet_id"] = "quality-held-out-001"
    payload["purpose"] = "held_out_acceptance"
    payload["sampling_strategy"] = "all_cases"
    payload["source"].update(
        {
            "dataset_split": "external_holdout",
            "population_kind": "approved_deidentified",
            "independence_status": "owner_attested",
        }
    )
    payload["items"][0].update(
        {
            "candidate_pool_strategy": "pooled_variants",
            "candidate_pool_run_manifest_sha256": [SHA_A, SHA_C],
        }
    )
    spec = QualityReviewPacketSpec.model_validate(payload)
    packet_dir = publish_quality_review_packet(tmp_path / "packets", spec)
    packet_hash = hashlib.sha256(
        (packet_dir / "manifest.json").read_bytes()
    ).hexdigest()
    paths = []
    for reviewer_hash in ("c" * 64, "d" * 64):
        submission = QualityReviewSubmission(
            packet_id=spec.packet_id,
            packet_manifest_sha256=packet_hash,
            reviewer_id_hash=reviewer_hash,
            reviewer_identity_domain_sha256=IDENTITY_DOMAIN,
            submitted_at_utc=datetime(2026, 7, 27, 1, tzinfo=timezone.utc),
            blindness_attestation=True,
            independence_attestation=True,
            fixture_only=False,
            judgements=[
                QualityJudgement(
                    review_item_id="qri_4c5db720f312",
                    retrieval_relevance=[
                        RetrievalRelevanceJudgement(
                            source_id="Source A",
                            grade="2",
                        )
                    ],
                    factual_correctness="pass",
                    completeness="pass",
                    citation_support="pass",
                    refusal_appropriateness="not_applicable",
                    access_safety="pass",
                    overall_acceptability="pass",
                    primary_failure_stage="none",
                    rationale="Perfect labels on an undersized holdout.",
                )
            ],
        )
        paths.append(
            publish_quality_review_submission(
                tmp_path / "submissions",
                packet_dir,
                submission,
            )
        )

    aggregate = aggregate_quality_reviews(packet_dir, paths)

    assert aggregate.claim_status == "INCONCLUSIVE"
    assert aggregate.release_gate_reasons == [
        "held_out_item_count_below_minimum"
    ]


def test_evidence_bundle_recomputes_summary_and_detects_tampering(
    tmp_path: Path,
) -> None:
    packet_dir = publish_quality_review_packet(tmp_path / "packets", packet_spec())
    packet_hash = hashlib.sha256(
        (packet_dir / "manifest.json").read_bytes()
    ).hexdigest()
    paths = []
    for reviewer_hash in ("c" * 64, "d" * 64):
        submission = QualityReviewSubmission(
            packet_id="quality-calibration-001",
            packet_manifest_sha256=packet_hash,
            reviewer_id_hash=reviewer_hash,
            reviewer_identity_domain_sha256=IDENTITY_DOMAIN,
            submitted_at_utc=datetime(2026, 7, 27, 1, tzinfo=timezone.utc),
            blindness_attestation=True,
            independence_attestation=True,
            fixture_only=True,
            judgements=[
                QualityJudgement(
                    review_item_id="qri_4c5db720f312",
                    retrieval_relevance=[
                        RetrievalRelevanceJudgement(
                            source_id="Source A",
                            grade="2",
                        )
                    ],
                    factual_correctness="pass",
                    completeness="pass",
                    citation_support="pass",
                    refusal_appropriateness="not_applicable",
                    access_safety="pass",
                    overall_acceptability="pass",
                    primary_failure_stage="none",
                    rationale="Fixture evidence for recomputation.",
                )
            ],
        )
        paths.append(
            publish_quality_review_submission(
                tmp_path / "submissions",
                packet_dir,
                submission,
            )
        )

    evidence_dir = publish_quality_review_evidence(
        tmp_path / "evidence",
        evidence_id="quality-evidence-001",
        packet_dir=packet_dir,
        submission_paths=paths,
        adjudication=None,
        created_at_utc=datetime(2026, 7, 27, 3, tzinfo=timezone.utc),
    )
    verified = verify_quality_review_evidence(evidence_dir)

    assert verified.claim_status == "FIXTURE_ONLY"
    assert verified.mean_ndcg_at_5 == 1.0
    with pytest.raises(FileExistsError, match="already exists"):
        publish_quality_review_evidence(
            tmp_path / "evidence",
            evidence_id="quality-evidence-001",
            packet_dir=packet_dir,
            submission_paths=paths,
            adjudication=None,
            created_at_utc=datetime(2026, 7, 27, 3, tzinfo=timezone.utc),
        )

    summary_path = evidence_dir / "summary.json"
    summary_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        verify_quality_review_evidence(evidence_dir)


def test_pooled_candidates_expose_retrieval_miss_in_recall_and_ndcg(
    tmp_path: Path,
) -> None:
    source_a = evidence("Source A", "Remote work is allowed three days.")
    source_b = evidence("Source B", "The authoritative limit is three days.")
    spec = QualityReviewPacketSpec(
        packet_id="quality-pooled-001",
        purpose="calibration",
        created_at_utc=datetime(2026, 7, 27, tzinfo=timezone.utc),
        source=QualityReviewSource(
            run_id="pooled-run",
            run_manifest_sha256=SHA_A,
            dataset_sha256=SHA_B,
            dataset_split="dev",
            git_commit="1" * 40,
        ),
        sampling_strategy="all_cases",
        sampling_seed=1729,
        items=[
            QualityReviewItem(
                review_item_id="qri_111111111111",
                question="What is the current limit?",
                system_answer="Three days [Source A].",
                expected_response_mode="answered",
                reference_answer="Three days.",
                retrieved_evidence=[source_a],
                retrieval_candidate_evidence=[source_a, source_b],
                candidate_pool_strategy="pooled_variants",
                candidate_pool_run_manifest_sha256=[SHA_A, SHA_C],
                reference_evidence=[source_b],
            )
        ],
    )
    packet_dir = publish_quality_review_packet(tmp_path / "packets", spec)
    packet_hash = hashlib.sha256(
        (packet_dir / "manifest.json").read_bytes()
    ).hexdigest()
    paths = []
    for reviewer_hash in ("c" * 64, "d" * 64):
        paths.append(
            publish_quality_review_submission(
                tmp_path / "submissions",
                packet_dir,
                QualityReviewSubmission(
                    packet_id=spec.packet_id,
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
                    fixture_only=True,
                    judgements=[
                        QualityJudgement(
                            review_item_id="qri_111111111111",
                            retrieval_relevance=[
                                RetrievalRelevanceJudgement(
                                    source_id="Source A",
                                    grade="2",
                                ),
                                RetrievalRelevanceJudgement(
                                    source_id="Source B",
                                    grade="2",
                                ),
                            ],
                            factual_correctness="pass",
                            completeness="pass",
                            citation_support="pass",
                            refusal_appropriateness="not_applicable",
                            access_safety="pass",
                            overall_acceptability="pass",
                            primary_failure_stage="none",
                            rationale="Both pooled candidates are relevant.",
                        )
                    ],
                ),
            )
        )

    aggregate = aggregate_quality_reviews(packet_dir, paths)

    assert aggregate.mean_relevance_precision_at_5 == 1.0
    assert aggregate.mean_relevance_recall_at_5 == 0.5
    assert aggregate.mean_ndcg_at_5 == pytest.approx(0.6131471928)

    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["judgements"][0]["retrieval_relevance"][1]["grade"] = (
            "uncertain"
        )
        path.write_text(json.dumps(payload), encoding="utf-8")

    conservative = aggregate_quality_reviews(packet_dir, paths)

    assert conservative.retrieval_uncertain_count == 1
    assert conservative.mean_relevance_precision_at_5 == 1.0
    assert conservative.mean_relevance_recall_at_5 == 0.5
    assert conservative.mean_ndcg_at_5 == pytest.approx(0.6131471928)


def test_submission_can_grade_every_allowed_pooled_candidate(
    tmp_path: Path,
) -> None:
    candidates = [
        evidence(f"Source {index:02d}", f"Candidate evidence {index}.")
        for index in range(21)
    ]
    spec = QualityReviewPacketSpec(
        packet_id="quality-pooled-capacity-001",
        purpose="calibration",
        created_at_utc=datetime(2026, 7, 27, tzinfo=timezone.utc),
        source=QualityReviewSource(
            run_id="pooled-capacity-run",
            run_manifest_sha256=SHA_A,
            dataset_sha256=SHA_B,
            dataset_split="dev",
            git_commit="1" * 40,
        ),
        sampling_strategy="all_cases",
        sampling_seed=1729,
        items=[
            QualityReviewItem(
                review_item_id="qri_222222222222",
                question="Which candidate is relevant?",
                system_answer="Source 00 is relevant.",
                expected_response_mode="answered",
                reference_answer="Source 00.",
                retrieved_evidence=[candidates[0]],
                retrieval_candidate_evidence=candidates,
                candidate_pool_strategy="pooled_variants",
                candidate_pool_run_manifest_sha256=[SHA_A, SHA_C],
                reference_evidence=[candidates[0]],
            )
        ],
    )
    packet_dir = publish_quality_review_packet(tmp_path / "packets", spec)
    packet_hash = hashlib.sha256(
        (packet_dir / "manifest.json").read_bytes()
    ).hexdigest()

    submission_path = publish_quality_review_submission(
        tmp_path / "submissions",
        packet_dir,
        QualityReviewSubmission(
            packet_id=spec.packet_id,
            packet_manifest_sha256=packet_hash,
            reviewer_id_hash="e" * 64,
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
            fixture_only=True,
            judgements=[
                QualityJudgement(
                    review_item_id="qri_222222222222",
                    retrieval_relevance=[
                        RetrievalRelevanceJudgement(
                            source_id=item.source_id,
                            grade="2" if index == 0 else "0",
                        )
                        for index, item in enumerate(candidates)
                    ],
                    factual_correctness="pass",
                    completeness="pass",
                    citation_support="pass",
                    refusal_appropriateness="not_applicable",
                    access_safety="pass",
                    overall_acceptability="pass",
                    primary_failure_stage="none",
                    rationale="All pooled candidates were graded.",
                )
            ],
        ),
    )

    assert verify_quality_review_submission(
        submission_path,
        packet_dir,
    ).judgements[0].retrieval_relevance[20].source_id == "Source 20"
