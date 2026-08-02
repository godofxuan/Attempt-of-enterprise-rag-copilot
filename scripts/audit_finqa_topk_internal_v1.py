from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
from dataclasses import dataclass
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
from app.external_datasets.finqa_descriptor_retriever_v5 import (
    DeterministicFinQADescriptorRetrieverV5,
)
from app.external_datasets.finqa_retrievable_descriptor_protocol_v1 import (
    load_retrievable_descriptor_protocol_v1,
)
from app.external_datasets.finqa_role_compatibility_audit_v2 import (
    _source_bound_constant_ids,
    build_oracle_semantic_program_v2,
)
from app.external_datasets.finqa_topk_ranker_protocol_v1 import (
    load_topk_ranker_protocol_v1,
)
from app.external_datasets.finqa_topk_ranker_v1 import (
    TopKBoundaryFinQADescriptorRetrieverV1,
    load_topk_ranker_artifact_v1,
)
from app.external_datasets.finqa_typed_calibration import case_ids_sha256
from app.security.retrieved_content import RetrievedContentGuard
from scripts import audit_finqa_retrievable_descriptor_v1 as e8_audit
from scripts import audit_finqa_role_query_planner_v1 as evidence_io


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/external_datasets/evidence/finqa_topk_ranker_protocol_v1.json"
CV_EVIDENCE = ROOT / "docs/external_datasets/evidence/finqa_topk_nested_cv_public_v1.json"
ARTIFACT = ROOT / "docs/external_datasets/evidence/finqa_topk_ranker_artifact_v1.json"
E8_PROTOCOL = ROOT / "docs/external_datasets/evidence/finqa_retrievable_descriptor_protocol_v1.json"
CATALOG_PROTOCOL = ROOT / "docs/external_datasets/evidence/finqa_descriptor_catalog_protocol_v1.json"
SOURCE_DETAILS = (
    DEFAULT_PRIVATE_ROOT
    / "typed_retrospective_runs/finqa-typed-retrospective-dev-v1/details.jsonl"
)
PRIVATE_SPLIT = (
    DEFAULT_PRIVATE_ROOT / "typed_contract_calibration/gate-e2-v1/split.json"
)
OUTPUT = ROOT / "docs/external_datasets/evidence/finqa_topk_internal_validation_public_v1.json"
EXECUTION_INCIDENT = ROOT / "docs/external_datasets/evidence/finqa_topk_internal_execution_incident_v1.json"
PRIVATE_OUTPUT = (
    DEFAULT_PRIVATE_ROOT / "topk_ranker_runs/finqa-top4-boundary-e11-internal-v1"
)
E11_IMPLEMENTATION_FILES = (
    "app/external_datasets/finqa_topk_ranker_protocol_v1.py",
    "app/external_datasets/finqa_topk_ranker_v1.py",
    "app/external_datasets/finqa_topk_ranker_training_v1.py",
    "scripts/train_finqa_topk_ranker_v1.py",
)
AUDIT_IMPLEMENTATION_FILES = (
    "scripts/audit_finqa_topk_internal_v1.py",
)


@dataclass(frozen=True)
class InternalInputV1:
    case_id: str
    selected_unit_ids: tuple[str, ...]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.resolve().read_bytes()).hexdigest()


