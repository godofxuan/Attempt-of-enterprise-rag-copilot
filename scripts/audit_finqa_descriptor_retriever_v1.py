try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
from pathlib import Path

from app.external_datasets.finqa import (
    DEFAULT_PRIVATE_ROOT,
    DEFAULT_SOURCE_ROOT,
    FINQA_DEV_SHA256,
    load_finqa_split,
)
from app.external_datasets.finqa_descriptor_catalog_protocol_v1 import (
    load_descriptor_catalog_protocol_v1,
)
from app.external_datasets.finqa_descriptor_retriever_protocol_v1 import (
    load_descriptor_retriever_protocol_v1,
)
from app.external_datasets.finqa_descriptor_retriever_v1 import (
    DeterministicFinQADescriptorRetrieverV1,
)
from app.external_datasets.finqa_semantic_calibration_run import (
    FinQASemanticPlanningCase,
)
from app.external_datasets.finqa_typed_calibration import case_ids_sha256
from app.security.retrieved_content import RetrievedContentGuard
from scripts import audit_finqa_descriptor_catalog_upper_bound_v1 as catalog_audit
from scripts import audit_finqa_descriptor_selector_live_v1 as live_audit
from scripts import audit_finqa_role_query_planner_llm_v1 as live_io
from scripts import audit_finqa_role_query_planner_v1 as evidence_io


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_descriptor_retriever_protocol_v1.json"
)
DEFAULT_CATALOG_PROTOCOL = catalog_audit.DEFAULT_PROTOCOL
DEFAULT_CATALOG_UPPER_BOUND = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_descriptor_catalog_upper_bound_public_v2.json"
)
DEFAULT_FAILED_LIVE_SELECTOR = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_descriptor_selector_live_public_v1.json"
)
DEFAULT_E5_RUN = evidence_io.DEFAULT_E5_RUN
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_descriptor_retriever_public_v1.json"
)
DEFAULT_PRIVATE_OUTPUT = (
    DEFAULT_PRIVATE_ROOT
    / "descriptor_retriever_audits"
    / "finqa-deterministic-descriptor-retriever-v1"
)
COMPARISON_EVIDENCE = {
    "question_only_v2": (
        REPOSITORY_ROOT
        / "docs/external_datasets/evidence/finqa_role_query_planner_v2_calibration_public_v1.json"
    ),
    "free_query_llm_v1": (
        REPOSITORY_ROOT
        / "docs/external_datasets/evidence/finqa_role_query_planner_llm_v1_calibration_public_v1.json"
    ),
    "descriptor_selector_qwen3_8b_v1": DEFAULT_FAILED_LIVE_SELECTOR,
}
IMPLEMENTATION_FILES = (
    "app/external_datasets/finqa_safe_descriptor_catalog_v1.py",
    "app/external_datasets/finqa_safe_descriptor_catalog_v2.py",
    "app/external_datasets/finqa_descriptor_retriever_v1.py",
    "app/external_datasets/finqa_descriptor_retriever_protocol_v1.py",
    "scripts/audit_finqa_descriptor_retriever_v1.py",
)


