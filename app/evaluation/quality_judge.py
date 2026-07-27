from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections import Counter
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Literal, Sequence

from pydantic import Field, field_validator, model_validator

from app.evaluation.contracts import StrictModel
from app.evaluation.quality_review import (
    QualityJudgement,
    QualityReviewAdjudication,
    QualityReviewSubmission,
    validate_quality_judgements,
    verify_quality_review_evidence,
)
from app.filesystem import atomic_directory_move


_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_CALIBRATION_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")


class QualityJudgeRun(StrictModel):
    schema_version: Literal["enterprise_quality_judge_run_v1"] = (
        "enterprise_quality_judge_run_v1"
    )
    producer: Literal["enterprise_agentic_rag_v2"] = "enterprise_agentic_rag_v2"
    run_id: str = Field(min_length=1, max_length=200)
    human_evidence_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    packet_id: str = Field(min_length=1, max_length=200)
    packet_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    provider: Literal["ollama_local"]
    judge_model_name: str = Field(min_length=1, max_length=200)
    judge_model_digest: str = Field(pattern=_SHA256_PATTERN)
    judge_model_family: str = Field(min_length=1, max_length=200)
    answer_model_family: str = Field(min_length=1, max_length=200)
    prompt_sha256: str = Field(pattern=_SHA256_PATTERN)
    inference_config_sha256: str = Field(pattern=_SHA256_PATTERN)
    trial_index: int = Field(ge=0)
    created_at_utc: datetime
    retrieved_content_is_data_attestation: Literal[True]
    security_gate_authority: Literal["none"]
    fixture_only: bool
    judgements: list[QualityJudgement] = Field(min_length=1, max_length=10_000)

    @field_validator("created_at_utc")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("quality judge timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_judgements(self) -> QualityJudgeRun:
        item_ids = [item.review_item_id for item in self.judgements]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("quality judge item IDs must be unique")
        return self


class QualityJudgeCalibrationThresholds(StrictModel):
    minimum_trial_count: int = Field(default=3, ge=2)
    minimum_raw_label_agreement: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
    )
    minimum_overall_acceptability_agreement: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
    )
    minimum_cohens_kappa: float = Field(default=0.7, ge=-1.0, le=1.0)
    minimum_judge_stability: float = Field(default=0.8, ge=0.0, le=1.0)
    maximum_false_pass_count: int = Field(default=0, ge=0)
    maximum_security_false_pass_count: int = Field(default=0, ge=0)


class QualityJudgeCalibration(StrictModel):
    schema_version: Literal["enterprise_quality_judge_calibration_v1"] = (
        "enterprise_quality_judge_calibration_v1"
    )
    producer: Literal["enterprise_agentic_rag_v2"] = "enterprise_agentic_rag_v2"
    status: Literal[
        "FIXTURE_ONLY",
        "INCONCLUSIVE",
        "FAILED",
        "CALIBRATED",
    ]
    human_evidence_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    packet_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    judge_run_sha256: list[str] = Field(min_length=1)
    judge_model_name: str = Field(min_length=1)
    judge_model_digest: str = Field(pattern=_SHA256_PATTERN)
    judge_model_family: str = Field(min_length=1)
    answer_model_family: str = Field(min_length=1)
    prompt_sha256: str = Field(pattern=_SHA256_PATTERN)
    inference_config_sha256: str = Field(pattern=_SHA256_PATTERN)
    thresholds: QualityJudgeCalibrationThresholds
    trial_count: int = Field(ge=1)
    item_count: int = Field(ge=1)
    compared_label_count: int = Field(ge=1)
    raw_label_agreement: float = Field(ge=0.0, le=1.0)
    overall_acceptability_agreement: float = Field(ge=0.0, le=1.0)
    cohens_kappa: float | None = Field(default=None, ge=-1.0, le=1.0)
    judge_stability: float | None = Field(default=None, ge=0.0, le=1.0)
    false_pass_count: int = Field(ge=0)
    security_false_pass_count: int = Field(ge=0)
    per_dimension_agreement: dict[str, float]
    risk_flags: list[str]
    decision_reasons: list[str]
    release_authority: Literal[False] = False


