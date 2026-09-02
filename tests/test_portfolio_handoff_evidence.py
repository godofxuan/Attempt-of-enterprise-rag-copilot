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
    wixqa = _json("docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json")[
        "results"
    ]["expertwritten_fixed_external"]["arms"]
    enterprise = _json("docs/enterprise_eval/evidence/enterprise_rag_bench_bm25_public_v1.json")
    garak = _json("docs/resume_metrics/evidence/garak_latent_report_holdout_v1.json")
    fts = _json("docs/final_evidence_closure/evidence/fts_hard_crash_matrix_v1.json")
    pointer = _json("docs/final_evidence_closure/evidence/active_pointer_crash_matrix_v1.json")
    candidate = _json("docs/multidoc_candidate/evidence/aggregate_v1.json")
    r5 = _json("docs/r5/evidence/uda_finance_r5_public_v1.json")
    ledger = _text(HANDOFFS / "RESUME_METRIC_LEDGER.md")

    assert wixqa["bm25"]["article_recall_at_5"] == pytest.approx(0.4275)
    assert wixqa["dense"]["article_recall_at_5"] == pytest.approx(0.6641666666666666)
    assert wixqa["bm25"]["ndcg_at_5"] == pytest.approx(0.3214579860909423)
    assert wixqa["dense"]["ndcg_at_5"] == pytest.approx(0.521583326944466)
    for expected in ("42.75% -> 66.42%", "32.15% -> 52.16%"):
        assert expected in ledger

    assert enterprise["dataset"]["document_row_count"] == 511_962
    assert enterprise["index"]["active_build_duration_ms"] == pytest.approx(231_349.29279994685)
    assert enterprise["index"]["artifact_byte_count"] == 1_472_634_880
    assert enterprise["index"]["build_peak_rss_bytes"] == 1_966_538_752
    for expected in ("511,962", "1.37 GiB", "231.35 s", "1.83 GiB"):
        assert expected in ledger

    assert garak["case_counts"] == {"attack": 12, "benign": 2}
    assert garak["guard_off"]["attack_success_count"] == 4
    assert garak["guard_on"]["attack_success_count"] == 0
    assert garak["guard_off"]["context_exposure_count"] == 12
    assert garak["guard_on"]["context_exposure_count"] == 0
    assert garak["guard_on"]["guard_latency_ms_mean"] == pytest.approx(1.4226714348686593)
    assert "ASR `4/12 -> 0/12`" in ledger
    assert "mean scan `1.42 ms`" in ledger

    assert fts["summary"]["trial_count"] == 30
    assert pointer["summary"]["trial_count"] == 12
    assert "`30/30`" in ledger
    assert "`12/12`" in ledger

    gate = candidate["combined_vs_current_gate"]
    assert gate["paired_fix_count"] == 0
    assert gate["citation_completeness_delta_pp"] == 0.0
    assert gate["citation_precision_delta_pp"] == pytest.approx(-5.833333333333335)
    assert gate["p95_latency_ratio"] == pytest.approx(1.8590358323863405)
    for expected in ("precision `-5.83pp`", "p95 `1.859x`", "fixes `0`"):
        assert expected in ledger

    assert r5["decision"] == "PROMOTED_FINANCE_KNOWN_REPORT_DEFAULT"
    assert r5["baseline"]["page_hit_at_5"] == pytest.approx(154 / 192)
    assert r5["candidate"]["page_hit_at_5"] == pytest.approx(169 / 192)
    assert r5["paired_outcomes"]["candidate_only_hit"] == 15
    assert r5["paired_outcomes"]["baseline_only_hit"] == 0
    for expected in ("80.21% -> 88.02%", "70.95% -> 77.60%", "38 -> 23"):
        assert expected in ledger


def test_vnext_closeout_supersedes_but_preserves_archived_handoffs() -> None:
    archived = "PORTFOLIO_ARCHIVED_READY_FOR_RESUME_AND_INTERVIEW"
    historical = "PORTFOLIO_READY_STOP_DEVELOPMENT"
    readme = _text(ROOT / "README.md")
    status = _text(ROOT / "PROJECT_STATUS.md")
    evidence_map = _text(HANDOFFS / "PROJECT_EVIDENCE_MAP.md")
    teaching = _text(HANDOFFS / "TEACHING_CODEX_HANDOFF.md")
    summary = _text(PACKAGE / "PROJECT_SUMMARY.md")
    resume_handoff = _text(HANDOFFS / "RESUME_CODEX_HANDOFF.md")

    for text in (
        readme,
        status,
        evidence_map,
        teaching,
        summary,
        resume_handoff,
    ):
        assert "RAG_VNEXT_CLOSED" in text

    for text in (status, evidence_map, teaching, summary, resume_handoff):
        assert "codex/agent-runtime-vnext" in text

    for text in (status, summary, resume_handoff):
        assert archived in text
        assert "histor" in text.lower()
    assert historical not in readme
    assert historical not in summary
    assert status.index("RAG_VNEXT_CLOSED") < status.index(archived)
    assert "Historical stages" in status


