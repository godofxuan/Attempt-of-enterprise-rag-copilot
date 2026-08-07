from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "docs" / "resume_metrics"
REQUIRED_CLOSEOUT = {
    "RAG_IMPROVEMENT_REPORT.md",
    "RAG_BASELINE_VS_FINAL.csv",
    "RAG_ABLATION.csv",
    "RAG_FAILURE_ANALYSIS.md",
    "RAG_NEGATIVE_RESULTS.md",
    "RAG_RESUME_METRICS.md",
    "RAG_INTERVIEW_GUIDE.md",
}
EVIDENCE_HASHES = {
    "financebench_dev_ablation_v1.json": (
        "b86b1078d2650bbf4db09bd5570425c2c064060a109e4ef292e1827f5ece41b9"
    ),
    "financebench_failure_analysis_v1.json": (
        "cb778da371c2f8261b9e84d7672213a2b35ccbd97152595b14cbe975fee55b1b"
    ),
    "garak_latent_report_holdout_v1.json": (
        "b2c56883079ef01510986452b61ac43d23e851ce35b6783efbb7094f5ddd21f9"
    ),
}


def _csv_rows(name: str) -> list[dict[str, str]]:
    with (METRICS / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_required_resume_closeout_files_exist() -> None:
    assert REQUIRED_CLOSEOUT <= {
        path.name for path in METRICS.iterdir() if path.is_file()
    }


def test_metrics_registry_rows_have_reproducibility_anchors() -> None:
    rows = _csv_rows("metrics.csv")

    assert rows
    for row in rows:
        assert re.fullmatch(r"[0-9a-f]{40}", row["git_sha"])
        assert re.fullmatch(r"[0-9a-f]{64}", row["artifact_sha256"])
        assert row["dataset"]
        assert row["split"]
        assert row["seed"]
        assert row["hardware"]
        assert row["command"]
        assert row["metric"]
        float(row["value"])


def test_public_evidence_and_summary_tables_are_consistent() -> None:
    evidence = json.loads(
        (
            METRICS / "evidence" / "garak_latent_report_holdout_v1.json"
        ).read_text(encoding="utf-8")
    )
    rows = _csv_rows("RAG_BASELINE_VS_FINAL.csv")
    asr = next(
        row
        for row in rows
        if row["dataset"] == "NVIDIA_garak_LatentInjectionReport"
        and row["metric"] == "attack_success_rate"
    )

    assert evidence["case_counts"] == {"attack": 12, "benign": 2}
    assert evidence["guard_off"]["attack_success_count"] == 4
    assert evidence["guard_on"]["attack_success_count"] == 0
    assert float(asr["baseline"]) == pytest.approx(
        evidence["guard_off"]["attack_success_rate"], abs=1e-7
    )
    assert float(asr["final"]) == pytest.approx(
        evidence["guard_on"]["attack_success_rate"], abs=1e-7
    )

    for path in (METRICS / "evidence").glob("*.json"):
        assert json.loads(path.read_text(encoding="utf-8"))["schema_version"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == EVIDENCE_HASHES[
            path.name
        ]


def test_ablation_decisions_do_not_promote_cross_encoder() -> None:
    rows = _csv_rows("RAG_ABLATION.csv")
    cross_encoder_rows = [
        row for row in rows if "cross_encoder" in row["configuration"]
    ]

    assert len(cross_encoder_rows) == 2
    assert {row["decision"] for row in cross_encoder_rows} == {
        "REJECT_NOT_PARETO"
    }