class QualityJudgeCalibrationManifest(StrictModel):
    schema_version: Literal["enterprise_quality_judge_evidence_v1"] = (
        "enterprise_quality_judge_evidence_v1"
    )
    producer: Literal["enterprise_agentic_rag_v2"] = "enterprise_agentic_rag_v2"
    calibration_id: str = Field(min_length=1, max_length=200)
    created_at_utc: datetime
    human_evidence_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    status: Literal[
        "FIXTURE_ONLY",
        "INCONCLUSIVE",
        "FAILED",
        "CALIBRATED",
    ]
    artifacts: dict[str, str]

    @field_validator("calibration_id")
    @classmethod
    def validate_calibration_id(cls, value: str) -> str:
        if value in {".", ".."} or not _CALIBRATION_ID_PATTERN.fullmatch(value):
            raise ValueError("quality judge calibration ID contains unsafe characters")
        return value

    @field_validator("created_at_utc")
    @classmethod
    def validate_manifest_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("quality judge calibration timestamp must be aware")
        return value

    @field_validator("artifacts")
    @classmethod
    def validate_artifacts(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("quality judge calibration artifacts are empty")
        for path, digest in value.items():
            candidate = Path(path)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise ValueError("quality judge artifact path is unsafe")
            if re.fullmatch(_SHA256_PATTERN, digest) is None:
                raise ValueError("quality judge artifact hash is invalid")
        return value


def calibrate_quality_judge(
    human_evidence_dir: Path,
    judge_runs: Sequence[QualityJudgeRun],
    *,
    thresholds: QualityJudgeCalibrationThresholds | None = None,
) -> QualityJudgeCalibration:
    if not judge_runs:
        raise ValueError("quality judge calibration requires at least one run")
    thresholds = thresholds or QualityJudgeCalibrationThresholds()
    human_evidence_dir = Path(human_evidence_dir).resolve()
    human_summary = verify_quality_review_evidence(human_evidence_dir)
    evidence_manifest_path = human_evidence_dir / "manifest.json"
    evidence_manifest_hash = _sha256(evidence_manifest_path)
    packet_dir = _packet_dir(human_evidence_dir)
    packet_manifest_hash = _sha256(packet_dir / "manifest.json")
    human_consensus = _load_human_consensus(
        human_evidence_dir,
        human_summary,
    )
    if not human_consensus:
        raise ValueError("quality judge calibration has no human consensus labels")

    _validate_run_set(
        judge_runs,
        evidence_manifest_hash=evidence_manifest_hash,
        packet_id=human_summary.packet_id,
        packet_manifest_hash=packet_manifest_hash,
        packet_dir=packet_dir,
    )
    metadata = judge_runs[0]
    human_vectors = {
        item_id: _label_vector(judgement)
        for item_id, judgement in human_consensus.items()
    }
    total_matches = 0
    total_labels = 0
    overall_matches = 0
    overall_total = 0
    false_pass_count = 0
    security_false_pass_count = 0
    human_kappa_labels: list[str] = []
    judge_kappa_labels: list[str] = []
    dimension_matches: Counter[str] = Counter()
    dimension_totals: Counter[str] = Counter()
    run_vectors: list[dict[str, list[tuple[str, str]]]] = []

    for run in sorted(judge_runs, key=lambda item: item.trial_index):
        by_id = {
            judgement.review_item_id: judgement
            for judgement in run.judgements
        }
        vectors: dict[str, list[tuple[str, str]]] = {}
        for item_id in sorted(human_consensus):
            human = human_consensus[item_id]
            judged = by_id[item_id]
            human_vector = human_vectors[item_id]
            judge_vector = _label_vector(judged)
            vectors[item_id] = judge_vector
            if [name for name, _ in human_vector] != [
                name for name, _ in judge_vector
            ]:
                raise ValueError("quality judge label vector shape mismatch")
            for (dimension, human_label), (_, judge_label) in zip(
                human_vector,
                judge_vector,
                strict=True,
            ):
                total_labels += 1
                category = (
                    "retrieval_relevance"
                    if dimension.startswith("retrieval_relevance:")
                    else dimension
                )
                dimension_totals[category] += 1
                if human_label == judge_label:
                    total_matches += 1
                    dimension_matches[category] += 1
                if dimension == "overall_acceptability":
                    human_kappa_labels.append(human_label)
                    judge_kappa_labels.append(judge_label)
            overall_total += 1
            if human.overall_acceptability == judged.overall_acceptability:
                overall_matches += 1
            if (
                human.overall_acceptability == "fail"
                and judged.overall_acceptability == "pass"
            ):
                false_pass_count += 1
            if (
                human.access_safety == "fail"
                and judged.access_safety != "fail"
            ):
                security_false_pass_count += 1
        run_vectors.append(vectors)

    per_dimension_agreement = {
        dimension: dimension_matches[dimension] / total
        for dimension, total in sorted(dimension_totals.items())
    }
    raw_agreement = (
        sum(per_dimension_agreement.values())
        / len(per_dimension_agreement)
    )
    overall_agreement = overall_matches / overall_total
    kappa = _cohens_kappa(human_kappa_labels, judge_kappa_labels)
    stability = _judge_stability(run_vectors)
    risk_flags: list[str] = []
    if metadata.judge_model_family == metadata.answer_model_family:
        risk_flags.append("same_model_family_correlation")
    if any(run.fixture_only for run in judge_runs):
        risk_flags.append("fixture_only_judge_outputs")
    if human_summary.claim_status == "FIXTURE_ONLY":
        risk_flags.append("fixture_only_human_consensus")

    status, reasons = _calibration_decision(
        human_status=human_summary.review_status,
        human_claim_status=human_summary.claim_status,
        judge_runs=judge_runs,
        raw_agreement=raw_agreement,
        overall_agreement=overall_agreement,
        kappa=kappa,
        stability=stability,
        false_pass_count=false_pass_count,
        security_false_pass_count=security_false_pass_count,
        risk_flags=risk_flags,
        thresholds=thresholds,
    )
    return QualityJudgeCalibration(
        status=status,
        human_evidence_manifest_sha256=evidence_manifest_hash,
        packet_manifest_sha256=packet_manifest_hash,
        judge_run_sha256=sorted(_model_hash(run) for run in judge_runs),
        judge_model_name=metadata.judge_model_name,
        judge_model_digest=metadata.judge_model_digest,
        judge_model_family=metadata.judge_model_family,
        answer_model_family=metadata.answer_model_family,
        prompt_sha256=metadata.prompt_sha256,
        inference_config_sha256=metadata.inference_config_sha256,
        thresholds=thresholds,
        trial_count=len(judge_runs),
        item_count=len(human_consensus),
        compared_label_count=total_labels,
        raw_label_agreement=raw_agreement,
        overall_acceptability_agreement=overall_agreement,
        cohens_kappa=kappa,
        judge_stability=stability,
        false_pass_count=false_pass_count,
        security_false_pass_count=security_false_pass_count,
        per_dimension_agreement=per_dimension_agreement,
        risk_flags=risk_flags,
        decision_reasons=reasons,
    )


def publish_quality_judge_calibration(
    root: Path,
    *,
    calibration_id: str,
    human_evidence_dir: Path,
    judge_runs: Sequence[QualityJudgeRun],
    created_at_utc: datetime,
) -> Path:
    calibration = calibrate_quality_judge(
        human_evidence_dir,
        judge_runs,
    )
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (
        calibration_id in {".", ".."}
        or not _CALIBRATION_ID_PATTERN.fullmatch(calibration_id)
    ):
        raise ValueError("quality judge calibration ID contains unsafe characters")
    target = (root / calibration_id).resolve()
    if target.parent != root:
        raise ValueError("quality judge calibration resolves outside output root")
    if target.exists():
        raise FileExistsError(
            f"quality judge calibration already exists: {target}"
        )

    stage = Path(
        tempfile.mkdtemp(prefix=f".{calibration_id}.staging-", dir=root)
    ).resolve()
    try:
        runs_dir = stage / "judge_runs"
        runs_dir.mkdir()
        for run in sorted(judge_runs, key=lambda item: item.trial_index):
            (runs_dir / f"trial_{run.trial_index:03d}.json").write_bytes(
                _json_bytes(run.model_dump(mode="json"))
            )
        (stage / "calibration.json").write_bytes(
            _json_bytes(calibration.model_dump(mode="json"))
        )
        artifacts = _tree_hashes(stage)
        manifest = QualityJudgeCalibrationManifest(
            calibration_id=calibration_id,
            created_at_utc=created_at_utc,
            human_evidence_manifest_sha256=_sha256(
                Path(human_evidence_dir).resolve() / "manifest.json"
            ),
            status=calibration.status,
            artifacts=artifacts,
        )
        (stage / "manifest.json").write_bytes(
            _json_bytes(manifest.model_dump(mode="json"))
        )
        verify_quality_judge_calibration(stage, human_evidence_dir)
        atomic_directory_move(stage, target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def verify_quality_judge_calibration(
    calibration_dir: Path,
    human_evidence_dir: Path,
) -> QualityJudgeCalibration:
    calibration_dir = Path(calibration_dir).resolve()
    _require_plain_tree(calibration_dir)
    manifest_path = calibration_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("quality judge calibration manifest not found")
    manifest = QualityJudgeCalibrationManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if (
        manifest.calibration_id != calibration_dir.name
        and ".staging-" not in calibration_dir.name
    ):
        raise ValueError("quality judge directory and manifest ID mismatch")
    observed_artifacts = _tree_hashes(
        calibration_dir,
        exclude={"manifest.json"},
    )
    if set(observed_artifacts) != set(manifest.artifacts):
        raise ValueError("quality judge calibration artifact set mismatch")
    for path, expected_hash in manifest.artifacts.items():
        if observed_artifacts[path] != expected_hash:
            raise ValueError(
                f"quality judge calibration artifact hash mismatch: {path}"
            )

    human_evidence_dir = Path(human_evidence_dir).resolve()
    if (
        _sha256(human_evidence_dir / "manifest.json")
        != manifest.human_evidence_manifest_sha256
    ):
        raise ValueError("quality judge human evidence manifest hash mismatch")
    judge_runs = [
        QualityJudgeRun.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(
            (calibration_dir / "judge_runs").glob("trial_*.json")
        )
    ]
    recomputed = calibrate_quality_judge(
        human_evidence_dir,
        judge_runs,
    )
    recorded = QualityJudgeCalibration.model_validate_json(
        (calibration_dir / "calibration.json").read_text(encoding="utf-8")
    )
    if recomputed != recorded:
        raise ValueError("quality judge calibration does not recompute")
    if recorded.status != manifest.status:
        raise ValueError("quality judge calibration status mismatch")
    return recorded


def _validate_run_set(
    runs: Sequence[QualityJudgeRun],
    *,
    evidence_manifest_hash: str,
    packet_id: str,
    packet_manifest_hash: str,
    packet_dir: Path,
) -> None:
    trial_indices = [run.trial_index for run in runs]
    if len(trial_indices) != len(set(trial_indices)):
        raise ValueError("quality judge trial indices must be unique")
    expected_metadata = _run_metadata(runs[0])
    fixture_values = {run.fixture_only for run in runs}
    if len(fixture_values) != 1:
        raise ValueError("quality judge fixture flags must match across trials")
    for run in runs:
        if run.human_evidence_manifest_sha256 != evidence_manifest_hash:
            raise ValueError("quality judge human evidence hash mismatch")
        if run.packet_id != packet_id:
            raise ValueError("quality judge packet ID mismatch")
        if run.packet_manifest_sha256 != packet_manifest_hash:
            raise ValueError("quality judge packet manifest hash mismatch")
        if _run_metadata(run) != expected_metadata:
            raise ValueError("quality judge trial metadata must be identical")
        validate_quality_judgements(packet_dir, run.judgements)


def _run_metadata(run: QualityJudgeRun) -> tuple[str, ...]:
    return (
        run.provider,
        run.judge_model_name,
        run.judge_model_digest,
        run.judge_model_family,
        run.answer_model_family,
        run.prompt_sha256,
        run.inference_config_sha256,
        run.security_gate_authority,
    )


def _load_human_consensus(
    evidence_dir: Path,
    summary,
) -> dict[str, QualityJudgement]:
    submissions = [
        QualityReviewSubmission.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(
            (evidence_dir / "submissions").glob("reviewer_*.json")
        )
    ]
    first = {
        judgement.review_item_id: judgement
        for judgement in submissions[0].judgements
    }
    disagreement_ids = {
        disagreement.review_item_id for disagreement in summary.disagreements
    }
    consensus = {
        item_id: judgement
        for item_id, judgement in first.items()
        if item_id not in disagreement_ids
    }
    if summary.unresolved_disagreement_count:
        return consensus
    adjudication_path = evidence_dir / "adjudication.json"
    if adjudication_path.is_file():
        adjudication = QualityReviewAdjudication.model_validate_json(
            adjudication_path.read_text(encoding="utf-8")
        )
        consensus.update(
            {
                decision.review_item_id: decision
                for decision in adjudication.decisions
            }
        )
    return consensus


def _packet_dir(evidence_dir: Path) -> Path:
    packet_dirs = [
        path for path in (evidence_dir / "packet").iterdir() if path.is_dir()
    ]
    if len(packet_dirs) != 1:
        raise ValueError("quality judge evidence must contain exactly one packet")
    return packet_dirs[0]


def _label_vector(judgement: QualityJudgement) -> list[tuple[str, str]]:
    vector = [
        (
            f"retrieval_relevance:{item.source_id}",
            item.grade,
        )
        for item in sorted(
            judgement.retrieval_relevance,
            key=lambda item: item.source_id,
        )
    ]
    vector.extend(
        [
            ("factual_correctness", judgement.factual_correctness),
            ("completeness", judgement.completeness),
            ("citation_support", judgement.citation_support),
            (
                "refusal_appropriateness",
                judgement.refusal_appropriateness,
            ),
            ("access_safety", judgement.access_safety),
            ("overall_acceptability", judgement.overall_acceptability),
            ("primary_failure_stage", judgement.primary_failure_stage),
        ]
    )
    return vector


def _judge_stability(
    run_vectors: list[dict[str, list[tuple[str, str]]]],
) -> float | None:
    if len(run_vectors) < 2:
        return None
    matches = 0
    total = 0
    for first, second in combinations(run_vectors, 2):
        for item_id in sorted(first):
            expected = first[item_id]
            observed = second[item_id]
            for (_, expected_label), (_, observed_label) in zip(
                expected,
                observed,
                strict=True,
            ):
                total += 1
                matches += expected_label == observed_label
    return matches / total


def _calibration_decision(
    *,
    human_status: str,
    human_claim_status: str,
    judge_runs: Sequence[QualityJudgeRun],
    raw_agreement: float,
    overall_agreement: float,
    kappa: float | None,
    stability: float | None,
    false_pass_count: int,
    security_false_pass_count: int,
    risk_flags: list[str],
    thresholds: QualityJudgeCalibrationThresholds,
) -> tuple[str, list[str]]:
    if human_claim_status == "FIXTURE_ONLY" or any(
        run.fixture_only for run in judge_runs
    ):
        return "FIXTURE_ONLY", ["fixture_only_inputs"]
    inconclusive: list[str] = []
    if human_status != "complete":
        inconclusive.append("human_consensus_incomplete")
    if len(judge_runs) < thresholds.minimum_trial_count:
        inconclusive.append("judge_trial_count_below_minimum")
    if kappa is None:
        inconclusive.append("cohens_kappa_undefined")
    if stability is None:
        inconclusive.append("judge_stability_undefined")
    if "same_model_family_correlation" in risk_flags:
        inconclusive.append("same_model_family_correlation")
    if inconclusive:
        return "INCONCLUSIVE", inconclusive

    failed: list[str] = []
    if raw_agreement < thresholds.minimum_raw_label_agreement:
        failed.append("raw_label_agreement_below_minimum")
    if (
        overall_agreement
        < thresholds.minimum_overall_acceptability_agreement
    ):
        failed.append("overall_acceptability_agreement_below_minimum")
    if kappa < thresholds.minimum_cohens_kappa:
        failed.append("cohens_kappa_below_minimum")
    if stability < thresholds.minimum_judge_stability:
        failed.append("judge_stability_below_minimum")
    if false_pass_count > thresholds.maximum_false_pass_count:
        failed.append("false_pass_count_above_maximum")
    if (
        security_false_pass_count
        > thresholds.maximum_security_false_pass_count
    ):
        failed.append("security_false_pass_count_above_maximum")
    if failed:
        return "FAILED", failed
    return "CALIBRATED", []


def _cohens_kappa(first: list[str], second: list[str]) -> float | None:
    if len(first) != len(second) or not first:
        raise ValueError("Cohen's kappa requires equal non-empty labels")
    total = len(first)
    observed = sum(
        left == right
        for left, right in zip(first, second, strict=True)
    ) / total
    first_counts = Counter(first)
    second_counts = Counter(second)
    expected = sum(
        (first_counts[label] / total) * (second_counts[label] / total)
        for label in set(first_counts) | set(second_counts)
    )
    if abs(1.0 - expected) <= 1e-12:
        return None
    return (observed - expected) / (1.0 - expected)


def _model_hash(model: StrictModel) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ).encode("utf-8")


def _tree_hashes(
    root: Path,
    *,
    exclude: set[str] | None = None,
) -> dict[str, str]:
    excluded = exclude or set()
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.relative_to(root).as_posix() not in excluded
    }


def _require_plain_tree(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise FileNotFoundError(
            f"quality judge calibration directory not found: {root}"
        )
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(
                f"quality judge calibration contains symlink: {path}"
            )


__all__ = [
    "QualityJudgeCalibration",
    "QualityJudgeCalibrationManifest",
    "QualityJudgeCalibrationThresholds",
    "QualityJudgeRun",
    "calibrate_quality_judge",
    "publish_quality_judge_calibration",
    "verify_quality_judge_calibration",
]
