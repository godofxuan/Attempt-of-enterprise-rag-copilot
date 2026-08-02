from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from multiprocessing.connection import Connection
from pathlib import Path

from app.external_datasets.finqa import DEFAULT_SOURCE_ROOT
from app.external_datasets.finqa_descriptor_shadow_v1 import (
    FinQADescriptorShadowRuntimeV1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeCandidateDescriptorV3,
    RetrievableSafeDescriptorCatalogV3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)
from app.external_datasets.finqa_shadow_replay_v1 import (
    evaluate_shadow_replay_gates_v1,
    load_finqa_shadow_replay_train_v1,
    run_finqa_shadow_operational_replay_v1,
)
from app.external_datasets.finqa_shadow_worker_protocol_v1 import (
    load_shadow_worker_replay_protocol_v1,
)
from app.external_datasets.finqa_shadow_worker_v1 import (
    FinQAIsolatedShadowWorkerV1,
    FinQAShadowWorkerConfigV1,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/external_datasets/evidence"
DEFAULT_PROTOCOL = EVIDENCE / "finqa_shadow_worker_replay_protocol_v1.json"
DEFAULT_OUTPUT = EVIDENCE / "finqa_shadow_worker_replay_public_v1.json"
IMPLEMENTATION_PATHS = (
    "app/external_datasets/finqa_shadow_worker_protocol_v1.py",
    "app/external_datasets/finqa_shadow_worker_v1.py",
    "app/external_datasets/finqa_shadow_replay_v1.py",
    "scripts/audit_finqa_shadow_worker_replay_v1.py",
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


def _fault_skeleton() -> SemanticProgramSkeletonV2:
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


def _fault_catalog() -> RetrievableSafeDescriptorCatalogV3:
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


def _ready_then_hang(
    connection: Connection,
    _evidence_dir: str,
    _max_request_bytes: int,
    _max_response_bytes: int,
) -> None:
    connection.send_bytes(b'{"status":"READY"}')
    if connection.recv_bytes() == b'{"kind":"STOP"}':
        return
    time.sleep(60)


def _ready_then_crash(
    connection: Connection,
    _evidence_dir: str,
    _max_request_bytes: int,
    _max_response_bytes: int,
) -> None:
    connection.send_bytes(b'{"status":"READY"}')
    if connection.recv_bytes() == b'{"kind":"STOP"}':
        return
    os._exit(17)


def _ready_then_malformed(
    connection: Connection,
    _evidence_dir: str,
    _max_request_bytes: int,
    _max_response_bytes: int,
) -> None:
    connection.send_bytes(b'{"status":"READY"}')
    if connection.recv_bytes() == b'{"kind":"STOP"}':
        return
    connection.send_bytes(b"{}")
    time.sleep(60)


def _fault_injection() -> dict[str, bool]:
    question = "Which operating metric changed?"
    skeleton = _fault_skeleton()
    catalog = _fault_catalog()
    primary = FinQADescriptorShadowRuntimeV1().select_primary(
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )
    primary_before = (
        primary.input_binding_sha256,
        primary.result.retriever_version,
        primary.result.generation_calls,
        primary.result.selections.model_dump_json(),
    )

    timeout_worker = FinQAIsolatedShadowWorkerV1(
        evidence_dir=EVIDENCE,
        config=FinQAShadowWorkerConfigV1(
            startup_timeout_seconds=5,
            observation_timeout_seconds=0.05,
            termination_grace_seconds=0.5,
        ),
        worker_entry=_ready_then_hang,
    )
    timeout_worker.start()
    timeout_pid = timeout_worker.diagnostics().worker_pid
    timeout = timeout_worker.observe(
        primary=primary,
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )
    timeout_diagnostics = timeout_worker.diagnostics()
    timeout_worker.close()

    crash_worker = FinQAIsolatedShadowWorkerV1(
        evidence_dir=EVIDENCE,
        config=FinQAShadowWorkerConfigV1(
            startup_timeout_seconds=5,
            observation_timeout_seconds=1,
            termination_grace_seconds=0.5,
        ),
        worker_entry=_ready_then_crash,
    )
    crash_worker.start()
    crash_pid = crash_worker.diagnostics().worker_pid
    crash = crash_worker.observe(
        primary=primary,
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )
    crash_diagnostics = crash_worker.diagnostics()
    crash_worker.close()

    malformed_worker = FinQAIsolatedShadowWorkerV1(
        evidence_dir=EVIDENCE,
        config=FinQAShadowWorkerConfigV1(
            startup_timeout_seconds=5,
            observation_timeout_seconds=1,
            termination_grace_seconds=0.5,
        ),
        worker_entry=_ready_then_malformed,
    )
    malformed_worker.start()
    malformed_pid = malformed_worker.diagnostics().worker_pid
    malformed = malformed_worker.observe(
        primary=primary,
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )
    malformed_diagnostics = malformed_worker.diagnostics()
    malformed_worker.close()

    oversized_worker = FinQAIsolatedShadowWorkerV1(
        evidence_dir=EVIDENCE,
        config=FinQAShadowWorkerConfigV1(max_request_bytes=64),
    )
    oversized = oversized_worker.observe(
        primary=primary,
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )
    oversized_diagnostics = oversized_worker.diagnostics()
    oversized_worker.close()

    return {
        "crash_detection_and_restart": (
            crash.outcome == "WORKER_CRASH"
            and crash.worker_restarted
            and crash_diagnostics.last_terminated_pid == crash_pid
            and crash_diagnostics.worker_pid not in {None, crash_pid}
        ),
        "hard_timeout_terminates_worker": (
            timeout.outcome == "WORKER_TIMEOUT"
            and timeout.worker_restarted
            and timeout_diagnostics.last_terminated_pid == timeout_pid
            and timeout_diagnostics.worker_pid not in {None, timeout_pid}
        ),
        "malformed_response_rejected": (
            malformed.outcome == "WORKER_ERROR"
            and malformed.worker_restarted
            and malformed_diagnostics.last_terminated_pid == malformed_pid
            and malformed_diagnostics.worker_pid not in {None, malformed_pid}
        ),
        "oversized_request_rejected_before_ipc": (
            oversized.outcome == "PAYLOAD_REJECTED"
            and oversized_diagnostics.worker_pid is None
        ),
        "primary_result_immutability": (
            primary.input_binding_sha256,
            primary.result.retriever_version,
            primary.result.generation_calls,
            primary.result.selections.model_dump_json(),
        )
        == primary_before,
    }


def build_public_evidence() -> dict[str, object]:
    protocol, protocol_sha256 = load_shadow_worker_replay_protocol_v1(
        DEFAULT_PROTOCOL
    )
    e12_protocol_matches = protocol.source_e12_protocol_sha256 == _sha256(
        EVIDENCE / "finqa_descriptor_shadow_protocol_v1.json"
    )
    e12_mechanism_matches = protocol.source_e12_mechanism_sha256 == _sha256(
        EVIDENCE / "finqa_descriptor_shadow_mechanism_public_v1.json"
    )
    cases = load_finqa_shadow_replay_train_v1(
        DEFAULT_SOURCE_ROOT / "dataset/train.json",
        expected_sha256=protocol.dataset.split_sha256,
    )
    with FinQAIsolatedShadowWorkerV1(
        evidence_dir=EVIDENCE,
        config=FinQAShadowWorkerConfigV1.from_protocol(protocol),
    ) as worker:
        summary = run_finqa_shadow_operational_replay_v1(
            cases,
            protocol=protocol,
            worker=worker,
        )
    replay_gates = evaluate_shadow_replay_gates_v1(summary, protocol=protocol)
    fault_gates = _fault_injection()
    gate_checks = {
        "source_e12_evidence_hashes": (
            e12_protocol_matches and e12_mechanism_matches
        ),
        **replay_gates,
        **fault_gates,
    }
    if not all(gate_checks.values()):
        failed = sorted(name for name, passed in gate_checks.items() if not passed)
        raise RuntimeError(f"E13 operational replay gates failed: {failed}")

    summary_payload = summary.model_dump(mode="json")
    summary_payload.pop("schema_version")
    return {
        "schema_version": "finqa_shadow_worker_replay_public_v1",
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "claim": protocol.claim_label,
        "decision": "E13_OPERATIONAL_REPLAY_PASSED_SHADOW_REMAINS_DEFAULT_OFF",
        **summary_payload,
        "fault_injection": fault_gates,
        "gate_checks": gate_checks,
        "implementation_sha256": {
            relative: _sha256(ROOT / relative)
            for relative in IMPLEMENTATION_PATHS
        },
        "serving_champion": protocol.serving_champion,
        "challenger_status": protocol.challenger_status,
        "internal_cohort_status": protocol.internal_cohort_status,
        "frozen_test_status": protocol.frozen_test_status,
        "non_claims": list(protocol.non_claims),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    content = _canonical_bytes(build_public_evidence())
    output = args.output.resolve()
    if output.exists() and output.read_bytes() != content:
        raise RuntimeError("refusing to overwrite different E13 public evidence")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    print(json.dumps(json.loads(content), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
