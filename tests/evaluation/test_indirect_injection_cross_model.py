from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.indirect_injection_cross_model import (
    CrossModelPlanError,
    load_cross_model_plan,
)


ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "data" / "v2" / "evaluation" / "r2_s4_cross_model_matrix_v1.json"


def _canonical_json(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _plan_payload() -> dict[str, object]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def _write_plan(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "plan.json"
    path.write_bytes(_canonical_json(payload))
    return path


def test_loads_checked_in_frozen_cross_model_plan() -> None:
    plan, digest = load_cross_model_plan(PLAN_PATH)

    assert plan.schema_version == "indirect_injection_cross_model_plan_v1"
    assert plan.experiment_id == "r2-s4-cross-model-dev-v1"
    assert plan.split == "dev"
    assert plan.expected_case_count == 36
    assert plan.expected_arm_event_count_per_model == 72
    assert plan.model_for_role("baseline").requested_name == "qwen2.5:3b"
    assert plan.model_for_role("replication").requested_name == "qwen3:8b"
    assert len(digest) == 64


def test_plan_models_are_frozen() -> None:
    plan, _ = load_cross_model_plan(PLAN_PATH)

    with pytest.raises(ValidationError):
        plan.split = "test"  # type: ignore[misc]


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_field",
        "test_split",
        "duplicate_role",
        "duplicate_requested_name",
        "duplicate_digest",
        "duplicate_run_id",
        "missing_metric",
        "unsafe_run_id",
        "wrong_embedding_digest",
        "reversed_chat_models",
        "too_many_chat_models",
        "too_few_chat_models",
    ],
)
def test_loader_rejects_invalid_frozen_plan(
    tmp_path: Path,
    mutation: str,
) -> None:
    payload = _plan_payload()
    chat_models = payload["chat_models"]
    assert isinstance(chat_models, list)

    if mutation == "unknown_field":
        payload["unexpected"] = True
    elif mutation == "test_split":
        payload["split"] = "test"
    elif mutation == "duplicate_role":
        chat_models[1]["role"] = chat_models[0]["role"]
    elif mutation == "duplicate_requested_name":
        chat_models[1]["requested_name"] = chat_models[0]["requested_name"]
    elif mutation == "duplicate_digest":
        chat_models[1]["digest"] = chat_models[0]["digest"]
    elif mutation == "duplicate_run_id":
        chat_models[1]["run_id"] = chat_models[0]["run_id"]
    elif mutation == "missing_metric":
        metrics = payload["comparison_metric_ids"]
        assert isinstance(metrics, list)
        metrics.pop()
    elif mutation == "unsafe_run_id":
        chat_models[0]["run_id"] = "../unsafe"
    elif mutation == "wrong_embedding_digest":
        embedding = payload["embedding"]
        assert isinstance(embedding, dict)
        embedding["digest"] = "f" * 64
    elif mutation == "reversed_chat_models":
        chat_models.reverse()
    elif mutation == "too_many_chat_models":
        chat_models.append(chat_models[0].copy())
    else:
        del chat_models[1]

    with pytest.raises(CrossModelPlanError):
        load_cross_model_plan(_write_plan(tmp_path, payload))


def test_loader_rejects_noncanonical_plan_bytes(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    path.write_bytes(b"\n" + PLAN_PATH.read_bytes())

    with pytest.raises(CrossModelPlanError, match="canonical"):
        load_cross_model_plan(path)
