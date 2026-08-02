from __future__ import annotations

import hashlib
import json
import os
import time
from multiprocessing.connection import Connection
from pathlib import Path

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
from app.external_datasets.finqa_shadow_worker_v1 import (
    FinQAIsolatedShadowWorkerV1,
    FinQAShadowWorkerConfigV1,
)


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/external_datasets/evidence"


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


def _primary_inputs():
    question = "Which operating metric changed?"
    skeleton = _skeleton()
    catalog = _catalog()
    primary = FinQADescriptorShadowRuntimeV1().select_primary(
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )
    return primary, question, skeleton, catalog


def test_real_spawn_worker_runs_verified_e11_and_closes() -> None:
    primary, question, skeleton, catalog = _primary_inputs()
    worker = FinQAIsolatedShadowWorkerV1(evidence_dir=EVIDENCE)
    assert worker.start() is True
    original_pid = worker.diagnostics().worker_pid

    observation = worker.observe(
        primary=primary,
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )

    assert original_pid is not None
    assert observation.outcome in {"MATCH", "DIVERGED"}
    assert observation.worker_peak_rss_bytes is not None
    assert observation.worker_restarted is False
    assert worker.diagnostics().worker_pid == original_pid
    worker.close()
    assert worker.diagnostics().worker_pid is None
    assert worker.diagnostics().last_terminated_exitcode == 0


def test_input_mismatch_and_oversized_payload_fail_before_worker_start() -> None:
    primary, question, skeleton, catalog = _primary_inputs()
    mismatch_worker = FinQAIsolatedShadowWorkerV1(evidence_dir=EVIDENCE)
    mismatch = mismatch_worker.observe(
        primary=primary,
        question=f"{question} changed",
        skeleton=skeleton,
        catalog=catalog,
    )
    assert mismatch.outcome == "INPUT_MISMATCH"
    assert mismatch_worker.diagnostics().worker_pid is None

    small_worker = FinQAIsolatedShadowWorkerV1(
        evidence_dir=EVIDENCE,
        config=FinQAShadowWorkerConfigV1(max_request_bytes=64),
    )
    oversized = small_worker.observe(
        primary=primary,
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )
    assert oversized.outcome == "PAYLOAD_REJECTED"
    assert small_worker.diagnostics().worker_pid is None


def test_hard_timeout_terminates_old_pid_and_starts_replacement() -> None:
    primary, question, skeleton, catalog = _primary_inputs()
    worker = FinQAIsolatedShadowWorkerV1(
        evidence_dir=EVIDENCE,
        config=FinQAShadowWorkerConfigV1(
            startup_timeout_seconds=5,
            observation_timeout_seconds=0.05,
            termination_grace_seconds=0.5,
        ),
        worker_entry=_ready_then_hang,
    )
    assert worker.start() is True
    original_pid = worker.diagnostics().worker_pid

    observation = worker.observe(
        primary=primary,
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )
    diagnostics = worker.diagnostics()

    assert observation.outcome == "WORKER_TIMEOUT"
    assert observation.worker_restarted is True
    assert diagnostics.last_terminated_pid == original_pid
    assert diagnostics.last_terminated_exitcode is not None
    assert diagnostics.worker_pid not in {None, original_pid}
    assert diagnostics.restart_count == 1
    worker.close()


def test_crash_and_malformed_response_are_detected_then_restarted() -> None:
    primary, question, skeleton, catalog = _primary_inputs()
    for entry, expected in (
        (_ready_then_crash, "WORKER_CRASH"),
        (_ready_then_malformed, "WORKER_ERROR"),
    ):
        worker = FinQAIsolatedShadowWorkerV1(
            evidence_dir=EVIDENCE,
            config=FinQAShadowWorkerConfigV1(
                startup_timeout_seconds=5,
                observation_timeout_seconds=1,
                termination_grace_seconds=0.5,
            ),
            worker_entry=entry,
        )
        assert worker.start() is True
        original_pid = worker.diagnostics().worker_pid
        observation = worker.observe(
            primary=primary,
            question=question,
            skeleton=skeleton,
            catalog=catalog,
        )
        diagnostics = worker.diagnostics()

        assert observation.outcome == expected
        assert observation.worker_restarted is True
        assert diagnostics.last_terminated_pid == original_pid
        assert diagnostics.worker_pid not in {None, original_pid}
        worker.close()
