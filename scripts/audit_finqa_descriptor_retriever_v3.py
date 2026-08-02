try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
from pathlib import Path

from app.config import get_settings
from app.external_datasets.finqa import (
    DEFAULT_PRIVATE_ROOT,
    DEFAULT_SOURCE_ROOT,
    FINQA_DEV_SHA256,
    load_finqa_split,
)
from app.external_datasets.finqa_descriptor_catalog_protocol_v1 import (
    load_descriptor_catalog_protocol_v1,
)
from app.external_datasets.finqa_descriptor_retriever_protocol_v3 import (
    load_descriptor_retriever_protocol_v3,
)
from app.external_datasets.finqa_descriptor_retriever_v3 import (
    HybridFinQADescriptorRetrieverV3,
)
from app.external_datasets.finqa_semantic_calibration_run import (
    FinQASemanticPlanningCase,
)
from app.external_datasets.finqa_typed_calibration import case_ids_sha256
from app.runtime.ollama_embeddings import OllamaEmbeddingClient
from app.security.retrieved_content import RetrievedContentGuard
from scripts import audit_finqa_descriptor_catalog_upper_bound_v1 as catalog_audit
from scripts import audit_finqa_descriptor_retriever_v1 as audit_v1
from scripts import audit_finqa_descriptor_retriever_v2 as audit_v2
from scripts import audit_finqa_descriptor_selector_live_v1 as live_audit
from scripts import audit_finqa_role_query_planner_llm_v1 as live_io
from scripts import audit_finqa_role_query_planner_v1 as evidence_io


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_descriptor_retriever_protocol_v3.json"
)
DEFAULT_CATALOG_PROTOCOL = catalog_audit.DEFAULT_PROTOCOL
DEFAULT_CATALOG_UPPER_BOUND = audit_v1.DEFAULT_CATALOG_UPPER_BOUND
DEFAULT_RETRIEVER_V2 = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_descriptor_retriever_public_v2.json"
)
DEFAULT_E5_RUN = evidence_io.DEFAULT_E5_RUN
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_descriptor_retriever_public_v3.json"
)
DEFAULT_PRIVATE_OUTPUT = (
    DEFAULT_PRIVATE_ROOT
    / "descriptor_retriever_audits"
    / "finqa-hybrid-descriptor-retriever-bge-m3-v3"
)
FORBIDDEN_EMBEDDING_MARKERS = (
    "candidate_id",
    "evidence_id",
    "source_id",
    "raw_text",
    "normalized_value",
    "provenance",
    "gold_program",
    "gold_answer",
    "case_id",
    "desc-",
    "num-",
)
COMPARISON_EVIDENCE = {
    "deterministic_retriever_v1": audit_v2.DEFAULT_RETRIEVER_V1,
    "normalized_lexical_retriever_v2": DEFAULT_RETRIEVER_V2,
    "descriptor_selector_qwen3_8b_v1": audit_v1.DEFAULT_FAILED_LIVE_SELECTOR,
}
IMPLEMENTATION_FILES = (
    "app/external_datasets/finqa_safe_descriptor_catalog_v1.py",
    "app/external_datasets/finqa_safe_descriptor_catalog_v2.py",
    "app/external_datasets/finqa_descriptor_retriever_v2.py",
    "app/external_datasets/finqa_descriptor_retriever_v3.py",
    "app/external_datasets/finqa_descriptor_retriever_protocol_v3.py",
    "app/runtime/ollama_embeddings.py",
    "scripts/audit_finqa_descriptor_retriever_v3.py",
)


class AuditedEmbeddingBatch:
    def __init__(self, client: OllamaEmbeddingClient) -> None:
        self.client = client
        self.logical_request_count = 0
        self.payload_violation_count = 0

    def __call__(self, texts: list[str]):
        self.logical_request_count += 1
        serialized = "\n".join(texts).casefold()
        if any(marker in serialized for marker in FORBIDDEN_EMBEDDING_MARKERS):
            self.payload_violation_count += 1
        return self.client.embed_batch(texts)


