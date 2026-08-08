from __future__ import annotations

from pathlib import Path


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
    }
    assert expected <= {path.name for path in DOCS.iterdir()}
    assert AUDIT_SHA in _read("PRE_FLIGHT.md")


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


def test_new_dataset_consumption_is_frozen_before_download() -> None:
    ledger = _read("CONSUMPTION_LEDGER.md")
    for status in (
        "UNTOUCHED",
        "DEVELOPMENT",
        "VALIDATION",
        "FIXED_CONSUMED",
        "REGRESSION_ONLY",
    ):
        assert status in ledger
    assert "WixQA Synthetic" in ledger and "DEVELOPMENT" in ledger
    assert "WixQA Simulated" in ledger and "VALIDATION" in ledger
    assert "WixQA ExpertWritten" in ledger and "UNTOUCHED" in ledger
