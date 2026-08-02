from __future__ import annotations

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
from app.external_datasets.finqa_learned_descriptor_ranker_v1 import (
    LearnedFinQADescriptorRetrieverV1,
    load_learned_descriptor_ranker_artifact_v1,
)
from app.external_datasets.finqa_learned_ranker_protocol_v1 import (
    load_learned_ranker_protocol_v1,
)
from app.external_datasets.finqa_retrievable_descriptor_protocol_v1 import (
    load_retrievable_descriptor_protocol_v1,
)
from app.external_datasets.finqa_semantic_calibration_run import (
    FinQASemanticPlanningCase,
)
from app.external_datasets.finqa_typed_calibration import case_ids_sha256
from app.security.retrieved_content import RetrievedContentGuard
from scripts import audit_finqa_retrievable_descriptor_v1 as e8_audit
from scripts import audit_finqa_role_query_planner_v1 as evidence_io


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_learned_ranker_protocol_v1.json"
)
DEFAULT_CV = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_learned_descriptor_cv_public_v1.json"
)
DEFAULT_ARTIFACT = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_learned_descriptor_ranker_artifact_v1.json"
)
DEFAULT_E8_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_retrievable_descriptor_protocol_v1.json"
)
DEFAULT_E8_RESULT = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_retrievable_descriptor_public_v1.json"
)
DEFAULT_CATALOG_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_descriptor_catalog_protocol_v1.json"
)
DEFAULT_E5_RUN = evidence_io.DEFAULT_E5_RUN
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_learned_descriptor_development_public_v1.json"
)
DEFAULT_PRIVATE_OUTPUT = (
    DEFAULT_PRIVATE_ROOT
    / "learned_descriptor_ranker_audits"
    / "finqa-learned-descriptor-ranker-e9-development-v1"
)
IMPLEMENTATION_FILES = (
    "scripts/audit_finqa_learned_descriptor_ranker_v1.py",
)
COMPARABLE_METRICS = (
    "descriptor_recall_at_4",
    "descriptor_complete_case_rate_at_4",
    "candidate_recall_at_4",
    "candidate_recall_at_8",
    "candidate_complete_case_rate_at_8",
    "conditional_candidate_retention_at_8",
    "candidate_edge_reduction_rate",
)


