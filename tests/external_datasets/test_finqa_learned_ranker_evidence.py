from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.external_datasets.finqa_learned_descriptor_ranker_v1 import (
    load_learned_descriptor_ranker_artifact_v1,
)
from app.external_datasets.finqa_learned_ranker_protocol_v1 import (
    load_learned_ranker_protocol_v1,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = REPOSITORY_ROOT / "docs/external_datasets/evidence"


def _load(name: str) -> dict[str, object]:
    payload = json.loads((EVIDENCE_ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sha256(relative: str) -> str:
    return hashlib.sha256((REPOSITORY_ROOT / relative).read_bytes()).hexdigest()


def test_e9_cv_and_artifact_authorization_chain_is_complete() -> None:
    protocol, protocol_sha256 = load_learned_ranker_protocol_v1(
        EVIDENCE_ROOT / "finqa_learned_ranker_protocol_v1.json"
    )
    artifact = load_learned_descriptor_ranker_artifact_v1(
        EVIDENCE_ROOT / "finqa_learned_descriptor_ranker_artifact_v1.json"
    )
    cv = _load("finqa_learned_descriptor_cv_public_v1.json")

    assert cv["protocol_sha256"] == protocol_sha256 == artifact.protocol_sha256
    assert cv["artifact_sha256"] == artifact.artifact_sha256
    assert cv["decision"] == (
        "E9_CV_CHALLENGER_ELIGIBLE_FOR_ONE_DEVELOPMENT_RUN"
    )
    assert all(cv["gate_checks"].values())
    assert cv["cross_validation"]["learned_delta_at_4"] > 0.02
    assert cv["internal_validation_status"] == "NOT_RUN"
    assert cv["frozen_test_status"] == "UNTOUCHED"
    for relative, expected in cv["implementation_sha256"].items():
        assert _sha256(relative) == expected
    assert protocol.challenger_serving_status == "DISABLED"


def test_e9_development_failure_is_preserved_and_keeps_e8_champion() -> None:
    result = _load("finqa_learned_descriptor_development_public_v1.json")

    assert result["decision"] == "E9_DEVELOPMENT_GATE_FAILED_KEEP_E8_CHAMPION"
    assert result["development_evaluation_ordinal"] == 1
    assert result["development_evaluation_budget"] == 1
    assert result["serving_champion_after_gate"] == (
        "finqa_deterministic_descriptor_retriever_v5"
    )
    assert result["serving_route_status"] == "DISABLED"
    assert result["delta_vs_e8"]["descriptor_recall_at_4"] < 0
    assert result["delta_vs_e8"]["candidate_recall_at_8"] < 0
    assert result["internal_validation_status"] == "NOT_RUN"
    assert result["frozen_test_status"] == "UNTOUCHED"
    for relative, expected in result["implementation_sha256"].items():
        assert _sha256(relative) == expected


def test_e9_postmortem_reconciles_paired_role_transitions() -> None:
    result = _load("finqa_learned_descriptor_postmortem_public_v1.json")
    transitions = result["descriptor_recall_at_4_transitions"]

    assert sum(transitions.values()) == result["role_count"] == 123
    assert transitions["regressed"] == 11
    assert transitions["gained"] == 4
    assert result["decision"].startswith("KEEP_E8_CHAMPION")
    assert "do not rerun the consumed 60-case development cohort for E9" in (
        result["next_protocol_requirements"]
    )