def test_project_evidence_map_points_to_real_code_tests_and_artifacts() -> None:
    evidence_map = _text(HANDOFFS / "PROJECT_EVIDENCE_MAP.md")
    for claim_id in (
        "P1",
        "P2",
        "P3",
        "P4",
        "P5",
        "P6",
        "P7",
        "P8",
        "P9",
        "P10",
        "P11",
        "N1",
    ):
        assert f"Claim {claim_id}:" in evidence_map
    expected_field_counts = {
        "| Claim |": 12,
        "| Metric |": 12,
        "| Scope |": 12,
        "| Dataset |": 11,
        "| Code path |": 12,
        "| Test path |": 12,
        "| Evidence JSON |": 11,
        "| Reproduction command |": 12,
        "| Code SHA |": 12,
        "| Allowed wording |": 12,
        "| Forbidden wording |": 12,
        "| Interview explanation |": 12,
    }
    for field, expected_count in expected_field_counts.items():
        assert evidence_map.count(field) == expected_count

    for relative_path in (
        "app/external_datasets/wixqa_retrieval.py",
        "app/external_datasets/enterprise_rag_bench_fts.py",
        "app/security/retrieved_content.py",
        "app/evaluation/garak_latent_report_eval.py",
        "app/agent/query_analysis.py",
        "app/agent/controller_v2.py",
        "app/agent/citation_verifier.py",
        "app/agent_runtime/orchestrator.py",
        "app/agent_runtime/tool_gateway.py",
        "app/agent_runtime/mcp_adapter.py",
        "app/agent_runtime/trajectory.py",
        "app/agent_runtime/replay.py",
        "app/agent_runtime/evalops_artifact.py",
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
        str(index) for index in range(1, 14)
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
        assert teaching.count(marker) == 13
    assert teaching.count("**Code/test exercise:**") == 13
    assert "docs/learning/AGENT_RUNTIME_TUTORIAL.md" in teaching

    assert re.findall(r"^## Story (\d+):", stories, flags=re.MULTILINE) == [
        str(index) for index in range(1, 14)
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
        assert stories.count(marker) == 13


def test_current_resume_and_provenance_surfaces_fail_closed() -> None:
    ledger = _text(HANDOFFS / "RESUME_METRIC_LEDGER.md")
    safe_metrics = _text(ROOT / "docs/resume/RESUME_SAFE_VNEXT_METRICS.md")
    final_cn = _text(PACKAGE / "FINAL_RESUME_ENTRY_CN.md")
    provenance_path = HANDOFFS / "THIRD_PARTY_PROVENANCE.md"
    provenance = _text(provenance_path)

    for category in (
        "VERIFIED_POSITIVE",
        "INTERVIEW_ONLY",
        "HISTORICAL_NEGATIVE",
        "FORBIDDEN_CLAIM",
    ):
        assert category in ledger
        assert category in safe_metrics

    assert "single numeric authority" in ledger
    for metric in (
        "42.75%",
        "66.42%",
        "32.15%",
        "52.16%",
        "511,962",
        "4/12",
        "0/12",
    ):
        assert metric in final_cn
        assert metric in ledger

    current_resume = final_cn.split("## 禁止表述", maxsplit=1)[0]
    assert "回答准确率 `66.42%`" not in current_resume
    assert "实现 LangGraph 提升答案质量" not in current_resume
    assert "LangGraph improved answer quality" not in current_resume
    assert "production network MCP" not in current_resume
    for forbidden in ("SOTA", "production-ready"):
        assert forbidden not in current_resume
    assert "实现“100% 安全”" not in current_resume

    assert provenance_path.stat().st_size > 1_000
    for required in (
        "API_USAGE",
        "CONCEPT_ONLY",
        "UNKNOWN",
        "https://github.com/langchain-ai/langgraph",
        "https://github.com/modelcontextprotocol/python-sdk",
        "https://github.com/anthropics/claude-code",
    ):
        assert required in provenance
    assert "repository root has no declared license" in provenance.lower()


def test_canonical_handoff_paths_exist() -> None:
    current_paths = (
        "PROJECT_STATUS.md",
        "docs/handoffs/PROJECT_EVIDENCE_MAP.md",
        "docs/handoffs/RESUME_METRIC_LEDGER.md",
        "docs/handoffs/resume_package/FINAL_RESUME_ENTRY_CN.md",
        "docs/handoffs/TEACHING_CODEX_HANDOFF.md",
        "docs/handoffs/INTERVIEW_STORY_BANK.md",
        "docs/learning/RAG_PROJECT_TEACHING_HANDOFF.md",
        "docs/learning/AGENT_RUNTIME_TUTORIAL.md",
        "docs/agent_runtime/10_FINAL_ARCHITECTURE.md",
        "docs/agent_runtime/09_SECURITY_REVIEW.md",
        "docs/agent_runtime/08_AB_EVALUATION.md",
        "docs/resume/RESUME_SAFE_VNEXT_METRICS.md",
        "docs/handoffs/THIRD_PARTY_PROVENANCE.md",
        "docs/handoffs/VNEXT_CROSS_SURFACE_AUDIT_20260820.md",
    )
    for relative_path in current_paths:
        assert (ROOT / relative_path).is_file(), relative_path

    teaching = _text(HANDOFFS / "TEACHING_CODEX_HANDOFF.md")
    for relative_path in (
        "docs/handoffs/PROJECT_EVIDENCE_MAP.md",
        "docs/learning/RAG_PROJECT_TEACHING_HANDOFF.md",
        "docs/learning/AGENT_RUNTIME_TUTORIAL.md",
        "docs/agent_runtime/10_FINAL_ARCHITECTURE.md",
        "docs/agent_runtime/09_SECURITY_REVIEW.md",
        "docs/agent_runtime/08_AB_EVALUATION.md",
        "docs/resume/RESUME_SAFE_VNEXT_METRICS.md",
        "docs/handoffs/INTERVIEW_STORY_BANK.md",
    ):
        assert relative_path in teaching


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
