from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.uda_finance_page_eval import UdaFinancePageSummary
from app.external_datasets.uda_finance_r4_eval import (
    R4CampaignManifest,
    R4GateChecks,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class R4PublicArm(_StrictModel):
    arm: Literal["dense_chunk", "focused_page_fusion"]
    summary: UdaFinancePageSummary


class R4PublicRun(_StrictModel):
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    split: Literal["dev", "validation"]
    code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    index_run_id: str = Field(min_length=1)
    index_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_model: str = Field(min_length=1)
    arms: list[R4PublicArm] = Field(min_length=2, max_length=2)
    page_hit_at_5_delta: float
    page_ndcg_at_5_delta: float
    p95_latency_multiplier: float = Field(ge=0)
    gate_checks: R4GateChecks
    decision: Literal[
        "DEVELOPMENT_ONLY",
        "VALIDATION_PASSED_TEST_AUTHORIZED",
        "VALIDATION_REJECTED_TEST_FORBIDDEN",
    ]

    @model_validator(mode="after")
    def validate_projection(self) -> R4PublicRun:
        if [item.arm for item in self.arms] != [
            "dense_chunk",
            "focused_page_fusion",
        ]:
            raise ValueError("R4 public arms must keep paired order")
        baseline = self.arms[0].summary
        candidate = self.arms[1].summary
        expected = (
            candidate.page_hit_at_5 - baseline.page_hit_at_5,
            candidate.page_ndcg_at_5 - baseline.page_ndcg_at_5,
            candidate.latency_ms_p95 / max(baseline.latency_ms_p95, 1e-9),
        )
        observed = (
            self.page_hit_at_5_delta,
            self.page_ndcg_at_5_delta,
            self.p95_latency_multiplier,
        )
        if any(abs(left - right) > 1e-12 for left, right in zip(expected, observed, strict=True)):
            raise ValueError("R4 public deltas do not match arm summaries")
        return self


class R4PublicEvidence(_StrictModel):
    schema_version: Literal["uda_finance_r4_public_v1"] = "uda_finance_r4_public_v1"
    dataset: Literal["UDA-QA/FinHybrid"] = "UDA-QA/FinHybrid"
    repository_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    evaluation_scope: Literal["known_report_page_localization"] = "known_report_page_localization"
    development: R4PublicRun
    validation: R4PublicRun
    frozen_test_status: Literal["NOT_RUN_VALIDATION_GATE_FORBIDS"]
    promotion_decision: Literal["REJECTED"]
    claim_boundary: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_campaign_binding(self) -> R4PublicEvidence:
        if self.development.split != "dev" or self.validation.split != "validation":
            raise ValueError("R4 public evidence split binding is invalid")
        if not self.development.gate_checks.passed:
            raise ValueError("R4 validation requires a passing development run")
        if self.validation.decision != "VALIDATION_REJECTED_TEST_FORBIDDEN":
            raise ValueError("R4 public v1 records the rejected validation campaign")
        for field in (
            "code_revision",
            "protocol_sha256",
            "index_run_id",
            "index_manifest_sha256",
            "embedding_model",
        ):
            if getattr(self.development, field) != getattr(self.validation, field):
                raise ValueError(f"R4 public campaign changed {field}")
        return self


def project_public_run(
    manifest: R4CampaignManifest,
    *,
    source_manifest_sha256: str,
) -> R4PublicRun:
    return R4PublicRun(
        run_id=manifest.run_id,
        split=manifest.split,
        code_revision=manifest.code_revision,
        protocol_sha256=manifest.protocol_sha256,
        source_manifest_sha256=source_manifest_sha256,
        index_run_id=manifest.index_run_id,
        index_manifest_sha256=manifest.index_manifest_sha256,
        embedding_model=manifest.embedding_model,
        arms=[R4PublicArm(arm=item.arm, summary=item.summary) for item in manifest.arms],
        page_hit_at_5_delta=manifest.page_hit_at_5_delta,
        page_ndcg_at_5_delta=manifest.page_ndcg_at_5_delta,
        p95_latency_multiplier=manifest.p95_latency_multiplier,
        gate_checks=manifest.gate_checks,
        decision=manifest.decision,
    )


def build_r4_public_evidence(
    *,
    development: R4CampaignManifest,
    development_manifest_sha256: str,
    validation: R4CampaignManifest,
    validation_manifest_sha256: str,
    repository_revision: str,
) -> R4PublicEvidence:
    return R4PublicEvidence(
        repository_revision=repository_revision,
        development=project_public_run(
            development,
            source_manifest_sha256=development_manifest_sha256,
        ),
        validation=project_public_run(
            validation,
            source_manifest_sha256=validation_manifest_sha256,
        ),
        frozen_test_status="NOT_RUN_VALIDATION_GATE_FORBIDS",
        promotion_decision="REJECTED",
        claim_boundary=[
            "External public-label company-disjoint validation; not a blind benchmark.",
            "Known-report page localization only; not document discovery or answer accuracy.",
            "Validation missed the preregistered Hit@5 delta gate, so the candidate "
            "was not promoted.",
            "Questions, answers, company identifiers, source paths, and per-case "
            "failures are excluded.",
        ],
    )


def verify_r4_public_evidence(
    evidence_path: Path,
    *,
    protocol_path: Path,
) -> R4PublicEvidence:
    evidence = R4PublicEvidence.model_validate_json(Path(evidence_path).read_bytes())
    protocol_sha256 = hashlib.sha256(Path(protocol_path).read_bytes()).hexdigest()
    if evidence.validation.protocol_sha256 != protocol_sha256:
        raise ValueError("R4 public evidence protocol hash mismatch")
    return evidence


def canonical_json_bytes(value: BaseModel) -> bytes:
    return (
        json.dumps(
            value.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


__all__ = [
    "R4PublicEvidence",
    "build_r4_public_evidence",
    "canonical_json_bytes",
    "project_public_run",
    "verify_r4_public_evidence",
]
