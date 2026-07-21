from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


CrossModelRole = Literal["baseline", "replication"]

PLAN_SCHEMA_VERSION = "indirect_injection_cross_model_plan_v1"
EXPERIMENT_ID = "r2-s4-cross-model-dev-v1"
MATRIX_RUN_ID = "r2-s4-cross-model-dev-20260722-01"
EMBEDDING_DIGEST = "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab"
COMPARISON_METRIC_IDS = (
    "off_user_boundary_attack_success",
    "on_user_boundary_attack_success",
    "off_raw_follow_signal",
    "on_raw_follow_signal",
    "off_model_context_exposure",
    "on_model_context_exposure",
    "on_conditional_quarantine",
    "on_all_labeled_quarantine",
    "on_benign_quarantine",
    "clean_utility",
    "mixed_utility",
    "poison_only_utility",
    "model_error_count",
    "blocked_egress",
    "model_call_count",
    "model_latency_p50_ms",
    "model_latency_p95_ms",
)


class CrossModelPlanError(ValueError):
    """Raised when the frozen cross-model plan is malformed or changed."""


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=False,
    )


class CrossModelEmbeddingPlan(_StrictFrozenModel):
    requested_name: Literal["bge-m3"]
    resolved_name: Literal["bge-m3:latest"]
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_identity(self) -> CrossModelEmbeddingPlan:
        if self.digest != EMBEDDING_DIGEST:
            raise ValueError("embedding digest does not match the frozen plan")
        return self


class CrossModelModelPlan(_StrictFrozenModel):
    role: CrossModelRole
    requested_name: str = Field(min_length=1, max_length=200)
    resolved_name: str = Field(min_length=1, max_length=200)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    family: str = Field(min_length=1, max_length=100)
    parameter_size: str = Field(min_length=1, max_length=100)
    run_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class CrossModelPlanV1(_StrictFrozenModel):
    schema_version: Literal["indirect_injection_cross_model_plan_v1"]
    experiment_id: Literal["r2-s4-cross-model-dev-v1"]
    split: Literal["dev"]
    matrix_run_id: Literal["r2-s4-cross-model-dev-20260722-01"]
    only_changed_variable: Literal["chat_model_identity"]
    expected_case_count: Literal[36]
    expected_arm_event_count_per_model: Literal[72]
    expected_arm_order_protocol: Literal["stable_case_hash_rank_counterbalanced_v1"]
    embedding: CrossModelEmbeddingPlan
    chat_models: tuple[CrossModelModelPlan, ...] = Field(
        min_length=2,
        max_length=2,
    )
    comparison_metric_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_frozen_matrix(self) -> CrossModelPlanV1:
        roles = tuple(model.role for model in self.chat_models)
        requested_names = tuple(model.requested_name for model in self.chat_models)
        digests = tuple(model.digest for model in self.chat_models)
        run_ids = tuple(model.run_id for model in self.chat_models)
        if len(set(roles)) != len(roles):
            raise ValueError("chat model roles must be unique")
        if len(set(requested_names)) != len(requested_names):
            raise ValueError("chat model requested names must be unique")
        if len(set(digests)) != len(digests):
            raise ValueError("chat model digests must be unique")
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("chat model run IDs must be unique")
        if roles != ("baseline", "replication"):
            raise ValueError("plan requires baseline before replication")
        if self.comparison_metric_ids != COMPARISON_METRIC_IDS:
            raise ValueError("comparison metric IDs do not match the frozen plan")

        expected_models = {
            "baseline": {
                "requested_name": "qwen2.5:3b",
                "resolved_name": "qwen2.5:3b",
                "digest": "357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b",
                "family": "qwen2",
                "parameter_size": "3.1B",
                "run_id": "r2-s4-qwen25-dev-20260722-01",
            },
            "replication": {
                "requested_name": "qwen3:8b",
                "resolved_name": "qwen3:8b",
                "digest": "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41",
                "family": "qwen3",
                "parameter_size": "8.2B",
                "run_id": "r2-s4-qwen3-dev-20260722-01",
            },
        }
        observed_models = {
            model.role: model.model_dump(exclude={"role"}, mode="python")
            for model in self.chat_models
        }
        if observed_models != expected_models:
            raise ValueError("chat model identities do not match the frozen plan")
        return self

    def model_for_role(self, role: CrossModelRole) -> CrossModelModelPlan:
        for model in self.chat_models:
            if model.role == role:
                return model
        raise CrossModelPlanError(f"unknown model role: {role}")


def load_cross_model_plan(path: Path) -> tuple[CrossModelPlanV1, str]:
    """Load the immutable plan only when its bytes are canonical and valid."""

    try:
        raw = path.read_bytes()
        payload = _load_json_object(raw)
        if raw != _canonical_json_bytes(payload):
            raise CrossModelPlanError("cross-model plan is not canonical JSON")
        plan = CrossModelPlanV1.model_validate_json(raw)
    except CrossModelPlanError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise CrossModelPlanError(f"invalid cross-model plan: {exc}") from exc

    return plan, hashlib.sha256(raw).hexdigest()


def _load_json_object(raw: bytes) -> dict[str, Any]:
    payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(payload, dict):
        raise CrossModelPlanError("cross-model plan must be a JSON object")
    return payload


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CrossModelPlanError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


__all__ = [
    "COMPARISON_METRIC_IDS",
    "CrossModelModelPlan",
    "CrossModelPlanError",
    "CrossModelPlanV1",
    "load_cross_model_plan",
]
