from __future__ import annotations

from pathlib import Path

import json


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "enterprise_eval"
AUDIT_SHA = "d9c7294d59b166523febfcfe3b23a23c3c66b9b1"


def _read(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def test_enterprise_preflight_package_is_complete() -> None:
    expected = {
        "README.md",
        "PRE_FLIGHT.md",
        "BENCHMARK_GAP_ANALYSIS.md",
        "DATASET_SELECTION.md",
        "DATA_PROCESSING_DESIGN.md",
        "CONSUMPTION_LEDGER.md",
        "CAPACITY_PLAN.md",
        "EXPERIMENT_REGISTRY.md",
        "FINAL_REPORT.md",
        "RESUME_SAFE_METRICS.md",
    }
    assert expected <= {path.name for path in DOCS.iterdir()}
    assert AUDIT_SHA in _read("PRE_FLIGHT.md")


def test_enterprise_closeout_keeps_measured_and_unmeasured_claims_separate() -> None:
    report = _read("FINAL_REPORT.md")
    resume = _read("RESUME_SAFE_METRICS.md")
    for required in (
        "WixQA ExpertWritten is the primary benchmark",
        "511,962",
        "AGENTIC_ROUTE_REJECTED",
        "Answer correctness was",
        "Source-aware chunking",
        "Stop broad feature development",
    ):
        assert required in report
    assert "retrieval, not answer accuracy" in resume
    assert "must not claim Agent quality improvement" in resume


def test_learning_handoff_maps_resume_claims_to_evidence() -> None:
    learning = ROOT / "docs" / "learning"
    handoff = (learning / "RAG_PROJECT_TEACHING_HANDOFF.md").read_text(
        encoding="utf-8"
    )
    mapping = (learning / "RESUME_BULLET_EVIDENCE_MAP.md").read_text(
        encoding="utf-8"
    )
    assert "enterprise_rag_bench_fts.py" in handoff
    assert "07b156ed4d1b4e7ff24a06aac7a8d8b41630e03b" in mapping
    assert "检索 Recall@5" in mapping


def test_primary_selection_is_bounded_and_revision_pinned() -> None:
    selection = _read("DATASET_SELECTION.md")
    for dataset, revision in {
        "WixQA": "d662dc42479c14e202eccd832f8c4b66a035c4cc",
        "EnterpriseRAG-Bench": "d36685e273713975ee20299bbf1ab64165575b3c",
        "HERB": "db3bf9b3f911745726c579c9dbf9f7f6b2c05b36",
    }.items():
        assert dataset in selection
        assert revision in selection
    assert "capped at WixQA, EnterpriseRAG-Bench, and conditional HERB" in selection


def test_claim_boundaries_cover_known_overstatements() -> None:
    preflight = _read("PRE_FLIGHT.md")
    gap = _read("BENCHMARK_GAP_ANALYSIS.md")
    capacity = _read("CAPACITY_PLAN.md")
    assert "not autonomous `search -> find -> open`" in preflight
    assert "COMPLEX_DOCUMENT_TABLE_STRESS" in gap
    assert "must not report a formal benchmark score" in capacity


def test_dataset_consumption_statuses_are_explicit() -> None:
    ledger = _read("CONSUMPTION_LEDGER.md")
    for status in (
        "UNTOUCHED",
        "DEVELOPMENT",
        "VALIDATION",
        "FIXED_CONSUMED",
        "REGRESSION_ONLY",
    ):
        assert status in ledger
    assert "WixQA Synthetic | DEVELOPMENT" in ledger
    assert "WixQA Simulated | VALIDATION" in ledger
    assert "WixQA ExpertWritten | FIXED_CONSUMED" in ledger


def test_wixqa_public_baseline_preserves_claim_boundaries() -> None:
    payload = json.loads(
        (DOCS / "evidence" / "wixqa_retrieval_baseline_public_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["claims"]["retrieval_champion"] == "dense"
    assert payload["claims"]["blind_holdout"] is False
    assert payload["claims"]["answer_correctness"] == "NOT_RUN"
    fixed = payload["results"]["expertwritten_fixed_external"]
    assert fixed["dense"]["article_recall_at_5"] > fixed["equal_rrf"]["article_recall_at_5"]
    assert fixed["dense"]["multi_article_completeness_at_5"] > fixed["equal_rrf"]["multi_article_completeness_at_5"]


def test_enterprise_full_corpus_and_agent_public_results_are_bounded() -> None:
    evidence = DOCS / "evidence"
    enterprise = json.loads(
        (evidence / "enterprise_rag_bench_bm25_public_v1.json").read_text(
            encoding="utf-8"
        )
    )
    agent = json.loads(
        (evidence / "wixqa_agent_public_v1.json").read_text(encoding="utf-8")
    )
    assert enterprise["dataset"]["document_row_count"] == 511_962
    assert enterprise["claim_boundary"]["retrieval_only"] is True
    assert enterprise["claim_boundary"]["answer_quality"] == "NOT_MEASURED"
    assert enterprise["metrics"]["overall"]["macro_document_recall_at_5"] < 1
    for cohort in agent["cohorts"].values():
        summary = cohort["summary"]
        assert summary["search_calls_mean"] == 1
        assert summary["find_calls_mean"] == 0
        assert summary["open_calls_mean"] == 0
        assert summary["search_evidence_recall"] == summary["b2_recall_at_5"]
        assert summary["multi_article_citation_complete"] == 0