def _canonical_without_newline(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _load_internal_inputs(
    *,
    details_path: Path,
    case_ids: tuple[str, ...],
) -> tuple[InternalInputV1, ...]:
    wanted = set(case_ids)
    selected = {}
    for line in details_path.resolve().read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        payload = json.loads(line)
        case_id = payload.get("case_id")
        if case_id not in wanted:
            continue
        unit_ids = payload.get("selected_unit_ids")
        if (
            not isinstance(unit_ids, list)
            or len(unit_ids) != 10
            or len(set(unit_ids)) != 10
            or any(not isinstance(item, str) or not item for item in unit_ids)
        ):
            raise ValueError("E11 internal selected units are invalid")
        if case_id in selected:
            raise ValueError("E11 internal input has duplicate case ID")
        selected[case_id] = tuple(unit_ids)
    if set(selected) != wanted:
        raise ValueError("E11 internal input IDs are incomplete")
    return tuple(
        InternalInputV1(case_id=case_id, selected_unit_ids=selected[case_id])
        for case_id in sorted(case_ids)
    )


def _selected_input_sha256(rows: tuple[InternalInputV1, ...]) -> str:
    payload = [
        {"case_id": row.case_id, "unit_ids": list(row.selected_unit_ids)}
        for row in rows
    ]
    return hashlib.sha256(_canonical_without_newline(payload)).hexdigest()


def _paired_role_transitions(
    left_rows: list[dict[str, object]],
    right_rows: list[dict[str, object]],
    *,
    metric: str,
) -> dict[str, int]:
    right_by_id = {row["case_id"]: row for row in right_rows}
    transitions = {
        "retained": 0,
        "regressed": 0,
        "gained": 0,
        "missed_both": 0,
    }
    for left in left_rows:
        right = right_by_id[left["case_id"]]
        left_roles = {
            item["role_id"]: bool(item[metric])
            for item in left.get("retention", [])
        }
        right_roles = {
            item["role_id"]: bool(item[metric])
            for item in right.get("retention", [])
        }
        if set(left_roles) != set(right_roles):
            raise ValueError("E11 paired role identities changed")
        for role_id in sorted(left_roles):
            left_hit = left_roles[role_id]
            right_hit = right_roles[role_id]
            if left_hit and right_hit:
                transitions["retained"] += 1
            elif left_hit:
                transitions["regressed"] += 1
            elif right_hit:
                transitions["gained"] += 1
            else:
                transitions["missed_both"] += 1
    return transitions


def _common_input_identity(
    left_rows: list[dict[str, object]],
    right_rows: list[dict[str, object]],
) -> bool:
    right_by_id = {row["case_id"]: row for row in right_rows}
    return all(
        row["case_id"] in right_by_id
        and row.get("status") == right_by_id[row["case_id"]].get("status")
        and row.get("source_candidate_count")
        == right_by_id[row["case_id"]].get("source_candidate_count")
        and row.get("represented_candidate_count")
        == right_by_id[row["case_id"]].get("represented_candidate_count")
        and row.get("catalog_sha256")
        == right_by_id[row["case_id"]].get("catalog_sha256")
        for row in left_rows
    )


def _evaluate_with_shared_capability_boundary(
    *,
    case,
    source_row: InternalInputV1,
    selector,
    guard: RetrievedContentGuard,
    forbidden_fields: tuple[str, ...],
) -> dict[str, object]:
    try:
        build_oracle_semantic_program_v2(
            question=case.qa.question,
            program=case.qa.program,
            source_bound_constant_ids=_source_bound_constant_ids(case),
        )
    except (ValueError, TypeError) as error:
        return {
            "case_id": case.id,
            "status": "FALLBACK_ROUTED",
            "route_match": False,
            "model_call_count": 0,
            "fallback_reason": (
                f"SHARED_TYPED_CAPABILITY_BOUNDARY:{type(error).__name__}:"
                f"{str(error).splitlines()[0]}"
            )[:320],
        }
    return e8_audit._evaluate_case(
        case=case,
        source_row=source_row,
        selector=selector,
        guard=guard,
        forbidden_fields=forbidden_fields,
        descriptor_priority_step=0.0,
        candidate_local_weight=1.0,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the one-shot E11 internal Top-4 ranker comparison."
    )
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--cv-evidence", type=Path, default=CV_EVIDENCE)
    parser.add_argument("--artifact", type=Path, default=ARTIFACT)
    parser.add_argument("--private-split", type=Path, default=PRIVATE_SPLIT)
    parser.add_argument("--source-details", type=Path, default=SOURCE_DETAILS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--private-output", type=Path, default=PRIVATE_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol, protocol_sha256 = load_topk_ranker_protocol_v1(
        args.protocol.resolve()
    )
    artifact = load_topk_ranker_artifact_v1(args.artifact.resolve())
    cv = json.loads(args.cv_evidence.resolve().read_text(encoding="utf-8"))
    if (
        cv["decision"]
        != "E11_OUTER_CV_AUTHORIZED_FOR_SINGLE_INTERNAL_VALIDATION"
        or not all(cv["gate_checks"].values())
        or cv["protocol_sha256"] != protocol_sha256
        or artifact.protocol_sha256 != protocol_sha256
        or cv["artifact_sha256"] != artifact.artifact_sha256
    ):
        raise ValueError("E11 internal run is not authorized by outer CV")
    for relative in E11_IMPLEMENTATION_FILES:
        if cv["implementation_sha256"][relative] != _sha256(ROOT / relative):
            raise ValueError("E11 implementation changed after outer CV")
    boundary = protocol.internal_validation
    if (
        _sha256(args.private_split) != boundary.source_private_split_sha256
        or _sha256(args.source_details)
        != boundary.source_retrospective_details_sha256
    ):
        raise ValueError("E11 internal source binding failed")
    split = json.loads(args.private_split.resolve().read_text(encoding="utf-8"))
    case_ids = tuple(split["internal_validation_case_ids"])
    if (
        len(case_ids) != boundary.case_count
        or case_ids_sha256(case_ids) != boundary.case_ids_sha256
    ):
        raise ValueError("E11 internal case boundary changed")
    source_rows = _load_internal_inputs(
        details_path=args.source_details,
        case_ids=case_ids,
    )
    if _selected_input_sha256(source_rows) != boundary.selected_input_sha256:
        raise ValueError("E11 internal selected input hash changed")

    cases, _ = load_finqa_split(
        (DEFAULT_SOURCE_ROOT / "dataset/dev.json").resolve(),
        expected_sha256=FINQA_DEV_SHA256,
    )
    cases_by_id = {case.id: case for case in cases}
    if any(row.case_id not in cases_by_id for row in source_rows):
        raise ValueError("E11 internal cases are missing from pinned dev")
    e8_protocol, e8_protocol_sha256 = load_retrievable_descriptor_protocol_v1(
        E8_PROTOCOL
    )
    catalog_protocol, catalog_protocol_sha256 = (
        load_descriptor_catalog_protocol_v1(CATALOG_PROTOCOL)
    )
    guard = RetrievedContentGuard()
    selectors = {
        "e8": DeterministicFinQADescriptorRetrieverV5(),
        "e11": TopKBoundaryFinQADescriptorRetrieverV1(artifact),
    }
    evaluated = {}
    for arm, selector in selectors.items():
        evaluated[arm] = [
            _evaluate_with_shared_capability_boundary(
                case=cases_by_id[source_row.case_id],
                source_row=source_row,
                selector=selector,
                guard=guard,
                forbidden_fields=catalog_protocol.forbidden_prompt_fields,
            )
            for source_row in source_rows
        ]
    summaries = {
        arm: e8_audit._summarize(rows, e8_protocol)
        for arm, rows in evaluated.items()
    }
    metric_names = (
        "descriptor_recall_at_4",
        "descriptor_complete_case_rate_at_4",
        "candidate_recall_at_8",
        "candidate_complete_case_rate_at_8",
        "conditional_candidate_retention_at_8",
    )
    deltas = {
        metric: summaries["e11"][metric] - summaries["e8"][metric]
        for metric in metric_names
    }
    descriptor_transitions = _paired_role_transitions(
        evaluated["e8"],
        evaluated["e11"],
        metric="descriptor_hit_at_4",
    )
    candidate_transitions = _paired_role_transitions(
        evaluated["e8"],
        evaluated["e11"],
        metric="retained_at_8",
    )
    gates = protocol.internal_gates
    checks = {
        "descriptor_recall_at_4": deltas["descriptor_recall_at_4"]
        >= gates.min_descriptor_recall_delta_at_4,
        "descriptor_complete_case_rate_at_4": (
            deltas["descriptor_complete_case_rate_at_4"]
            >= gates.min_descriptor_complete_case_delta_at_4
        ),
        "candidate_recall_at_8": deltas["candidate_recall_at_8"]
        >= gates.min_candidate_recall_delta_at_8,
        "candidate_complete_case_rate_at_8": (
            deltas["candidate_complete_case_rate_at_8"]
            >= gates.min_candidate_complete_case_delta_at_8
        ),
        "conditional_candidate_retention_at_8": (
            deltas["conditional_candidate_retention_at_8"]
            >= gates.min_conditional_retention_delta_at_8
        ),
        "zero_model_calls": all(
            summary["model_call_count"] == 0 for summary in summaries.values()
        ),
        "input_order_invariance": all(
            row.get("input_order_invariant", False)
            for rows in evaluated.values()
            for row in rows
            if row["status"] == "EVALUATED"
        ),
        "guard_scan_before_projection": all(
            row.get("guard_scan_before_projection", False)
            for rows in evaluated.values()
            for row in rows
            if row["status"] == "EVALUATED"
        ),
        "candidate_identity_preservation": all(
            row.get("candidate_identity_preserved", False)
            for rows in evaluated.values()
            for row in rows
            if row["status"] == "EVALUATED"
        ),
        "common_input_identity": _common_input_identity(
            evaluated["e8"], evaluated["e11"]
        ),
        "serving_route_disabled": protocol.challenger_serving_status
        == "DISABLED",
        "frozen_test_untouched": protocol.frozen_test_status == "UNTOUCHED",
    }
    passed = all(checks.values())
    private_dir = args.private_output.resolve()
    detail_hashes = {}
    for arm, rows in evaluated.items():
        content = b"".join(evidence_io._canonical_bytes(row) for row in rows)
        path = private_dir / f"{arm}_details.jsonl"
        evidence_io._write_once(path, content)
        detail_hashes[f"{arm}_details_sha256"] = _sha256(path)
    manifest = {
        "artifact_file_sha256": _sha256(args.artifact),
        "audit_implementation_sha256": {
            relative: _sha256(ROOT / relative)
            for relative in AUDIT_IMPLEMENTATION_FILES
        },
        "case_ids_sha256": boundary.case_ids_sha256,
        "case_count": len(source_rows),
        "cv_evidence_sha256": _sha256(args.cv_evidence),
        **detail_hashes,
        "evaluation_ordinal": 1,
        "execution_incident_sha256": _sha256(EXECUTION_INCIDENT),
        "protocol_sha256": protocol_sha256,
        "run_id": private_dir.name,
        "schema_version": "finqa_topk_internal_manifest_v1",
        "selected_input_sha256": boundary.selected_input_sha256,
    }
    evidence_io._write_once(
        private_dir / "manifest.json",
        evidence_io._canonical_bytes(manifest),
    )
    public = {
        "artifact_file_sha256": _sha256(args.artifact),
        "artifact_sha256": artifact.artifact_sha256,
        "case_count": len(source_rows),
        "case_ids_sha256": boundary.case_ids_sha256,
        "challenger_status": (
            "INTERNAL_VALIDATION_PASSED_SERVING_DISABLED"
            if passed
            else "INTERNAL_VALIDATION_FAILED_SERVING_DISABLED"
        ),
        "claim": "ONE_SHOT_INTERNAL_VALIDATION_NOT_ANSWER_ACCURACY",
        "decision": (
            "E11_INTERNAL_GATE_PASSED_ELIGIBLE_FOR_NEXT_STAGE"
            if passed
            else "E11_INTERNAL_GATE_FAILED_KEEP_E8_CHAMPION"
        ),
        "delta_vs_e8": deltas,
        "descriptor_recall_at_4_transitions": descriptor_transitions,
        "candidate_recall_at_8_transitions": candidate_transitions,
        "e8_metrics": {
            metric: summaries["e8"][metric] for metric in metric_names
        },
        "e11_metrics": {
            metric: summaries["e11"][metric] for metric in metric_names
        },
        "evaluation_budget": boundary.evaluation_budget,
        "evaluation_ordinal": 1,
        "execution_incident_count": 1,
        "frozen_test_status": protocol.frozen_test_status,
        "gate_checks": checks,
        "implementation_sha256": {
            relative: _sha256(ROOT / relative)
            for relative in AUDIT_IMPLEMENTATION_FILES
        },
        "model_call_count": 0,
        "private_manifest_sha256": _sha256(private_dir / "manifest.json"),
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "schema_version": "finqa_topk_internal_validation_public_v1",
        "selected_input_sha256": boundary.selected_input_sha256,
        "serving_champion_after_gate": (
            "finqa_deterministic_descriptor_retriever_v5"
        ),
        "serving_route_status": "DISABLED",
        "source_catalog_protocol_sha256": catalog_protocol_sha256,
        "source_cv_evidence_sha256": _sha256(args.cv_evidence),
        "source_e8_protocol_sha256": e8_protocol_sha256,
        "source_execution_incident_sha256": _sha256(EXECUTION_INCIDENT),
        "source_private_split_sha256": _sha256(args.private_split),
        "source_retrospective_details_sha256": _sha256(args.source_details),
        "non_claims": [
            "not answer accuracy",
            "not frozen-test evidence",
            "not serving authorization",
            "not production financial reliability",
            "one-shot internal result must not be reused for E11 tuning",
        ],
    }
    evidence_io._write_once(
        args.output.resolve(),
        evidence_io._canonical_bytes(public),
    )
    print(json.dumps(public, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