def _summarize(rows, protocol, *, model_identity_match: bool):
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
    embedding_requests = sum(
        row["embedding_request_count"] for row in typed
    )
    generation_requests = sum(
        row["generation_request_count"] for row in typed
    )
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
        "embedding_request_budget": (
            embedding_requests
            <= gates.max_embedding_requests_per_typed_case * len(typed)
        ),
        "zero_generation_requests": generation_requests == 0,
        "pinned_model_identity": model_identity_match,
        "safe_descriptor_only_embedding_payload": not any(
            row.get("embedding_payload_violation", True) for row in typed
        ),
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
        "embedding_request_count": embedding_requests,
        "generation_request_count": generation_requests,
        "mean_latency_ms": mean_latency,
        "p95_latency_ms": p95_latency,
        "runtime_route_accuracy": sum(row["route_match"] for row in rows)
        / len(rows),
        "gate_checks": checks,
        "decision": (
            "HYBRID_DESCRIPTOR_RETRIEVER_GATE_PASSED"
            if all(checks.values())
            else "HYBRID_DESCRIPTOR_RETRIEVER_GATE_FAILED"
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run E7 local BGE-M3 hybrid descriptor audit."
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
        "--retriever-v2", type=Path, default=DEFAULT_RETRIEVER_V2
    )
    parser.add_argument("--e5-run", type=Path, default=DEFAULT_E5_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--private-output", type=Path, default=DEFAULT_PRIVATE_OUTPUT
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol, protocol_sha256 = load_descriptor_retriever_protocol_v3(
        args.protocol.resolve()
    )
    catalog_protocol, catalog_protocol_sha256 = (
        load_descriptor_catalog_protocol_v1(args.catalog_protocol.resolve())
    )
    upper_bound_path = args.catalog_upper_bound.resolve()
    retriever_v2_path = args.retriever_v2.resolve()
    upper_bound = json.loads(upper_bound_path.read_text(encoding="ascii"))
    retriever_v2 = json.loads(retriever_v2_path.read_text(encoding="ascii"))
    if (
        catalog_protocol_sha256 != protocol.source_catalog_protocol_sha256
        or evidence_io._sha256(upper_bound_path)
        != protocol.source_catalog_upper_bound_v2_sha256
        or evidence_io._sha256(retriever_v2_path)
        != protocol.source_retriever_v2_result_sha256
        or upper_bound["decision"] != "ORACLE_CATALOG_GATE_PASSED"
        or retriever_v2["decision"]
        != "DETERMINISTIC_DESCRIPTOR_RETRIEVER_GATE_FAILED"
    ):
        raise ValueError("hybrid retriever source evidence is invalid")

    client = OllamaEmbeddingClient.from_settings(get_settings())
    model_identity_match = (
        client.model_identifier == protocol.embedding_model
        and client.model_sha256 == protocol.embedding_model_sha256
        and client.dimension == protocol.embedding_dimension
    )
    if not model_identity_match:
        raise ValueError("hybrid retriever model identity does not match protocol")
    audited_embed = AuditedEmbeddingBatch(client)
    selector = HybridFinQADescriptorRetrieverV3(
        embed_batch=audited_embed,
        model_identifier=client.model_identifier,
        model_sha256=client.model_sha256,
        embedding_dimension=client.dimension,
    )
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
        raise ValueError("hybrid retriever cohort is invalid")

    guard = RetrievedContentGuard()
    rows = []
    for index, source_row in enumerate(source_rows, start=1):
        requests_before = audited_embed.logical_request_count
        violations_before = audited_embed.payload_violation_count
        row = live_audit._evaluate_case(
            case=cases_by_id[source_row.case_id],
            source_row=source_row,
            selector=selector,
            guard=guard,
            forbidden_fields=catalog_protocol.forbidden_prompt_fields,
        )
        row["embedding_request_count"] = (
            audited_embed.logical_request_count - requests_before
        )
        row["generation_request_count"] = 0
        row["embedding_payload_violation"] = (
            audited_embed.payload_violation_count > violations_before
        )
        rows.append(row)
        print(
            json.dumps(
                {
                    "case": index,
                    "case_count": len(source_rows),
                    "status": row["status"],
                    "latency_ms": row["latency_ms"],
                },
                ensure_ascii=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
    summary = _summarize(
        rows, protocol, model_identity_match=model_identity_match
    )

    private_dir = args.private_output.resolve()
    details_bytes = b"".join(evidence_io._canonical_bytes(row) for row in rows)
    evidence_io._write_once(private_dir / "details.jsonl", details_bytes)
    manifest = {
        "schema_version": "finqa_descriptor_retriever_manifest_v3",
        "run_id": private_dir.name,
        "protocol_sha256": protocol_sha256,
        "catalog_protocol_sha256": catalog_protocol_sha256,
        "catalog_upper_bound_sha256": evidence_io._sha256(upper_bound_path),
        "retriever_v2_result_sha256": evidence_io._sha256(retriever_v2_path),
        "source_details_sha256": evidence_io._sha256(source_details),
        "details_sha256": evidence_io._sha256(private_dir / "details.jsonl"),
        "case_count": len(rows),
        "embedding_model": client.model_identifier,
        "embedding_model_sha256": client.model_sha256,
        "embedding_dimension": client.dimension,
        "initialization_embedding_probe_count": 1,
        "embedding_request_count": summary["embedding_request_count"],
        "generation_request_count": summary["generation_request_count"],
    }
    evidence_io._write_once(
        private_dir / "manifest.json", evidence_io._canonical_bytes(manifest)
    )
    comparisons = {
        name: json.loads(path.read_text(encoding="ascii"))
        for name, path in COMPARISON_EVIDENCE.items()
    }
    public = {
        "claim": "DISCLOSED_DEVELOPMENT_LOCAL_HYBRID_DESCRIPTOR_RETRIEVAL_CALIBRATION",
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "catalog_protocol_sha256": catalog_protocol_sha256,
        "catalog_upper_bound_sha256": evidence_io._sha256(upper_bound_path),
        "retriever_v2_result_sha256": evidence_io._sha256(retriever_v2_path),
        "private_manifest_sha256": evidence_io._sha256(
            private_dir / "manifest.json"
        ),
        "private_details_sha256": evidence_io._sha256(
            private_dir / "details.jsonl"
        ),
        "case_count": len(rows),
        "retriever_version": protocol.retriever_version,
        "embedding_model": client.model_identifier,
        "embedding_model_sha256": client.model_sha256,
        "embedding_dimension": client.dimension,
        "initialization_embedding_probe_count": 1,
        "rrf": {
            "k": protocol.rrf_k,
            "dense_weight": protocol.dense_weight,
            "lexical_weight": protocol.lexical_weight,
        },
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
