from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = REPOSITORY_ROOT / "docs/external_datasets/evidence"
PUBLIC_EVIDENCE = (
    "finqa_role_query_planner_v1_calibration_public_v1.json",
    "finqa_role_query_planner_v2_calibration_public_v1.json",
    "finqa_role_query_planner_llm_v1_calibration_public_v1.json",
    "finqa_descriptor_catalog_upper_bound_public_v1.json",
    "finqa_descriptor_catalog_upper_bound_public_v2.json",
    "finqa_descriptor_selector_live_public_v1.json",
    "finqa_descriptor_retriever_public_v1.json",
    "finqa_descriptor_retriever_public_v2.json",
    "finqa_descriptor_retriever_public_v3.json",
    "finqa_descriptor_retriever_public_v4.json",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_e7_public_evidence_still_matches_bound_implementations() -> None:
    for filename in PUBLIC_EVIDENCE:
        payload = json.loads((EVIDENCE_ROOT / filename).read_text(encoding="ascii"))
        assert payload["serving_route_status"] == "DISABLED"
        for relative, expected in payload["implementation_sha256"].items():
            assert _sha256(REPOSITORY_ROOT / relative) == expected, (
                filename,
                relative,
            )


def test_e7_lineage_preserves_negative_results_and_upper_bound_boundary() -> None:
    catalog_v2 = json.loads(
        (EVIDENCE_ROOT / "finqa_descriptor_catalog_upper_bound_public_v2.json")
        .read_text(encoding="ascii")
    )
    selector = json.loads(
        (EVIDENCE_ROOT / "finqa_descriptor_selector_live_public_v1.json")
        .read_text(encoding="ascii")
    )
    retrievers = [
        json.loads(
            (EVIDENCE_ROOT / f"finqa_descriptor_retriever_public_v{version}.json")
            .read_text(encoding="ascii")
        )
        for version in range(1, 5)
    ]

    assert catalog_v2["decision"] == "ORACLE_CATALOG_GATE_PASSED"
    assert catalog_v2["oracle_role_recall_at_8"] == 1.0
    assert selector["decision"] == "LIVE_DESCRIPTOR_SELECTOR_GATE_FAILED"
    assert all("FAILED" in item["decision"] for item in retrievers)
    assert all(item["serving_route_status"] == "DISABLED" for item in retrievers)
    assert retrievers[1]["role_recall_at_4"] > retrievers[0]["role_recall_at_4"]
    assert retrievers[2]["role_recall_at_4"] < retrievers[1]["role_recall_at_4"]
    assert retrievers[3]["role_recall_at_8"] > retrievers[1]["role_recall_at_8"]
