from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.uda_finance_page_eval import (
    UdaFinancePageCaseResult,
    UdaFinancePageSummary,
)

R4Arm = Literal["dense_chunk", "focused_page_fusion"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class R4ArmResult(_StrictModel):
    arm: R4Arm
    summary: UdaFinancePageSummary
    details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class R4GateChecks(_StrictModel):
    min_page_hit_at_5_delta: bool
    min_page_ndcg_at_5_delta: bool
    max_p95_latency_multiplier: bool

    @property
    def passed(self) -> bool:
        return all(self.model_dump().values())


class R4CampaignManifest(_StrictModel):
    schema_version: Literal["uda_finance_r4_campaign_v1"] = "uda_finance_r4_campaign_v1"
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    split: Literal["dev", "validation", "test"]
    code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    index_run_id: str = Field(min_length=1)
    index_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_model: str = Field(min_length=1)
    arms: list[R4ArmResult] = Field(min_length=2, max_length=2)
    page_hit_at_5_delta: float
    page_ndcg_at_5_delta: float
    p95_latency_multiplier: float = Field(ge=0)
    gate_checks: R4GateChecks
    decision: Literal[
        "DEVELOPMENT_ONLY",
        "VALIDATION_PASSED_TEST_AUTHORIZED",
        "VALIDATION_REJECTED_TEST_FORBIDDEN",
        "TEST_COMPLETED_PROMOTED",
        "TEST_COMPLETED_NOT_PROMOTED",
    ]

    @model_validator(mode="after")
    def validate_arms(self) -> R4CampaignManifest:
        if [item.arm for item in self.arms] != ["dense_chunk", "focused_page_fusion"]:
            raise ValueError("R4 campaign arms must keep baseline-first paired order")
        return self


def build_gate_checks(*, baseline, candidate, protocol) -> R4GateChecks:
    latency_multiplier = candidate.latency_ms_p95 / max(baseline.latency_ms_p95, 1e-9)
    return R4GateChecks(
        min_page_hit_at_5_delta=(
            candidate.page_hit_at_5 - baseline.page_hit_at_5 >= protocol.min_page_hit_at_5_delta
        ),
        min_page_ndcg_at_5_delta=(
            candidate.page_ndcg_at_5 - baseline.page_ndcg_at_5 >= protocol.min_page_ndcg_at_5_delta
        ),
        max_p95_latency_multiplier=(latency_multiplier <= protocol.max_p95_latency_multiplier),
    )


def publish_r4_campaign(
    *,
    root: Path,
    manifest_fields: dict,
    details_by_arm: Mapping[R4Arm, Sequence[UdaFinancePageCaseResult]],
    summaries: Mapping[R4Arm, UdaFinancePageSummary],
    protocol,
) -> Path:
    run_dir = Path(root).resolve() / manifest_fields["run_id"]
    run_dir.mkdir(parents=True, exist_ok=False)
    arm_results: list[R4ArmResult] = []
    for arm in ("dense_chunk", "focused_page_fusion"):
        detail_bytes = b"".join(
            _canonical_json_bytes(item.model_dump(mode="json")) for item in details_by_arm[arm]
        )
        (run_dir / f"{arm}.jsonl").write_bytes(detail_bytes)
        arm_results.append(
            R4ArmResult(
                arm=arm,
                summary=summaries[arm],
                details_sha256=hashlib.sha256(detail_bytes).hexdigest(),
            )
        )
    baseline = summaries["dense_chunk"]
    candidate = summaries["focused_page_fusion"]
    checks = build_gate_checks(baseline=baseline, candidate=candidate, protocol=protocol)
    split = manifest_fields["split"]
    decision = (
        "DEVELOPMENT_ONLY"
        if split == "dev"
        else "VALIDATION_PASSED_TEST_AUTHORIZED"
        if split == "validation" and checks.passed
        else "VALIDATION_REJECTED_TEST_FORBIDDEN"
        if split == "validation"
        else "TEST_COMPLETED_PROMOTED"
        if checks.passed
        else "TEST_COMPLETED_NOT_PROMOTED"
    )
    manifest = R4CampaignManifest(
        **manifest_fields,
        arms=arm_results,
        page_hit_at_5_delta=candidate.page_hit_at_5 - baseline.page_hit_at_5,
        page_ndcg_at_5_delta=candidate.page_ndcg_at_5 - baseline.page_ndcg_at_5,
        p95_latency_multiplier=(candidate.latency_ms_p95 / max(baseline.latency_ms_p95, 1e-9)),
        gate_checks=checks,
        decision=decision,
    )
    (run_dir / "manifest.json").write_bytes(_canonical_json_bytes(manifest.model_dump(mode="json")))
    return run_dir


def verify_r4_campaign(path: Path) -> R4CampaignManifest:
    run_dir = Path(path).resolve()
    manifest = R4CampaignManifest.model_validate_json((run_dir / "manifest.json").read_bytes())
    for arm in manifest.arms:
        if (
            hashlib.sha256((run_dir / f"{arm.arm}.jsonl").read_bytes()).hexdigest()
            != arm.details_sha256
        ):
            raise ValueError(f"R4 campaign {arm.arm} details hash mismatch")
    return manifest


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


__all__ = [
    "R4CampaignManifest",
    "build_gate_checks",
    "publish_r4_campaign",
    "verify_r4_campaign",
]