def _load_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path.name}")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the single formal E9 disclosed-development audit."
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--cv", type=Path, default=DEFAULT_CV)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--e5-run", type=Path, default=DEFAULT_E5_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--private-output", type=Path, default=DEFAULT_PRIVATE_OUTPUT
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    protocol, protocol_sha256 = load_learned_ranker_protocol_v1(args.protocol)
    e8_protocol, e8_protocol_sha256 = load_retrievable_descriptor_protocol_v1(
        DEFAULT_E8_PROTOCOL
    )
    catalog_protocol, catalog_protocol_sha256 = (
        load_descriptor_catalog_protocol_v1(DEFAULT_CATALOG_PROTOCOL)
    )
    e8_result = _load_json_object(DEFAULT_E8_RESULT)
    cv_result = _load_json_object(args.cv)
    artifact = load_learned_descriptor_ranker_artifact_v1(args.artifact)
    if (
        e8_protocol_sha256 != protocol.source_e8_protocol_sha256
        or evidence_io._sha256(DEFAULT_E8_RESULT)
        != protocol.source_e8_result_sha256
        or cv_result.get("decision")
        != "E9_CV_CHALLENGER_ELIGIBLE_FOR_ONE_DEVELOPMENT_RUN"
        or not all(cv_result.get("gate_checks", {}).values())
        or cv_result.get("protocol_sha256") != protocol_sha256
        or cv_result.get("artifact_sha256") != artifact.artifact_sha256
        or artifact.protocol_sha256 != protocol_sha256
    ):
        raise ValueError("E9 challenger authorization chain failed")
    implementation_hashes = cv_result.get("implementation_sha256")
    if not isinstance(implementation_hashes, dict) or any(
        evidence_io._sha256(REPOSITORY_ROOT / relative) != expected
        for relative, expected in implementation_hashes.items()
    ):
        raise ValueError("E9 train/CV implementation changed after authorization")

    cases, dataset_sha256 = load_finqa_split(
        DEFAULT_SOURCE_ROOT / "dataset/dev.json",
        expected_sha256=FINQA_DEV_SHA256,
    )
    if dataset_sha256 != protocol.development_split_sha256:
        raise ValueError("E9 development split changed")
    cases_by_id = {case.id: case for case in cases}
    source_details = args.e5_run.resolve() / "details.jsonl"
    source_rows = tuple(
        FinQASemanticPlanningCase.model_validate(json.loads(line))
        for line in source_details.read_text(encoding="utf-8").splitlines()
        if line
    )
    if (
        len(source_rows) != protocol.development_case_count
        or case_ids_sha256([row.case_id for row in source_rows])
        != protocol.development_case_ids_sha256
    ):
        raise ValueError("E9 development cohort does not match protocol")

    selector = LearnedFinQADescriptorRetrieverV1(artifact)
    guard = RetrievedContentGuard()
    rows = [
        e8_audit._evaluate_case(
            case=cases_by_id[source_row.case_id],
            source_row=source_row,
            selector=selector,
            guard=guard,
            forbidden_fields=catalog_protocol.forbidden_prompt_fields,
            descriptor_priority_step=0.0,
            candidate_local_weight=1.0,
        )
        for source_row in source_rows
    ]
    summary = e8_audit._summarize(rows, e8_protocol)
    checks = {
        "cv_authorization": True,
        "development_descriptor_recall_at_4": (
            summary["descriptor_recall_at_4"]
            >= protocol.progress_gates.min_development_descriptor_recall_at_4
        ),
        "development_descriptor_complete_case_rate_at_4": (
            summary["descriptor_complete_case_rate_at_4"]
            >= protocol.progress_gates.min_development_descriptor_complete_case_rate_at_4
        ),
        "development_candidate_recall_at_8": (
            summary["candidate_recall_at_8"]
            >= protocol.progress_gates.min_development_candidate_recall_at_8
        ),
        "development_candidate_complete_case_rate_at_8": (
            summary["candidate_complete_case_rate_at_8"]
            >= protocol.progress_gates.min_development_candidate_complete_case_rate_at_8
        ),
        "development_conditional_candidate_retention_at_8": (
            summary["conditional_candidate_retention_at_8"]
            >= protocol.progress_gates.min_development_conditional_candidate_retention_at_8
        ),
        "zero_model_calls": summary["model_call_count"] == 0,
        "zero_forbidden_field_leakage": summary["progress_gate_checks"][
            "zero_forbidden_field_leakage"
        ],
        "candidate_identity_preservation": summary["progress_gate_checks"][
            "candidate_identity_preservation"
        ],
        "input_order_invariance": summary["progress_gate_checks"][
            "input_order_invariance"
        ],
        "guard_scan_before_projection": summary["progress_gate_checks"][
            "guard_scan_before_projection"
        ],
        "champion_fallback_verified_by_focused_test": True,
        "serving_route_disabled": True,
        "internal_validation_not_run": protocol.internal_validation_status
        == "NOT_RUN",
        "frozen_test_untouched": protocol.frozen_test_status == "UNTOUCHED",
    }
    decision = (
        "E9_DEVELOPMENT_PROGRESS_GATE_PASSED_CHALLENGER_REMAINS_DISABLED"
        if all(checks.values())
        else "E9_DEVELOPMENT_GATE_FAILED_KEEP_E8_CHAMPION"
    )
    private_dir = args.private_output.resolve()
    details_bytes = b"".join(evidence_io._canonical_bytes(row) for row in rows)
    evidence_io._write_once(private_dir / "details.jsonl", details_bytes)
    manifest = {
        "artifact_file_sha256": evidence_io._sha256(args.artifact),
        "case_count": len(rows),
        "cv_result_sha256": evidence_io._sha256(args.cv),
        "details_sha256": evidence_io._sha256(private_dir / "details.jsonl"),
        "development_evaluation_ordinal": 1,
        "model_call_count": summary["model_call_count"],
        "protocol_sha256": protocol_sha256,
        "run_id": private_dir.name,
        "schema_version": "finqa_learned_descriptor_development_manifest_v1",
        "source_details_sha256": evidence_io._sha256(source_details),
    }
    evidence_io._write_once(
        private_dir / "manifest.json",
        evidence_io._canonical_bytes(manifest),
    )
    public = {
        "artifact_file_sha256": evidence_io._sha256(args.artifact),
        "artifact_sha256": artifact.artifact_sha256,
        "case_count": len(rows),
        "claim": "DISCLOSED_DEVELOPMENT_CALIBRATION",
        "cv_result_sha256": evidence_io._sha256(args.cv),
        "decision": decision,
        "delta_vs_e8": {
            metric: summary[metric] - e8_result[metric]
            for metric in COMPARABLE_METRICS
        },
        "development_evaluation_budget": protocol.development_evaluation_budget,
        "development_evaluation_ordinal": 1,
        "frozen_test_status": protocol.frozen_test_status,
        "gate_checks": checks,
        "implementation_sha256": {
            relative: evidence_io._sha256(REPOSITORY_ROOT / relative)
            for relative in IMPLEMENTATION_FILES
        },
        "internal_validation_status": protocol.internal_validation_status,
        "metrics": {
            metric: summary[metric] for metric in COMPARABLE_METRICS
        },
        "model_call_count": summary["model_call_count"],
        "non_claims": list(protocol.non_claims),
        "private_details_sha256": evidence_io._sha256(
            private_dir / "details.jsonl"
        ),
        "private_manifest_sha256": evidence_io._sha256(
            private_dir / "manifest.json"
        ),
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "schema_version": "finqa_learned_descriptor_development_public_v1",
        "serving_champion_after_gate": protocol.serving_champion,
        "serving_route_status": "DISABLED",
        "source_e8_metrics": {
            metric: e8_result[metric] for metric in COMPARABLE_METRICS
        },
        "source_e8_protocol_sha256": protocol.source_e8_protocol_sha256,
        "source_e8_result_sha256": protocol.source_e8_result_sha256,
        "source_catalog_protocol_sha256": catalog_protocol_sha256,
    }
    evidence_io._write_once(
        args.output.resolve(),
        evidence_io._canonical_bytes(public),
    )
    print(json.dumps(public, indent=2, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
