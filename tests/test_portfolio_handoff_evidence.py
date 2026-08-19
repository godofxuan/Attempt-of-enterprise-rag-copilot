from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HANDOFFS = ROOT / "docs" / "handoffs"
PACKAGE = HANDOFFS / "resume_package"


def _json(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_resume_metric_ledger_derives_from_frozen_public_evidence() -> None:
    wixqa = _json(
        "docs/enterprise_eval/evidence/"
        "wixqa_retrieval_baseline_public_v2.json"
    )["results"]["expertwritten_fixed_external"]["arms"]
    enterprise = _json(
        "docs/enterprise_eval/evidence/"
        "enterprise_rag_bench_bm25_public_v1.json"
    )
    garak = _json(
        "docs/resume_metrics/evidence/garak_latent_report_holdout_v1.json"
    )
    fts = _json(
        "docs/final_evidence_closure/evidence/fts_hard_crash_matrix_v1.json"
    )
    pointer = _json(
        "docs/final_evidence_closure/evidence/"
        "active_pointer_crash_matrix_v1.json"
    )
    candidate = _json(
        "docs/multidoc_candidate/evidence/aggregate_v1.json"
    )
    ledger = _text(HANDOFFS / "RESUME_METRIC_LEDGER.md")

    assert wixqa["bm25"]["article_recall_at_5"] == pytest.approx(0.4275)
    assert wixqa["dense"]["article_recall_at_5"] == pytest.approx(
        0.6641666666666666
    )
    assert wixqa["bm25"]["ndcg_at_5"] == pytest.approx(0.3214579860909423)
    assert wixqa["dense"]["ndcg_at_5"] == pytest.approx(0.521583326944466)
    for expected in ("42.75% -> 66.42%", "32.15% -> 52.16%"):
        assert expected in ledger

    assert enterprise["dataset"]["document_row_count"] == 511_962
    assert enterprise["index"]["active_build_duration_ms"] == pytest.approx(
        231_349.29279994685
    )
    assert enterprise["index"]["artifact_byte_count"] == 1_472_634_880
    assert enterprise["index"]["build_peak_rss_bytes"] == 1_966_538_752
    for expected in ("511,962", "1.37 GiB", "231.35 s", "1.83 GiB"):
        assert expected in ledger

    assert garak["case_counts"] == {"attack": 12, "benign": 2}
    assert garak["guard_off"]["attack_success_count"] == 4
    assert garak["guard_on"]["attack_success_count"] == 0
    assert garak["guard_off"]["context_exposure_count"] == 12
    assert garak["guard_on"]["context_exposure_count"] == 0
    assert garak["guard_on"]["guard_latency_ms_mean"] == pytest.approx(
        1.4226714348686593
    )
    assert "ASR `4/12 -> 0/12`" in ledger
    assert "mean scan `1.42 ms`" in ledger

    assert fts["summary"]["trial_count"] == 30
    assert pointer["summary"]["trial_count"] == 12
    assert "`30/30`" in ledger
    assert "`12/12`" in ledger

    gate = candidate["combined_vs_current_gate"]
    assert gate["paired_fix_count"] == 0
    assert gate["citation_completeness_delta_pp"] == 0.0
    assert gate["citation_precision_delta_pp"] == pytest.approx(
        -5.833333333333335
    )
    assert gate["p95_latency_ratio"] == pytest.approx(1.8590358323863405)
    for expected in ("precision `-5.83pp`", "p95 `1.859x`", "fixes `0`"):
        assert expected in ledger


def test_canonical_portfolio_state_has_one_current_entry_point() -> None:
    current = "PORTFOLIO_ARCHIVED_READY_FOR_RESUME_AND_INTERVIEW"
    historical = "PORTFOLIO_READY_STOP_DEVELOPMENT"
    readme = _text(ROOT / "README.md")
    status = _text(ROOT / "PROJECT_STATUS.md")
    summary = _text(PACKAGE / "PROJECT_SUMMARY.md")
    resume_handoff = _text(HANDOFFS / "RESUME_CODEX_HANDOFF.md")

    for text in (readme, status, summary, resume_handoff):
        assert current in text
    assert historical not in readme
    assert historical not in summary
    assert "only current portfolio enum" in status
    assert "HISTORICAL" in status


def test_project_evidence_map_points_to_real_code_tests_and_artifacts() -> None:
    evidence_map = _text(HANDOFFS / "PROJECT_EVIDENCE_MAP.md")
    for claim_id in ("P1", "P2", "P3", "P4", "P5", "P6", "N1"):
        assert f"Claim {claim_id}:" in evidence_map
    for field in (
        "| Claim |",
        "| Metric |",
        "| Scope |",
        "| Dataset |",
        "| Code path |",
        "| Test path |",
        "| Evidence JSON |",
        "| Reproduction command |",
        "| Code SHA |",
        "| Allowed wording |",
        "| Forbidden wording |",
        "| Interview explanation |",
    ):
        assert evidence_map.count(field) == 7

    for relative_path in (
        "app/external_datasets/wixqa_retrieval.py",
        "app/external_datasets/enterprise_rag_bench_fts.py",
        "app/security/retrieved_content.py",
        "app/evaluation/garak_latent_report_eval.py",
        "app/agent/query_analysis.py",
        "app/agent/controller_v2.py",
        "app/agent/citation_verifier.py",
        "app/evaluation/wixqa_multidoc_candidate.py",
        "tests/external_datasets/test_wixqa_public_evidence.py",
        "tests/test_final_evidence_closure.py",
        "tests/evaluation/test_wixqa_multidoc_candidate_evidence.py",
    ):
        assert (ROOT / relative_path).is_file(), relative_path
        assert relative_path in evidence_map or relative_path in _text(
            HANDOFFS / "TEACHING_CODEX_HANDOFF.md"
        )


def test_teaching_and_story_handoffs_cover_required_modules() -> None:
    teaching = _text(HANDOFFS / "TEACHING_CODEX_HANDOFF.md")
    stories = _text(HANDOFFS / "INTERVIEW_STORY_BANK.md")

    assert re.findall(r"^## Module (\d+):", teaching, flags=re.MULTILINE) == [
        str(index) for index in range(1, 9)
    ]
    for marker in (
        "**Foundation:**",
        "**Source trace:**",
        "**Design reason:**",
        "**Alternative:**",
        "**Trade-off:**",
        "**Interview question:**",
        "**Reference answer:**",
        "**Follow-up:**",
        "**Learner answer target:**",
    ):
        assert teaching.count(marker) == 8

    assert re.findall(r"^## Story (\d+):", stories, flags=re.MULTILINE) == [
        str(index) for index in range(1, 9)
    ]
    for marker in (
        "**Situation:**",
        "**Problem:**",
        "**Hypothesis:**",
        "**Experiment:**",
        "**Result:**",
        "**Decision:**",
        "**Trade-off:**",
        "**What I learned:**",
    ):
        assert stories.count(marker) == 8


def test_resume_package_is_complete_and_fail_closed() -> None:
    expected = {
        "PROJECT_SUMMARY.md",
        "ROLE_POSITIONING.md",
        "SAFE_METRICS.md",
        "BULLET_CANDIDATES.md",
        "FINAL_RESUME_ENTRY_CN.md",
        "EVIDENCE_MAP.md",
        "FORBIDDEN_CLAIMS.md",
        "INTERVIEW_STORIES.md",
        "JD_KEYWORD_MAP.md",
    }
    assert {path.name for path in PACKAGE.glob("*.md")} == expected

    final_cn = _text(PACKAGE / "FINAL_RESUME_ENTRY_CN.md")
    for required in (
        "66.42%",
        "511,962",
        "4/12",
        "Evidence Ledger",
        "不写“Agent 效果优于固定 RAG”",
        "不写“100% 安全”",
    ):
        assert required in final_cn

    bullets = _text(PACKAGE / "BULLET_CANDIDATES.md")
    assert bullets.count("## Version A:") == 1
    assert bullets.count("## Version B:") == 1
    assert bullets.count("## Version C:") == 1
    for index in range(1, 6):
        assert bullets.count(f"{index}. ") == 3

    forbidden = _text(PACKAGE / "FORBIDDEN_CLAIMS.md")
    for phrase in (
        "RAG accuracy 66.42%",
        "100% secure",
        "Production-ready",
        "independent third-party",
        "NO_EVIDENCE",
    ):
        assert phrase in forbidden


def test_jd_snapshot_uses_bounded_official_sources() -> None:
    jd_map = _text(PACKAGE / "JD_KEYWORD_MAP.md")
    urls = re.findall(r"\]\((https://[^)]+)\)", jd_map)
    assert len(urls) == 12
    assert all(
        any(
            domain in url
            for domain in (
                "talent.baidu.com",
                "jobs.apple.com",
                "nvidia.wd5.myworkdayjobs.com",
            )
        )
        for url in urls
    )
    assert "Snapshot date: 2026-08-11" in jd_map
    assert "not a statistical study" in " ".join(jd_map.split())
    assert jd_map.count("`NO_EVIDENCE`") >= 2
