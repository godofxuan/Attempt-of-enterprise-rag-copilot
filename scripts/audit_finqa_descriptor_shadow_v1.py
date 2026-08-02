from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

from app.external_datasets.finqa_descriptor_retriever_v1 import (
    DeterministicDescriptorRetrieverResultV1,
)
from app.external_datasets.finqa_descriptor_retriever_v5 import (
    RETRIEVER_VERSION,
    DeterministicFinQADescriptorRetrieverV5,
)
from app.external_datasets.finqa_descriptor_shadow_protocol_v1 import (
    load_descriptor_shadow_protocol_v1,
)
from app.external_datasets.finqa_descriptor_shadow_v1 import (
    FinQADescriptorShadowRuntimeV1,
    FinQAShadowConfigV1,
    load_verified_e11_shadow_challenger_v1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeCandidateDescriptorV3,
    RetrievableSafeDescriptorCatalogV3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/external_datasets/evidence"
DEFAULT_PROTOCOL = EVIDENCE / "finqa_descriptor_shadow_protocol_v1.json"
DEFAULT_OUTPUT = EVIDENCE / "finqa_descriptor_shadow_mechanism_public_v1.json"
IMPLEMENTATION_PATHS = (
    "app/external_datasets/finqa_descriptor_shadow_protocol_v1.py",
    "app/external_datasets/finqa_descriptor_shadow_v1.py",
    "scripts/audit_finqa_descriptor_shadow_v1.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")


def _skeleton() -> SemanticProgramSkeletonV2:
    return SemanticProgramSkeletonV2.model_validate(
        {
            "roles": [
                {
                    "role_id": "role-01",
                    "semantic_role": "comparison_left",
                    "period_role": "none",
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
            descriptor_id=f"desc-{index:016x}",
            metric=f"operating metric category {index}",
            row_header=f"operating metric category {index}",
            column_header="current period",
            local_context_hint="annual operating result",
            topic_hint="company operating performance",
            periods=(),
            source_kind="table_cell",
            candidate_count=1,
        )
        for index in range(1, 6)
    )
    payload = {
        "catalog_version": "finqa_safe_descriptor_catalog_v3",
        "source_candidate_count": len(descriptors),
        "represented_candidate_count": len(descriptors),
        "quarantined_candidate_count": 0,
        "descriptor_count": len(descriptors),
        "descriptors": [item.model_dump(mode="json") for item in descriptors],
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    return RetrievableSafeDescriptorCatalogV3(
        **payload,
        catalog_sha256=digest,
    )


class _CallCounter:
    def __init__(
        self,
        *,
        result: DeterministicDescriptorRetrieverResultV1 | None = None,
        failure_count: int = 0,
    ) -> None:
        self.result = result
        self.failure_count = failure_count
        self.calls = 0

    def select(self, **_: object) -> DeterministicDescriptorRetrieverResultV1:
        self.calls += 1
        if self.calls <= self.failure_count or self.result is None:
            raise RuntimeError("injected shadow failure")
        return self.result


def _clock(values: tuple[float, ...]):
    iterator: Iterator[float] = iter(values)
    return lambda: next(iterator)


def build_public_evidence() -> dict[str, object]:
    protocol, protocol_sha256 = load_descriptor_shadow_protocol_v1(
        DEFAULT_PROTOCOL
    )
    loaded = load_verified_e11_shadow_challenger_v1(
        protocol=protocol,
        evidence_dir=EVIDENCE,
    )
    if loaded.challenger is None:
        raise RuntimeError("E12 verified challenger is unavailable")

    question = "Which operating metric changed?"
    skeleton = _skeleton()
    catalog = _catalog()
    champion = DeterministicFinQADescriptorRetrieverV5()
    primary_runtime = FinQADescriptorShadowRuntimeV1(
        config=FinQAShadowConfigV1.from_protocol(protocol, mode="OBSERVE"),
        champion=champion,
        challenger=loaded.challenger,
        challenger_load_status=loaded.status,
        clock=_clock((1.0, 1.002)),
    )
    primary = primary_runtime.select_primary(
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )
    primary_selection_before = primary.result.selections.model_dump_json()
    real_observation = primary_runtime.observe(
        primary=primary,
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )

    disabled_counter = _CallCounter(result=primary.result)
    disabled_runtime = FinQADescriptorShadowRuntimeV1(
        champion=champion,
        challenger=disabled_counter,
    )
    disabled_primary = disabled_runtime.select_primary(
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )
    disabled_observation = disabled_runtime.observe(
        primary=disabled_primary,
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )

    error_counter = _CallCounter(failure_count=1)
    error_runtime = FinQADescriptorShadowRuntimeV1(
        config=FinQAShadowConfigV1(mode="OBSERVE"),
        champion=champion,
        challenger=error_counter,
        challenger_load_status="READY",
        clock=_clock((2.0, 2.001)),
    )
    error_observation = error_runtime.observe(
        primary=primary,
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )

    timeout_runtime = FinQADescriptorShadowRuntimeV1(
        config=FinQAShadowConfigV1(
            mode="OBSERVE",
            observation_timeout_ms=100,
        ),
        champion=champion,
        challenger=loaded.challenger,
        challenger_load_status="READY",
        clock=_clock((3.0, 3.2)),
    )
    timeout_observation = timeout_runtime.observe(
        primary=primary,
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )

    recovery_counter = _CallCounter(result=primary.result, failure_count=3)
    recovery_runtime = FinQADescriptorShadowRuntimeV1(
        config=FinQAShadowConfigV1(
            mode="OBSERVE",
            consecutive_failure_threshold=3,
            cooldown_observation_count=5,
        ),
        champion=champion,
        challenger=recovery_counter,
        challenger_load_status="READY",
    )
    recovery_outcomes = tuple(
        recovery_runtime.observe(
            primary=primary,
            question=question,
            skeleton=skeleton,
            catalog=catalog,
        ).outcome
        for _ in range(9)
    )
    expected_recovery = (
        "CHALLENGER_ERROR",
        "CHALLENGER_ERROR",
        "CHALLENGER_ERROR",
        "CIRCUIT_OPEN",
        "CIRCUIT_OPEN",
        "CIRCUIT_OPEN",
        "CIRCUIT_OPEN",
        "CIRCUIT_OPEN",
        "MATCH",
    )

    observation_payload = real_observation.model_dump(mode="json")
    serialized_observation = real_observation.model_dump_json()
    descriptor_ids = tuple(item.descriptor_id for item in catalog.descriptors)
    gates = {
        "artifact_and_evidence_hash_verification": loaded.status == "READY",
        "challenger_zero_model_calls": (
            real_observation.outcome in {"MATCH", "DIVERGED"}
            and protocol.runtime.challenger_model_calls_permitted is False
        ),
        "circuit_breaker_recovery": recovery_outcomes == expected_recovery,
        "default_off": disabled_runtime.config.mode == "OFF",
        "default_off_zero_challenger_calls": disabled_counter.calls == 0,
        "error_isolation": error_observation.outcome == "CHALLENGER_ERROR",
        "frozen_test_untouched": protocol.frozen_test_status == "UNTOUCHED",
        "primary_result_immutability": (
            primary.result.retriever_version == RETRIEVER_VERSION
            and primary.result.selections.model_dump_json()
            == primary_selection_before
        ),
        "privacy_bounded_telemetry": (
            tuple(observation_payload)
            == protocol.telemetry.allowed_observation_fields
            and question not in serialized_observation
            and all(item not in serialized_observation for item in descriptor_ids)
        ),
        "serving_route_disabled": protocol.serving_route_status == "DISABLED",
        "timeout_isolation": timeout_observation.outcome
        == "CHALLENGER_TIMEOUT",
    }
    if not all(gates.values()):
        raise RuntimeError("E12 mechanism gate failed")

    return {
        "schema_version": "finqa_descriptor_shadow_mechanism_public_v1",
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "claim": "MECHANISM_ONLY_NOT_PRODUCTION_TRAFFIC_OR_ANSWER_ACCURACY",
        "decision": "E12_MECHANISM_GATE_PASSED_SHADOW_REMAINS_DEFAULT_OFF",
        "challenger_load_status": loaded.status,
        "real_mechanism_probe": {
            "case_count": 1,
            "champion_version": primary.result.retriever_version,
            "observation_outcome": real_observation.outcome,
            "aggregate_metrics": primary_runtime.metrics.snapshot().model_dump(
                mode="json"
            ),
        },
        "failure_injection": {
            "default_off_outcome": disabled_observation.outcome,
            "error_outcome": error_observation.outcome,
            "timeout_outcome": timeout_observation.outcome,
            "circuit_observation_count": len(recovery_outcomes),
            "circuit_challenger_call_count": recovery_counter.calls,
            "circuit_sequence_matches_protocol": recovery_outcomes
            == expected_recovery,
        },
        "gate_checks": gates,
        "implementation_sha256": {
            relative: _sha256(ROOT / relative)
            for relative in IMPLEMENTATION_PATHS
        },
        "serving_route_status": "DISABLED",
        "frozen_test_status": "UNTOUCHED",
        "model_call_count": 0,
        "non_claims": list(protocol.non_claims),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    content = _canonical_bytes(build_public_evidence())
    output = args.output.resolve()
    if output.exists() and output.read_bytes() != content:
        raise RuntimeError("refusing to overwrite different E12 public evidence")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    print(json.dumps(json.loads(content), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
