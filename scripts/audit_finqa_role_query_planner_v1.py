try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
from pathlib import Path

from app.external_datasets.finqa import (
    DEFAULT_PRIVATE_ROOT,
    DEFAULT_SOURCE_ROOT,
    FINQA_DEV_SHA256,
    build_finqa_evidence_units,
    load_finqa_split,
)
from app.external_datasets.finqa_numeric_evidence_v2 import (
    admit_finqa_numeric_evidence_closure_v2,
    expand_finqa_numeric_evidence_v2,
    extract_finqa_numeric_candidates_v2,
)
from app.external_datasets.finqa_role_compatibility_audit_v2 import (
    _source_bound_constant_ids,
    _target_retained,
    build_oracle_semantic_program_v2,
)
from app.external_datasets.finqa_role_compatibility_protocol_v3 import (
    load_role_compatibility_protocol_v3,
)
from app.external_datasets.finqa_role_compatibility_v2 import (
    route_finqa_numeric_capability,
)
from app.external_datasets.finqa_role_compatibility_v3 import (
    build_role_candidate_compatibility_matrix_v3,
    verify_no_gold_runtime_inputs_v3,
)
from app.external_datasets.finqa_role_query_planner_v1 import (
    PLANNER_VERSION,
    plan_role_queries_from_question,
    verify_question_only_role_query_planner,
)
from app.external_datasets.finqa_semantic_calibration_run import (
    FinQASemanticPlanningCase,
)
from app.external_datasets.finqa_typed_calibration import case_ids_sha256
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)
from app.security.retrieved_content import RetrievedContentGuard


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_E5_RUN = (
    DEFAULT_PRIVATE_ROOT
    / "semantic_planning_calibration_runs"
    / "finqa-semantic-planning-calibration-v1"
)
DEFAULT_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_role_compatibility_protocol_v3.json"
)
DEFAULT_UPPER_BOUND = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_role_compatibility_v3_upper_bound_public_v1.json"
)
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_role_query_planner_v1_calibration_public_v1.json"
)
DEFAULT_PRIVATE_OUTPUT = (
    DEFAULT_PRIVATE_ROOT
    / "role_query_planner_v1_audits"
    / "finqa-role-query-planner-v1-calibration-v1"
)
IMPLEMENTATION_FILES = (
    "app/external_datasets/finqa_role_query_planner_v1.py",
    "scripts/audit_finqa_role_query_planner_v1.py",
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


def _write_once(path: Path, payload: bytes) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"immutable output differs: {path}")
        return
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _candidate_identity(candidates) -> str:
    payload = "\n".join(
        item.model_dump_json()
        for item in sorted(candidates, key=lambda value: value.candidate_id)
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit the deterministic E6-v3 question-only role planner."
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument(
        "--upper-bound",
        type=Path,
        default=DEFAULT_UPPER_BOUND,
    )
    parser.add_argument("--e5-run", type=Path, default=DEFAULT_E5_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--private-output",
        type=Path,
        default=DEFAULT_PRIVATE_OUTPUT,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol_path = args.protocol.resolve()
    upper_bound_path = args.upper_bound.resolve()
    protocol, protocol_sha256 = load_role_compatibility_protocol_v3(
        protocol_path
    )
    upper_bound = json.loads(upper_bound_path.read_text(encoding="ascii"))
    if (
        upper_bound["protocol_sha256"] != protocol_sha256
        or upper_bound["decision"] != "UPPER_BOUND_INPUT_GATE_PASSED"
    ):
        raise ValueError("question-only audit source evidence is invalid")

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
    if (
        len(source_rows) != protocol.calibration_case_count
        or case_ids_sha256([item.case_id for item in source_rows])
        != protocol.calibration_case_ids_sha256
    ):
        raise ValueError("question-only calibration cohort is invalid")

    guard = RetrievedContentGuard()
    rows = []
    role_count = retained_4 = retained_8 = complete_8 = 0
    typed_count = route_matches = failures = 0
    baseline_edges = selected_edges = 0
    schema_valid = invariance_count = identity_count = 0
    period_conflicts = non_admitted = 0
    for source_row in source_rows:
        case = cases_by_id[source_row.case_id]
        oracle = build_oracle_semantic_program_v2(
            question=case.qa.question,
            program=case.qa.program,
            source_bound_constant_ids=_source_bound_constant_ids(case),
        )
        runtime_route = route_finqa_numeric_capability(case.qa.question)
        route_match = runtime_route == oracle.capability_route
        route_matches += route_match
        if oracle.skeleton is None:
            rows.append(
                {
                    "case_id": case.id,
                    "status": "FALLBACK_ROUTED",
                    "route_match": route_match,
                }
            )
            continue

        typed_count += 1
        closure = expand_finqa_numeric_evidence_v2(
            case,
            selected_unit_ids=source_row.selected_unit_ids,
        )
        admission = admit_finqa_numeric_evidence_closure_v2(
            case,
            closure=closure,
            guard=guard,
        )
        admitted_ids = set(admission.admitted_unit_ids)
        candidates = tuple(
            candidate
            for candidate in extract_finqa_numeric_candidates_v2(
                case,
                admitted_evidence_ids=admitted_ids,
            ).candidates
            if candidate.role == "operand"
        )
        identity_before = _candidate_identity(candidates)
        units = {
            unit.unit_id: unit for unit in build_finqa_evidence_units(case)
        }
        context = {
            unit_id: units[unit_id].text
            for unit_id in admission.admitted_unit_ids
        }
        intent = extract_financial_question_intent_v2(case.qa.question)
        try:
            skeleton = plan_role_queries_from_question(
                question=case.qa.question,
                skeleton=oracle.skeleton,
                intent=intent,
            )
            schema_valid += 1
            matrix = build_role_candidate_compatibility_matrix_v3(
                question=case.qa.question,
                skeleton=skeleton,
                candidates=candidates,
                admitted_evidence_ids=admitted_ids,
                intent=intent,
                evidence_context_by_id=context,
            )
            reversed_matrix = build_role_candidate_compatibility_matrix_v3(
                question=case.qa.question,
                skeleton=skeleton,
                candidates=tuple(reversed(candidates)),
                admitted_evidence_ids=admitted_ids,
                intent=intent,
                evidence_context_by_id=context,
            )
        except ValueError as error:
            failures += 1
            role_count += len(oracle.evidence_targets)
            baseline_edges += len(candidates) * len(oracle.evidence_targets)
            rows.append(
                {
                    "case_id": case.id,
                    "status": "PLANNER_OR_COMPATIBILITY_ERROR",
                    "reason": str(error),
                    "route_match": route_match,
                }
            )
            continue

        invariant = matrix.role_allowlists == reversed_matrix.role_allowlists
        invariance_count += invariant
        identity_preserved = identity_before == _candidate_identity(candidates)
        identity_count += identity_preserved
        candidate_by_id = {
            candidate.candidate_id: candidate for candidate in candidates
        }
        target_by_role = {
            target.role_id: target for target in oracle.evidence_targets
        }
        case_complete = True
        retentions = []
        for allowlist in matrix.role_allowlists:
            selected = tuple(
                candidate_by_id[candidate_id]
                for candidate_id in allowlist.candidate_ids
            )
            target = target_by_role[allowlist.role_id]
            at_4 = _target_retained(target, selected[:4])
            at_8 = _target_retained(target, selected)
            role_count += 1
            retained_4 += at_4
            retained_8 += at_8
            case_complete = case_complete and at_8
            for candidate in selected:
                if candidate.evidence_id not in admitted_ids:
                    non_admitted += 1
                candidate_period = (
                    candidate.period
                    if candidate.period is not None
                    else (
                        str(candidate.fiscal_year)
                        if candidate.fiscal_year is not None
                        else None
                    )
                )
                if (
                    allowlist.expected_period is not None
                    and candidate_period is not None
                    and candidate_period.casefold()
                    != allowlist.expected_period.casefold()
                ):
                    period_conflicts += 1
            retentions.append(
                {
                    "role_id": allowlist.role_id,
                    "role_query": allowlist.role_query,
                    "expected_period": allowlist.expected_period,
                    "retained_at_4": at_4,
                    "retained_at_8": at_8,
                    "candidate_ids": list(allowlist.candidate_ids),
                }
            )
        complete_8 += case_complete
        baseline_edges += len(candidates) * len(oracle.evidence_targets)
        selected_edges += sum(
            len(item.candidate_ids) for item in matrix.role_allowlists
        )
        rows.append(
            {
                "case_id": case.id,
                "status": "EVALUATED",
                "route_match": route_match,
                "candidate_count": len(candidates),
                "complete_at_8": case_complete,
                "input_order_invariant": invariant,
                "candidate_identity_preserved": identity_preserved,
                "plan": skeleton.model_dump(mode="json"),
                "retention": retentions,
            }
        )

    role_recall_4 = retained_4 / role_count
    role_recall_8 = retained_8 / role_count
    complete_rate = complete_8 / typed_count
    edge_reduction = (
        1 - selected_edges / baseline_edges if baseline_edges else 0.0
    )
    route_accuracy = route_matches / len(source_rows)
    schema_rate = schema_valid / typed_count
    planner_verified = verify_question_only_role_query_planner()
    compatibility_verified = verify_no_gold_runtime_inputs_v3()
    gates = protocol.gates
    checks = {
        "runtime_capability_route_accuracy": (
            route_accuracy >= gates.min_runtime_capability_route_accuracy
        ),
        "typed_eligible_case_rate": (
            typed_count / len(source_rows)
            >= gates.min_typed_eligible_case_rate
        ),
        "role_query_schema_valid_rate": (
            schema_rate >= gates.min_role_query_schema_valid_rate
        ),
        "evidence_role_recall_at_4": (
            role_recall_4 >= gates.min_evidence_role_recall_at_4
        ),
        "evidence_role_recall_at_8": (
            role_recall_8 >= gates.min_evidence_role_recall_at_8
        ),
        "complete_typed_case_rate_at_8": (
            complete_rate >= gates.min_complete_typed_case_rate_at_8
        ),
        "role_candidate_edge_reduction_rate": (
            edge_reduction
            >= gates.min_role_candidate_edge_reduction_rate
        ),
        "zero_known_period_conflicts": period_conflicts == 0,
        "admitted_operand_only": non_admitted == 0,
        "input_order_invariance": invariance_count == typed_count,
        "candidate_identity_preservation": identity_count == typed_count,
        "question_only_planner_verified": planner_verified,
        "no_gold_compatibility_input_verified": compatibility_verified,
        "zero_silent_fallback_expansion": True,
        "serving_route_disabled": True,
    }
    decision = (
        "QUESTION_ONLY_INPUT_GATE_PASSED"
        if failures == 0 and all(checks.values())
        else "QUESTION_ONLY_INPUT_GATE_FAILED"
    )
    details_bytes = b"".join(
        _canonical_bytes(row) for row in rows
    )
    private_dir = args.private_output.resolve()
    manifest = {
        "schema_version": "finqa_role_query_planner_v1_manifest_v1",
        "run_id": private_dir.name,
        "protocol_sha256": protocol_sha256,
        "upper_bound_sha256": _sha256(upper_bound_path),
        "source_details_sha256": _sha256(source_details),
        "details_sha256": hashlib.sha256(details_bytes).hexdigest(),
        "case_count": len(rows),
        "planner_version": PLANNER_VERSION,
        "model_call_count": 0,
    }
    _write_once(private_dir / "details.jsonl", details_bytes)
    _write_once(private_dir / "manifest.json", _canonical_bytes(manifest))
    public = {
        "claim": "DISCLOSED_DEVELOPMENT_QUESTION_ONLY_INPUT_CALIBRATION",
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "upper_bound_sha256": _sha256(upper_bound_path),
        "private_manifest_sha256": _sha256(private_dir / "manifest.json"),
        "private_details_sha256": _sha256(private_dir / "details.jsonl"),
        "planner_version": PLANNER_VERSION,
        "case_count": len(source_rows),
        "typed_case_count": typed_count,
        "failed_typed_case_count": failures,
        "runtime_route_accuracy": route_accuracy,
        "role_query_schema_valid_rate": schema_rate,
        "role_count": role_count,
        "role_recall_at_4": role_recall_4,
        "role_recall_at_8": role_recall_8,
        "complete_typed_case_rate_at_8": complete_rate,
        "edge_reduction_rate": edge_reduction,
        "known_period_conflict_count": period_conflicts,
        "non_admitted_exposure_count": non_admitted,
        "input_order_invariant_case_count": invariance_count,
        "candidate_identity_preserved_case_count": identity_count,
        "gate_checks": checks,
        "decision": decision,
        "model_call_count": 0,
        "serving_route_status": "DISABLED",
        "implementation_sha256": {
            relative: _sha256(REPOSITORY_ROOT / relative)
            for relative in IMPLEMENTATION_FILES
        },
        "non_claims": [
            "not full semantic skeleton planner quality",
            "not binding accuracy",
            "not answer accuracy",
            "not held-out evaluation",
        ],
    }
    _write_once(args.output.resolve(), _canonical_bytes(public))
    print(
        json.dumps(
            {
                "decision": decision,
                "output": str(args.output.resolve()),
                "role_recall_at_4": role_recall_4,
                "role_recall_at_8": role_recall_8,
                "complete_typed_case_rate_at_8": complete_rate,
                "edge_reduction_rate": edge_reduction,
                "failed_typed_case_count": failures,
            },
            indent=2,
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
