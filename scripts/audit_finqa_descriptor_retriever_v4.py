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
from app.external_datasets.finqa_descriptor_retriever_protocol_v4 import (
    load_descriptor_retriever_protocol_v4,
)
from app.external_datasets.finqa_descriptor_retriever_v4 import (
    StructuredFinQADescriptorRetrieverV4,
)
from app.external_datasets.finqa_semantic_calibration_run import (
    FinQASemanticPlanningCase,
)
from app.external_datasets.finqa_typed_calibration import case_ids_sha256
from app.security.retrieved_content import RetrievedContentGuard
from scripts import audit_finqa_descriptor_catalog_upper_bound_v1 as catalog_audit
from scripts import audit_finqa_descriptor_retriever_v1 as audit_v1
from scripts import audit_finqa_descriptor_retriever_v2 as audit_v2
from scripts import audit_finqa_descriptor_retriever_v3 as audit_v3
from scripts import audit_finqa_descriptor_selector_live_v1 as live_audit
from scripts import audit_finqa_role_query_planner_v1 as evidence_io


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_descriptor_retriever_protocol_v4.json"
)
DEFAULT_CATALOG_PROTOCOL = catalog_audit.DEFAULT_PROTOCOL
DEFAULT_CATALOG_UPPER_BOUND = audit_v1.DEFAULT_CATALOG_UPPER_BOUND
DEFAULT_RETRIEVER_V2 = audit_v3.DEFAULT_RETRIEVER_V2
DEFAULT_FAILED_RETRIEVER_V3 = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_descriptor_retriever_public_v3.json"
)
DEFAULT_E5_RUN = evidence_io.DEFAULT_E5_RUN
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_descriptor_retriever_public_v4.json"
)
DEFAULT_PRIVATE_OUTPUT = (
    DEFAULT_PRIVATE_ROOT
    / "descriptor_retriever_audits"
    / "finqa-typed-structural-descriptor-retriever-v4"
)
COMPARISON_EVIDENCE = {
    "deterministic_retriever_v1": audit_v2.DEFAULT_RETRIEVER_V1,
    "normalized_lexical_retriever_v2": DEFAULT_RETRIEVER_V2,
    "hybrid_bge_m3_retriever_v3": DEFAULT_FAILED_RETRIEVER_V3,
}
IMPLEMENTATION_FILES = (
    "app/external_datasets/finqa_safe_descriptor_catalog_v1.py",
    "app/external_datasets/finqa_safe_descriptor_catalog_v2.py",
    "app/external_datasets/finqa_descriptor_retriever_v2.py",
    "app/external_datasets/finqa_descriptor_retriever_v4.py",
    "app/external_datasets/finqa_descriptor_retriever_protocol_v4.py",
    "scripts/audit_finqa_descriptor_retriever_v4.py",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run E7 typed structural descriptor retrieval audit."
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
    parser.add_argument(
        "--failed-retriever-v3",
        type=Path,
        default=DEFAULT_FAILED_RETRIEVER_V3,
    )
    parser.add_argument("--e5-run", type=Path, default=DEFAULT_E5_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--private-output", type=Path, default=DEFAULT_PRIVATE_OUTPUT
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol, protocol_sha256 = load_descriptor_retriever_protocol_v4(
        args.protocol.resolve()
    )
    catalog_protocol, catalog_protocol_sha256 = (
        load_descriptor_catalog_protocol_v1(args.catalog_protocol.resolve())
    )
    upper_bound_path = args.catalog_upper_bound.resolve()
    retriever_v2_path = args.retriever_v2.resolve()
    failed_v3_path = args.failed_retriever_v3.resolve()
    upper_bound = json.loads(upper_bound_path.read_text(encoding="ascii"))
    retriever_v2 = json.loads(retriever_v2_path.read_text(encoding="ascii"))
    failed_v3 = json.loads(failed_v3_path.read_text(encoding="ascii"))
    if (
        catalog_protocol_sha256 != protocol.source_catalog_protocol_sha256
        or evidence_io._sha256(upper_bound_path)
        != protocol.source_catalog_upper_bound_v2_sha256
        or evidence_io._sha256(retriever_v2_path)
        != protocol.source_retriever_v2_result_sha256
        or evidence_io._sha256(failed_v3_path)
        != protocol.source_failed_retriever_v3_result_sha256
        or upper_bound["decision"] != "ORACLE_CATALOG_GATE_PASSED"
        or retriever_v2["decision"]
        != "DETERMINISTIC_DESCRIPTOR_RETRIEVER_GATE_FAILED"
        or failed_v3["decision"] != "HYBRID_DESCRIPTOR_RETRIEVER_GATE_FAILED"
    ):
        raise ValueError("structured retriever source evidence is invalid")

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
        raise ValueError("structured retriever cohort is invalid")

    selector = StructuredFinQADescriptorRetrieverV4()
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
    summary = audit_v1._summarize(rows, protocol)

    private_dir = args.private_output.resolve()
    details_bytes = b"".join(evidence_io._canonical_bytes(row) for row in rows)
    evidence_io._write_once(private_dir / "details.jsonl", details_bytes)
    manifest = {
        "schema_version": "finqa_descriptor_retriever_manifest_v4",
        "run_id": private_dir.name,
        "protocol_sha256": protocol_sha256,
        "catalog_protocol_sha256": catalog_protocol_sha256,
        "catalog_upper_bound_sha256": evidence_io._sha256(upper_bound_path),
        "retriever_v2_result_sha256": evidence_io._sha256(retriever_v2_path),
        "failed_retriever_v3_result_sha256": evidence_io._sha256(failed_v3_path),
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
        "claim": "DISCLOSED_DEVELOPMENT_TYPED_STRUCTURAL_DESCRIPTOR_RETRIEVAL_CALIBRATION",
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "catalog_protocol_sha256": catalog_protocol_sha256,
        "catalog_upper_bound_sha256": evidence_io._sha256(upper_bound_path),
        "retriever_v2_result_sha256": evidence_io._sha256(retriever_v2_path),
        "failed_retriever_v3_result_sha256": evidence_io._sha256(failed_v3_path),
        "private_manifest_sha256": evidence_io._sha256(
            private_dir / "manifest.json"
        ),
        "private_details_sha256": evidence_io._sha256(
            private_dir / "details.jsonl"
        ),
        "case_count": len(rows),
        "retriever_version": protocol.retriever_version,
        "structural_bonus": protocol.structural_bonus,
        "interventions": list(protocol.interventions),
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
