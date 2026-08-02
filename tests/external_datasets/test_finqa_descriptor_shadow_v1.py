from __future__ import annotations

import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.external_datasets.finqa_descriptor_retriever_v1 import (
    DescriptorRankV1,
    DeterministicDescriptorRetrieverResultV1,
    RoleDescriptorRankingV1,
)
from app.external_datasets.finqa_descriptor_selector_v1 import (
    DescriptorSelectionsV1,
    RoleDescriptorSelectionV1,
)
from app.external_datasets.finqa_descriptor_shadow_protocol_v1 import (
    load_descriptor_shadow_protocol_v1,
)
from app.external_datasets.finqa_descriptor_shadow_v1 import (
    FinQADescriptorShadowRuntimeV1,
    FinQAShadowConfigV1,
    FinQAShadowMetricsRegistryV1,
    FinQAShadowObservationV1,
    build_verified_finqa_shadow_runtime_v1,
    load_verified_e11_shadow_challenger_v1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeCandidateDescriptorV3,
    RetrievableSafeDescriptorCatalogV3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/external_datasets/evidence"
PROTOCOL = EVIDENCE / "finqa_descriptor_shadow_protocol_v1.json"
IDS = tuple(f"desc-{index:016x}" for index in range(1, 6))


def _skeleton() -> SemanticProgramSkeletonV2:
    return SemanticProgramSkeletonV2.model_validate(
        {
            "roles": [
                {
                    "role_id": "role-01",
                    "semantic_role": "comparison_left",
                    "period_role": "start",
                }
            ],
            "steps": [
                {
                    "step_id": "step-01",
                    "operation": "SUB",
                    "arguments": [
                        {"role_id": "role-01"},
                        {"constant_id": "const_100"},
                    ],
                }
            ],
            "output_step_id": "step-01",
        }
    )


def _catalog() -> RetrievableSafeDescriptorCatalogV3:
    descriptors = tuple(
        RetrievableSafeCandidateDescriptorV3(
            descriptor_id=descriptor_id,
            metric=f"metric name {index}",
            row_header=f"metric name {index}",
            column_header="2020",
            local_context_hint="annual financial result",
            topic_hint="company performance",
            periods=("2020",),
            source_kind="table_cell",
            candidate_count=1,
        )
        for index, descriptor_id in enumerate(IDS, start=1)
    )
    payload = {
        "catalog_version": "finqa_safe_descriptor_catalog_v3",
        "source_candidate_count": len(descriptors),
        "represented_candidate_count": len(descriptors),
        "quarantined_candidate_count": 0,
        "descriptor_count": len(descriptors),
        "descriptors": [item.model_dump(mode="json") for item in descriptors],
    }
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return RetrievableSafeDescriptorCatalogV3(
        **payload,
        catalog_sha256=hashlib.sha256(canonical).hexdigest(),
    )


def _result(
    descriptor_ids: tuple[str, ...],
    *,
    generation_calls: int = 0,
) -> DeterministicDescriptorRetrieverResultV1:
    ranks = tuple(
        DescriptorRankV1(
            descriptor_id=descriptor_id,
            score=float(len(descriptor_ids) - index),
            score_reasons=("test",),
        )
        for index, descriptor_id in enumerate(descriptor_ids)
    )
    return DeterministicDescriptorRetrieverResultV1(
        retriever_version="test-retriever",
        model="test-model",
        selections=DescriptorSelectionsV1(
            selections=(
                RoleDescriptorSelectionV1(
                    role_id="role-01",
                    descriptor_ids=descriptor_ids[:4],
                ),
            )
        ),
        rankings=(
            RoleDescriptorRankingV1(
                role_id="role-01",
                ranked_descriptors=ranks,
            ),
        ),
        generation_calls=generation_calls,
        latency_ms=0.1,
    )


class _FakeRetriever:
    def __init__(
        self,
        result: DeterministicDescriptorRetrieverResultV1,
        *,
        failures: int = 0,
    ) -> None:
        self.result = result
        self.failures = failures
        self.calls = 0

    def select(self, **_: object) -> DeterministicDescriptorRetrieverResultV1:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("synthetic shadow failure")
        return self.result


def _inputs() -> tuple[
    str,
    SemanticProgramSkeletonV2,
    RetrievableSafeDescriptorCatalogV3,
]:
    return "What changed in metric name 1?", _skeleton(), _catalog()


def test_default_off_never_calls_challenger() -> None:
    champion = _FakeRetriever(_result(IDS))
    challenger = _FakeRetriever(_result(tuple(reversed(IDS))))
    runtime = FinQADescriptorShadowRuntimeV1(
        champion=champion,
        challenger=challenger,
    )
    question, skeleton, catalog = _inputs()

    primary = runtime.select_primary(
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )
    observation = runtime.observe(
        primary=primary,
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )

    assert champion.calls == 1
    assert challenger.calls == 0
    assert primary.result.selections.selections[0].descriptor_ids == IDS[:4]
    assert observation.outcome == "DISABLED"


def test_shadow_divergence_cannot_replace_primary_and_emits_only_counts() -> None:
    champion = _FakeRetriever(_result(IDS))
    challenger = _FakeRetriever(_result(tuple(reversed(IDS))))
    runtime = FinQADescriptorShadowRuntimeV1(
        config=FinQAShadowConfigV1(mode="OBSERVE"),
        champion=champion,
        challenger=challenger,
        challenger_load_status="READY",
    )
    question, skeleton, catalog = _inputs()
    primary = runtime.select_primary(
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )

    observation = runtime.observe(
        primary=primary,
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )

    assert primary.result.selections.selections[0].descriptor_ids == IDS[:4]
    assert observation.outcome == "DIVERGED"
    assert observation.changed_role_count == 1
    assert observation.common_descriptor_count_at_4 == 3
    payload = observation.model_dump(mode="json")
    assert set(payload) == {
        "schema_version",
        "outcome",
        "role_count",
        "changed_role_count",
        "common_descriptor_count_at_4",
        "latency_bucket",
        "circuit_state",
    }
    serialized = observation.model_dump_json()
    assert question not in serialized
    assert all(descriptor_id not in serialized for descriptor_id in IDS)


def test_input_mismatch_fails_before_challenger_call() -> None:
    champion = _FakeRetriever(_result(IDS))
    challenger = _FakeRetriever(_result(IDS))
    runtime = FinQADescriptorShadowRuntimeV1(
        config=FinQAShadowConfigV1(mode="OBSERVE"),
        champion=champion,
        challenger=challenger,
        challenger_load_status="READY",
    )
    question, skeleton, catalog = _inputs()
    primary = runtime.select_primary(
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )

    observation = runtime.observe(
        primary=primary,
        question=f"{question} changed",
        skeleton=skeleton,
        catalog=catalog,
    )

    assert observation.outcome == "INPUT_MISMATCH"
    assert challenger.calls == 0
    assert primary.result.selections.selections[0].descriptor_ids == IDS[:4]


def test_errors_open_circuit_then_half_open_probe_recovers() -> None:
    champion = _FakeRetriever(_result(IDS))
    challenger = _FakeRetriever(_result(IDS), failures=3)
    runtime = FinQADescriptorShadowRuntimeV1(
        config=FinQAShadowConfigV1(
            mode="OBSERVE",
            consecutive_failure_threshold=3,
            cooldown_observation_count=5,
        ),
        champion=champion,
        challenger=challenger,
        challenger_load_status="READY",
    )
    question, skeleton, catalog = _inputs()
    primary = runtime.select_primary(
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )

    outcomes = [
        runtime.observe(
            primary=primary,
            question=question,
            skeleton=skeleton,
            catalog=catalog,
        ).outcome
        for _ in range(9)
    ]

    assert outcomes == [
        "CHALLENGER_ERROR",
        "CHALLENGER_ERROR",
        "CHALLENGER_ERROR",
        "CIRCUIT_OPEN",
        "CIRCUIT_OPEN",
        "CIRCUIT_OPEN",
        "CIRCUIT_OPEN",
        "CIRCUIT_OPEN",
        "MATCH",
    ]
    assert challenger.calls == 4
    assert runtime.metrics.snapshot().outcomes == {
        "CHALLENGER_ERROR": 3,
        "CIRCUIT_OPEN": 5,
        "MATCH": 1,
    }


def test_elapsed_budget_breach_is_isolated_as_timeout() -> None:
    ticks = iter((1.0, 1.2))
    champion = _FakeRetriever(_result(IDS))
    challenger = _FakeRetriever(_result(tuple(reversed(IDS))))
    runtime = FinQADescriptorShadowRuntimeV1(
        config=FinQAShadowConfigV1(
            mode="OBSERVE",
            observation_timeout_ms=100,
        ),
        champion=champion,
        challenger=challenger,
        challenger_load_status="READY",
        clock=lambda: next(ticks),
    )
    question, skeleton, catalog = _inputs()
    primary = runtime.select_primary(
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )

    observation = runtime.observe(
        primary=primary,
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )

    assert observation.outcome == "CHALLENGER_TIMEOUT"
    assert observation.latency_bucket == "GE_100_MS"
    assert primary.result.selections.selections[0].descriptor_ids == IDS[:4]


def test_verified_loader_is_ready_and_artifact_tampering_fails_closed(
    tmp_path: Path,
) -> None:
    protocol, _ = load_descriptor_shadow_protocol_v1(PROTOCOL)
    loaded = load_verified_e11_shadow_challenger_v1(
        protocol=protocol,
        evidence_dir=EVIDENCE,
    )
    assert loaded.status == "READY"
    assert loaded.challenger is not None

    copied = tmp_path / "evidence"
    copied.mkdir()
    for filename in (
        "finqa_retrievable_descriptor_protocol_v1.json",
        "finqa_topk_ranker_protocol_v1.json",
        "finqa_topk_nested_cv_public_v1.json",
        "finqa_topk_ranker_artifact_v1.json",
        "finqa_topk_internal_validation_public_v1.json",
        "finqa_topk_internal_postmortem_public_v1.json",
    ):
        shutil.copyfile(EVIDENCE / filename, copied / filename)
    artifact = copied / "finqa_topk_ranker_artifact_v1.json"
    artifact.write_bytes(artifact.read_bytes() + b"\n")

    rejected = load_verified_e11_shadow_challenger_v1(
        protocol=protocol,
        evidence_dir=copied,
    )

    assert rejected.status == "DISABLED_EVIDENCE_INVALID"
    assert rejected.challenger is None


def test_factory_keeps_invalid_protocol_default_off(tmp_path: Path) -> None:
    invalid = tmp_path / "protocol.json"
    invalid.write_text("{}", encoding="utf-8")

    runtime = build_verified_finqa_shadow_runtime_v1(
        protocol_path=invalid,
        evidence_dir=EVIDENCE,
        mode="OBSERVE",
    )

    assert runtime.config.mode == "OFF"
    assert runtime.challenger_load_status == "DISABLED_EVIDENCE_INVALID"


def test_aggregate_metrics_are_thread_safe_and_store_no_request_payload() -> None:
    registry = FinQAShadowMetricsRegistryV1()
    observation = FinQAShadowObservationV1(
        outcome="DIVERGED",
        role_count=1,
        changed_role_count=1,
        common_descriptor_count_at_4=3,
        latency_bucket="LT_1_MS",
        circuit_state="CLOSED",
    )
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(registry.record, (observation for _ in range(200))))

    snapshot = registry.snapshot()
    assert snapshot.observation_count == 200
    assert snapshot.role_count == 200
    assert snapshot.changed_role_count == 200
    assert snapshot.common_descriptor_count_at_4 == 600
    assert snapshot.outcomes == {"DIVERGED": 200}
    serialized = snapshot.model_dump_json()
    assert "question" not in serialized
    assert "desc-" not in serialized


def test_aggregate_snapshot_rejects_unbounded_metric_keys() -> None:
    registry = FinQAShadowMetricsRegistryV1()
    payload = registry.snapshot().model_dump(mode="json")
    payload["outcomes"] = {"raw question text": 1}

    with pytest.raises(ValueError, match="metric boundary"):
        type(registry.snapshot()).model_validate(payload)
