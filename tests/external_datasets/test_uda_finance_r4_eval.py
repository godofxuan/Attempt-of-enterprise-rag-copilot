from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.external_datasets.uda_finance_page_eval import UdaFinancePageSummary
from app.external_datasets.uda_finance_r4 import load_uda_finance_r4_protocol
from app.external_datasets.uda_finance_r4_eval import build_gate_checks
from app.indexing.resumable_embeddings import ResumableEmbeddingSummary
from scripts.build_uda_finance_r4_index import embedding_summary_payload
from scripts.eval_uda_finance_r4_pages import (
    claim_split_execution,
    complete_split_execution,
    require_development_authorization,
    require_validation_authorization,
)


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
        latency_ms_mean=p95 * 0.8,
        latency_ms_p50=p95 * 0.8,
        latency_ms_p95=p95,
        embedding_calls=64,
    )


def test_r4_gate_requires_quality_and_latency_together() -> None:
    protocol, _ = load_uda_finance_r4_protocol()
    checks = build_gate_checks(
        baseline=_summary(hit=0.70, ndcg=0.60, p95=200),
        candidate=_summary(hit=0.76, ndcg=0.64, p95=250),
        protocol=protocol,
    )

    assert checks.passed


def test_r4_gate_rejects_ndcg_only_gain() -> None:
    protocol, _ = load_uda_finance_r4_protocol()
    checks = build_gate_checks(
        baseline=_summary(hit=0.70, ndcg=0.60, p95=200),
        candidate=_summary(hit=0.73, ndcg=0.65, p95=210),
        protocol=protocol,
    )

    assert not checks.passed
    assert not checks.min_page_hit_at_5_delta


def test_validation_marker_is_one_shot_and_authorizes_only_pass(tmp_path: Path) -> None:
    marker = claim_split_execution(
        tmp_path,
        split="validation",
        run_id="r4-validation-v1",
        code_revision="a" * 40,
        protocol_sha256="b" * 64,
        cases_sha256="c" * 64,
    )
    with pytest.raises(FileExistsError):
        claim_split_execution(
            tmp_path,
            split="validation",
            run_id="r4-validation-v2",
            code_revision="a" * 40,
            protocol_sha256="b" * 64,
            cases_sha256="c" * 64,
        )
    complete_split_execution(
        marker,
        result_manifest_sha256="d" * 64,
        decision="VALIDATION_PASSED_TEST_AUTHORIZED",
    )

    require_validation_authorization(tmp_path)
    assert json.loads(marker.read_text(encoding="utf-8"))["status"] == "COMPLETED"


def test_failed_validation_forbids_test(tmp_path: Path) -> None:
    marker = claim_split_execution(
        tmp_path,
        split="validation",
        run_id="r4-validation-v1",
        code_revision="a" * 40,
        protocol_sha256="b" * 64,
        cases_sha256="c" * 64,
    )
    complete_split_execution(
        marker,
        result_manifest_sha256="d" * 64,
        decision="VALIDATION_REJECTED_TEST_FORBIDDEN",
    )

    with pytest.raises(ValueError, match="not authorized"):
        require_validation_authorization(tmp_path)


def _write_development_campaign(root: Path, *, passed: bool = True) -> None:
    run_dir = root / "r4-dev-v3"
    run_dir.mkdir()
    empty_sha = hashlib.sha256(b"").hexdigest()
    for arm in ("dense_chunk", "focused_page_fusion"):
        (run_dir / f"{arm}.jsonl").write_bytes(b"")
    summary = _summary(hit=0.8, ndcg=0.7, p95=100).model_dump(mode="json")
    manifest = {
        "schema_version": "uda_finance_r4_campaign_v1",
        "run_id": "r4-dev-v3",
        "split": "dev",
        "code_revision": "a" * 40,
        "protocol_sha256": "b" * 64,
        "dataset_manifest_sha256": "c" * 64,
        "cases_sha256": "d" * 64,
        "index_run_id": "index-r4",
        "index_manifest_sha256": "e" * 64,
        "embedding_model": "bge-m3",
        "arms": [
            {"arm": arm, "summary": summary, "details_sha256": empty_sha}
            for arm in ("dense_chunk", "focused_page_fusion")
        ],
        "page_hit_at_5_delta": 0.05,
        "page_ndcg_at_5_delta": 0.03,
        "p95_latency_multiplier": 1.1,
        "gate_checks": {
            "min_page_hit_at_5_delta": passed,
            "min_page_ndcg_at_5_delta": True,
            "max_p95_latency_multiplier": True,
        },
        "decision": "DEVELOPMENT_ONLY",
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_development_authorization_binds_sha_protocol_cases_and_gates(
    tmp_path: Path,
) -> None:
    _write_development_campaign(tmp_path)

    require_development_authorization(
        tmp_path,
        run_id="r4-dev-v3",
        code_revision="a" * 40,
        protocol_sha256="b" * 64,
        cases_sha256="d" * 64,
    )

    with pytest.raises(ValueError, match="does not authorize"):
        require_development_authorization(
            tmp_path,
            run_id="r4-dev-v3",
            code_revision="f" * 40,
            protocol_sha256="b" * 64,
            cases_sha256="d" * 64,
        )


def test_failed_development_gate_forbids_validation(tmp_path: Path) -> None:
    _write_development_campaign(tmp_path, passed=False)

    with pytest.raises(ValueError, match="does not authorize"):
        require_development_authorization(
            tmp_path,
            run_id="r4-dev-v3",
            code_revision="a" * 40,
            protocol_sha256="b" * 64,
            cases_sha256="d" * 64,
        )


def test_embedding_summary_report_serializes_dataclass(tmp_path: Path) -> None:
    payload = embedding_summary_payload(
        ResumableEmbeddingSummary(
            build_id="a" * 64,
            cache_dir=tmp_path,
            total_batches=2,
            cache_hit_batches=2,
            computed_batches=0,
            recomputed_batches=0,
            vector_count=10,
            dimension=1024,
        )
    )

    assert payload["cache_dir"] == str(tmp_path)
    assert payload["cache_hit_batches"] == 2
