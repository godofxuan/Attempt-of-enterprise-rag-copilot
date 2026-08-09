from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WIXQA = ROOT / "docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json"
CLEAN = ROOT / "docs/reproduction/evidence/wixqa_clean_reproduction_public_v1.json"
ENTERPRISE = ROOT / "docs/enterprise_eval/evidence/enterprise_rag_bench_bm25_public_v1.json"
SENSITIVITY = (
    ROOT
    / "docs/final_closeout/evidence/enterprise_reused_source_id_sensitivity_v1.json"
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_clean_reproduction_is_exact_and_self_contained() -> None:
    historical = _json(WIXQA)
    replay = _json(CLEAN)

    assert replay["status"] == "VERIFIED"
    assert replay["quality_absolute_tolerance"] == 0.0
    assert replay["quality_difference_count"] == 0
    assert replay["quality_differences"] == []
    assert all(replay["identity_matches"].values())
    assert replay["clean_root_contract_satisfied"] is True

    observed = replay["quality_observation"]
    comparison_count = 0
    for cohort, expected_cohort in historical["results"].items():
        for arm, expected_arm in expected_cohort["arms"].items():
            for metric, values in observed[cohort][arm].items():
                comparison_count += 1
                assert values["historical"] == expected_arm[metric]
                assert values["candidate"] == expected_arm[metric]
                assert values["delta"] in (0.0, None)
    assert comparison_count == 63


def test_resume_headline_metrics_derive_from_public_evidence() -> None:
    wixqa = _json(WIXQA)["results"]["expertwritten_fixed_external"]["arms"]
    enterprise = _json(ENTERPRISE)
    sensitivity = _json(SENSITIVITY)

    assert wixqa["bm25"]["article_recall_at_5"] == pytest.approx(0.4275)
    assert wixqa["dense"]["article_recall_at_5"] == pytest.approx(
        0.6641666666666666
    )
    assert wixqa["bm25"]["ndcg_at_5"] == pytest.approx(0.3214579860909423)
    assert wixqa["dense"]["ndcg_at_5"] == pytest.approx(0.521583326944466)
    assert wixqa["dense"]["latency_ms_p95"] == pytest.approx(
        157.40569995250553
    )

    assert enterprise["metrics"]["overall"][
        "macro_document_recall_at_5"
    ] == pytest.approx(
        sensitivity["published_macro_recall_at_5"]
    )
    assert sensitivity["record_aware_macro_recall_at_5"] == pytest.approx(
        0.6026773049645389
    )
    assert sensitivity["macro_recall_at_5_reduction_percentage_points"] == (
        pytest.approx(0.10638297872340426)
    )
    assert sensitivity["affected_question_count"] == 1
    assert sensitivity["reused_source_id_group_count"] == 4


def test_recruiter_documents_point_to_current_evidence() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    status = (ROOT / "docs/PROJECT_STATUS.md").read_text(encoding="utf-8")
    resume = (ROOT / "docs/handoffs/RESUME_CODEX_UPDATE.md").read_text(
        encoding="utf-8"
    )
    safe = (ROOT / "docs/enterprise_eval/RESUME_SAFE_METRICS.md").read_text(
        encoding="utf-8"
    )

    for text in (readme, status, resume):
        assert "66.42%" in text
        assert "52.16%" in text
        positive_claims = text.split("## Forbidden claims", 1)[0]
        assert "answer accuracy 66.42%" not in positive_claims.lower()
    assert "wixqa_clean_reproduction_public_v1.json" in readme
    assert "02_REUSED_SOURCE_ID_SENSITIVITY.md" in readme
    assert "wixqa_retrieval_baseline_public_v2.json" in safe
    assert "wixqa_retrieval_baseline_public_v1.json" not in safe


def test_learning_and_demo_handoffs_are_complete() -> None:
    interview = (ROOT / "docs/learning/RAG_INTERVIEW_UPDATE.md").read_text(
        encoding="utf-8"
    )
    teaching = (ROOT / "docs/learning/RAG_PROJECT_TEACHING_HANDOFF.md").read_text(
        encoding="utf-8"
    )
    demo = (ROOT / "docs/demo/INTERVIEW_DEMO_RUNBOOK.md").read_text(
        encoding="utf-8"
    )

    questions = re.findall(r"^## (\d+)\.", interview, flags=re.MULTILINE)
    assert len(questions) >= 35
    assert questions[-1] == "35"
    for required in (
        "Clean root",
        "Transport versus semantics",
        "Business ID versus physical identity",
        "练习问题",
    ):
        assert required in teaching
    assert "Ten-minute path" in demo
    assert "Twenty-minute path" in demo
    assert "Failure-safe path" in demo
