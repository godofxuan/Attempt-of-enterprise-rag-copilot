from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.external_datasets.finqa import DEFAULT_SOURCE_ROOT
from app.external_datasets.finqa_shadow_capacity_protocol_v1 import (
    load_shadow_capacity_protocol_v1,
)
from app.external_datasets.finqa_shadow_capacity_v1 import (
    aggregate_finqa_shadow_capacity_trials_v1,
    capacity_trial_schedule_v1,
    evaluate_finqa_shadow_capacity_gates_v1,
    prepare_finqa_shadow_capacity_workload_v1,
    run_finqa_shadow_capacity_trial_v1,
)
from app.external_datasets.finqa_shadow_replay_v1 import (
    load_finqa_shadow_replay_train_v1,
)
from app.external_datasets.finqa_shadow_worker_protocol_v1 import (
    load_shadow_worker_replay_protocol_v1,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/external_datasets/evidence"
DEFAULT_PROTOCOL = EVIDENCE / "finqa_shadow_capacity_protocol_v1.json"
DEFAULT_OUTPUT = EVIDENCE / "finqa_shadow_capacity_public_v1.json"
E13_PROTOCOL = EVIDENCE / "finqa_shadow_worker_replay_protocol_v1.json"
E14_PROTOCOL = EVIDENCE / "finqa_shadow_pool_replay_protocol_v1.json"
E14_PUBLIC = EVIDENCE / "finqa_shadow_pool_replay_public_v1.json"
IMPLEMENTATION_PATHS = (
    "app/external_datasets/finqa_shadow_capacity_protocol_v1.py",
    "app/external_datasets/finqa_shadow_capacity_v1.py",
    "scripts/audit_finqa_shadow_capacity_v1.py",
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


def build_public_evidence() -> dict[str, object]:
    e15_protocol, e15_protocol_sha256 = load_shadow_capacity_protocol_v1(
        DEFAULT_PROTOCOL
    )
    e13_protocol, _ = load_shadow_worker_replay_protocol_v1(E13_PROTOCOL)
    source_evidence_matches = (
        e15_protocol.source_e14_protocol_sha256 == _sha256(E14_PROTOCOL)
        and e15_protocol.source_e14_public_evidence_sha256 == _sha256(E14_PUBLIC)
    )
    cases = load_finqa_shadow_replay_train_v1(
        DEFAULT_SOURCE_ROOT / "dataset/train.json",
        expected_sha256=e13_protocol.dataset.split_sha256,
    )
    workload = prepare_finqa_shadow_capacity_workload_v1(
        cases,
        e13_protocol=e13_protocol,
    )
    print(
        "E15 prepared "
        f"{len(workload.requests)}/{workload.preparation.selected_case_count} "
        "aggregate-only requests",
        flush=True,
    )
    schedule = capacity_trial_schedule_v1(e15_protocol)
    trials = []
    for index, item in enumerate(schedule, start=1):
        trial = run_finqa_shadow_capacity_trial_v1(
            workload,
            schedule_item=item,
            protocol=e15_protocol,
            e13_protocol=e13_protocol,
            evidence_dir=EVIDENCE,
        )
        trials.append(trial)
        print(
            f"E15 [{index:02d}/{len(schedule)}] {trial.trial_id} "
            f"throughput={trial.throughput_requests_per_second:.3f} req/s "
            f"p95={trial.end_to_end_latency_ms.p95:.3f} ms "
            f"failures={trial.attempted_count - trial.completed_count}",
            flush=True,
        )
    summary = aggregate_finqa_shadow_capacity_trials_v1(
        workload.preparation,
        trials,
        protocol=e15_protocol,
        all_primary_results_e8=workload.all_primary_results_e8,
    )
    gate_checks = {
        "source_e14_evidence_hashes": source_evidence_matches,
        **evaluate_finqa_shadow_capacity_gates_v1(
            summary,
            protocol=e15_protocol,
        ),
    }
    passed = all(gate_checks.values())
    summary_payload = summary.model_dump(mode="json")
    summary_payload.pop("schema_version")
    return {
        "schema_version": "finqa_shadow_capacity_public_v1",
        "protocol_id": e15_protocol.protocol_id,
        "protocol_sha256": e15_protocol_sha256,
        "claim": e15_protocol.claim_label,
        "decision": (
            "E15_LOCAL_CAPACITY_ENVELOPE_SUPPORTED_SHADOW_REMAINS_DEFAULT_OFF"
            if passed
            else "E15_LOCAL_CAPACITY_ENVELOPE_NOT_SUPPORTED_SHADOW_REMAINS_DEFAULT_OFF"
        ),
        **summary_payload,
        "gate_checks": gate_checks,
        "implementation_sha256": {
            relative: _sha256(ROOT / relative)
            for relative in IMPLEMENTATION_PATHS
        },
        "serving_champion": e15_protocol.serving_champion,
        "challenger_status": e15_protocol.challenger_status,
        "internal_cohort_status": e15_protocol.internal_cohort_status,
        "frozen_test_status": e15_protocol.frozen_test_status,
        "non_claims": list(e15_protocol.non_claims),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    content = _canonical_bytes(build_public_evidence())
    output = args.output.resolve()
    if output.exists() and output.read_bytes() != content:
        raise RuntimeError("refusing to overwrite different E15 public evidence")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    payload = json.loads(content)
    failed = sorted(
        name for name, passed in payload["gate_checks"].items() if not passed
    )
    print(
        json.dumps(
            {
                "decision": payload["decision"],
                "failed_gates": failed,
                "local_recommendation": payload["local_recommendation"],
                "output": str(output),
                "sha256": hashlib.sha256(content).hexdigest(),
            },
            indent=2,
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