def _summarize(rows, protocol):
    typed = [row for row in rows if row["status"] != "FALLBACK_ROUTED"]
    evaluated = [row for row in typed if row["status"] == "EVALUATED"]
    retentions = [item for row in evaluated for item in row["retention"]]
    role_count = sum(row.get("evidence_role_count", 0) for row in typed)
    recall_4 = sum(item["retained_at_4"] for item in retentions) / role_count
    recall_8 = sum(item["retained_at_8"] for item in retentions) / role_count
    complete = sum(row.get("complete_at_8", False) for row in typed) / len(typed)
    baseline_edges = sum(
        row.get("baseline_role_candidate_edges", 0) for row in typed
    )
    selected_edges = sum(
        row.get("selected_role_candidate_edges", 0) for row in typed
    )
    edge_reduction = 1 - selected_edges / baseline_edges
    latencies = [row["latency_ms"] for row in evaluated]
    mean_latency = sum(latencies) / len(latencies) if latencies else 0.0
    p95_latency = live_io._p95(latencies)
    requests = sum(row["model_request_count"] for row in typed)
    gates = protocol.gates
    checks = {
        "role_recall_at_4": recall_4 >= gates.min_role_recall_at_4,
        "role_recall_at_8": recall_8 >= gates.min_role_recall_at_8,
        "complete_typed_case_rate_at_8": (
            complete >= gates.min_complete_typed_case_rate_at_8
        ),
        "candidate_edge_reduction_rate": (
            edge_reduction >= gates.min_candidate_edge_reduction_rate
        ),
        "schema_valid_rate": len(evaluated) == len(typed),
        "mean_latency_ms": mean_latency <= gates.max_mean_latency_ms,
        "p95_latency_ms": p95_latency <= gates.max_p95_latency_ms,
        "zero_model_requests": requests == 0,
        "zero_prompt_leakage": not any(
            row.get("prompt_leakage", True) for row in typed
        ),
        "candidate_identity_preservation": all(
            row.get("candidate_identity_preserved", False)
            for row in evaluated
        ),
        "input_order_invariance": all(
            row.get("input_order_invariant", False) for row in evaluated
        ),
        "serving_route_disabled": True,
    }
    return {
        "typed_case_count": len(typed),
        "failed_typed_case_count": len(typed) - len(evaluated),
        "role_count": role_count,
        "role_recall_at_4": recall_4,
        "role_recall_at_8": recall_8,
        "complete_typed_case_rate_at_8": complete,
        "candidate_edge_reduction_rate": edge_reduction,
        "schema_valid_rate": len(evaluated) / len(typed),
        "model_request_count": requests,
        "mean_latency_ms": mean_latency,
        "p95_latency_ms": p95_latency,
        "runtime_route_accuracy": sum(row["route_match"] for row in rows)
        / len(rows),
        "gate_checks": checks,
        "decision": (
            "DETERMINISTIC_DESCRIPTOR_RETRIEVER_GATE_PASSED"
            if all(checks.values())
            else "DETERMINISTIC_DESCRIPTOR_RETRIEVER_GATE_FAILED"
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run E7 deterministic safe-descriptor retrieval audit."
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument(
        "--catalog-protocol", type=Path, default=DEFAULT_CATALOG_PROTOCOL
    )
    parser.add_argument(
        "--catalog-upper-bound",
        type=Path,
        default=DEFAULT_CATALOG_UPPER_BOUND,
    )
    parser.add_argument(
        "--failed-live-selector",
        type=Path,
        default=DEFAULT_FAILED_LIVE_SELECTOR,
    )
    parser.add_argument("--e5-run", type=Path, default=DEFAULT_E5_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--private-output", type=Path, default=DEFAULT_PRIVATE_OUTPUT
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol, protocol_sha256 = load_descriptor_retriever_protocol_v1(
        args.protocol.resolve()
    )
    catalog_protocol, catalog_protocol_sha256 = (
        load_descriptor_catalog_protocol_v1(args.catalog_protocol.resolve())
    )
    upper_bound_path = args.catalog_upper_bound.resolve()
    failed_live_path = args.failed_live_selector.resolve()
    upper_bound = json.loads(upper_bound_path.read_text(encoding="ascii"))
    failed_live = json.loads(failed_live_path.read_text(encoding="ascii"))
    if (
        catalog_protocol_sha256 != protocol.source_catalog_protocol_sha256
        or evidence_io._sha256(upper_bound_path)
        != protocol.source_catalog_upper_bound_v2_sha256
        or evidence_io._sha256(failed_live_path)
        != protocol.source_failed_live_selector_v1_sha256
        or upper_bound["decision"] != "ORACLE_CATALOG_GATE_PASSED"
        or failed_live["decision"] != "LIVE_DESCRIPTOR_SELECTOR_GATE_FAILED"
    ):
        raise ValueError("deterministic retriever source evidence is invalid")

    cases, _ = load_finqa_split(
        (DEFAULT_SOURCE_ROOT / "dataset" / "dev.json").resolve(),
        expected_sha256=FINQA_DEV_SHA256,
    )
    cases_by_id = {case.id: case for case in cases}
    source_details = args.e5_run.resolve() / "details.jsonl"
    source_rows = tuple(
        FinQASemanticPlanningCase.model_validate(json.loads(line))
        for line in source_details.read_text(encoding="utf-8").splitlines()
        if line
    )
    expected_ids = [row.case_id for row in source_rows]
    if (
        len(source_rows) != protocol.calibration_case_count
        or case_ids_sha256(expected_ids)
        != protocol.calibration_case_ids_sha256
    ):
        raise ValueError("deterministic retriever cohort is invalid")

    selector = DeterministicFinQADescriptorRetrieverV1()
    guard = RetrievedContentGuard()
    rows = []
    for source_row in source_rows:
        row = live_audit._evaluate_case(
            case=cases_by_id[source_row.case_id],
            source_row=source_row,
            selector=selector,
            guard=guard,
            forbidden_fields=catalog_protocol.forbidden_prompt_fields,
        )
        row["model_request_count"] = 0
        rows.append(row)

    summary = _summarize(rows, protocol)
    private_dir = args.private_output.resolve()
    details_bytes = b"".join(evidence_io._canonical_bytes(row) for row in rows)
    evidence_io._write_once(private_dir / "details.jsonl", details_bytes)
    manifest = {
        "schema_version": "finqa_descriptor_retriever_manifest_v1",
        "run_id": private_dir.name,
        "protocol_sha256": protocol_sha256,
        "catalog_protocol_sha256": catalog_protocol_sha256,
        "catalog_upper_bound_sha256": evidence_io._sha256(upper_bound_path),
        "failed_live_selector_sha256": evidence_io._sha256(failed_live_path),
        "source_details_sha256": evidence_io._sha256(source_details),
        "details_sha256": evidence_io._sha256(private_dir / "details.jsonl"),
        "case_count": len(rows),
        "model_request_count": summary["model_request_count"],
    }
    evidence_io._write_once(
        private_dir / "manifest.json", evidence_io._canonical_bytes(manifest)
    )
    comparisons = {
        name: json.loads(path.read_text(encoding="ascii"))
        for name, path in COMPARISON_EVIDENCE.items()
    }
    public = {
        "claim": "DISCLOSED_DEVELOPMENT_DETERMINISTIC_DESCRIPTOR_RETRIEVAL_CALIBRATION",
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "catalog_protocol_sha256": catalog_protocol_sha256,
        "catalog_upper_bound_sha256": evidence_io._sha256(upper_bound_path),
        "failed_live_selector_sha256": evidence_io._sha256(failed_live_path),
        "private_manifest_sha256": evidence_io._sha256(
            private_dir / "manifest.json"
        ),
        "private_details_sha256": evidence_io._sha256(
            private_dir / "details.jsonl"
        ),
        "case_count": len(rows),
        "retriever_version": protocol.retriever_version,
        **summary,
        "delta_vs_baselines": {
            name: {
                metric: summary[metric] - payload[metric]
                for metric in (
                    "role_recall_at_4",
                    "role_recall_at_8",
                    "complete_typed_case_rate_at_8",
                )
            }
            for name, payload in comparisons.items()
        },
        "serving_route_status": "DISABLED",
        "implementation_sha256": {
            relative: evidence_io._sha256(REPOSITORY_ROOT / relative)
            for relative in IMPLEMENTATION_FILES
        },
        "non_claims": list(protocol.non_claims),
    }
    evidence_io._write_once(
        args.output.resolve(), evidence_io._canonical_bytes(public)
    )
    print(json.dumps(public, indent=2, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
