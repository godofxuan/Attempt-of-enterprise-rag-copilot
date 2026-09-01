from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.external_datasets.uda_finance_page_eval import UdaFinancePageSummary
from app.external_datasets.uda_finance_r4_eval import R4CampaignManifest
from app.external_datasets.uda_finance_r4_public import (
    build_r4_public_evidence,
    canonical_json_bytes,
    verify_r4_public_evidence,
)

ROOT = Path(__file__).resolve().parents[2]


def _summary(*, hit: float, ndcg: float, p95: float) -> UdaFinancePageSummary:
    return UdaFinancePageSummary(
        case_count=64,
        page_hit_at_1=hit,
        page_hit_at_3=hit,
        page_hit_at_5=hit,
        page_mrr_at_5=ndcg,
        page_ndcg_at_5=ndcg,
        macro_page_recall_at_5=hit,
        page_locator_coverage_at_5=1.0,
        latency_ms_mean=p95,
        latency_ms_p50=p95,
        latency_ms_p95=p95,
        embedding_calls=64,
    )


def _campaign(*, split: str, decision: str) -> R4CampaignManifest:
    baseline = _summary(hit=0.70, ndcg=0.60, p95=100)
    candidate = _summary(hit=0.75 if split == "dev" else 0.74, ndcg=0.68, p95=110)
    passed = split == "dev"
    return R4CampaignManifest(
        run_id=f"r4-{split}",
        split=split,
        code_revision="a" * 40,
        protocol_sha256="b" * 64,
        dataset_manifest_sha256="c" * 64,
        cases_sha256="d" * 64,
        index_run_id="index-r4",
        index_manifest_sha256="e" * 64,
        embedding_model="bge-m3",
        arms=[
            {"arm": "dense_chunk", "summary": baseline, "details_sha256": "f" * 64},
            {
                "arm": "focused_page_fusion",
                "summary": candidate,
                "details_sha256": "1" * 64,
            },
        ],
        page_hit_at_5_delta=candidate.page_hit_at_5 - baseline.page_hit_at_5,
        page_ndcg_at_5_delta=candidate.page_ndcg_at_5 - baseline.page_ndcg_at_5,
        p95_latency_multiplier=1.1,
        gate_checks={
            "min_page_hit_at_5_delta": passed,
            "min_page_ndcg_at_5_delta": True,
            "max_p95_latency_multiplier": True,
        },
        decision=decision,
    )


def test_public_evidence_binds_paired_runs_without_case_content(tmp_path: Path) -> None:
    protocol = tmp_path / "protocol.json"
    protocol.write_bytes(b"{}")
    protocol_sha = hashlib.sha256(protocol.read_bytes()).hexdigest()
    development = _campaign(split="dev", decision="DEVELOPMENT_ONLY").model_copy(
        update={"protocol_sha256": protocol_sha}
    )
    validation = _campaign(
        split="validation",
        decision="VALIDATION_REJECTED_TEST_FORBIDDEN",
    ).model_copy(update={"protocol_sha256": protocol_sha})
    evidence = build_r4_public_evidence(
        development=development,
        development_manifest_sha256="2" * 64,
        validation=validation,
        validation_manifest_sha256="3" * 64,
        repository_revision="a" * 40,
    )
    output = tmp_path / "evidence.json"
    output.write_bytes(canonical_json_bytes(evidence))

    verified = verify_r4_public_evidence(output, protocol_path=protocol)

    assert verified.promotion_decision == "REJECTED"
    assert verified.frozen_test_status == "NOT_RUN_VALIDATION_GATE_FORBIDS"
    serialized = output.read_text(encoding="utf-8")
    for forbidden in ('"questions":', '"answers":', '"company_id":', '"source_path":'):
        assert forbidden not in serialized


def test_public_evidence_rejects_changed_code_between_splits() -> None:
    development = _campaign(split="dev", decision="DEVELOPMENT_ONLY")
    validation = _campaign(
        split="validation",
        decision="VALIDATION_REJECTED_TEST_FORBIDDEN",
    ).model_copy(update={"code_revision": "9" * 40})

    with pytest.raises(ValueError, match="changed code_revision"):
        build_r4_public_evidence(
            development=development,
            development_manifest_sha256="2" * 64,
            validation=validation,
            validation_manifest_sha256="3" * 64,
            repository_revision="a" * 40,
        )


def test_checked_in_r4_public_evidence_preserves_rejected_decision() -> None:
    evidence = verify_r4_public_evidence(
        ROOT / "docs" / "r4" / "evidence" / "uda_finance_r4_public_v1.json",
        protocol_path=(ROOT / "docs" / "r4" / "evidence" / "uda_finance_r4_protocol_v3.json"),
    )

    assert evidence.validation.arms[0].summary.page_hit_at_5 == pytest.approx(0.765625)
    assert evidence.validation.arms[1].summary.page_hit_at_5 == pytest.approx(0.8125)
    assert evidence.validation.page_ndcg_at_5_delta == pytest.approx(0.08199434843657438)
    assert not evidence.validation.gate_checks.min_page_hit_at_5_delta
    assert evidence.promotion_decision == "REJECTED"
    assert evidence.frozen_test_status == "NOT_RUN_VALIDATION_GATE_FORBIDS"
