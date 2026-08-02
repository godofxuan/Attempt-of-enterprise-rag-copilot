try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
import re
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
from app.external_datasets.finqa_role_compatibility_v2 import (
    route_finqa_numeric_capability,
)
from app.external_datasets.finqa_role_compatibility_v3 import (
    build_role_candidate_compatibility_matrix_v3,
    verify_no_gold_runtime_inputs_v3,
)
from app.external_datasets.finqa_role_compatibility_protocol_v3 import (
    load_role_compatibility_protocol_v3,
)
from app.external_datasets.finqa_semantic_calibration_run import (
    FinQASemanticPlanningCase,
)
from app.external_datasets.finqa_semantic_program_v3 import (
    SemanticProgramSkeletonV3,
    SemanticRoleSpecV3,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)
from app.external_datasets.finqa_typed_calibration import case_ids_sha256
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
DEFAULT_V2_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_role_compatibility_protocol_v2.json"
)
DEFAULT_V2_PUBLIC = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_role_compatibility_v2_calibration_public_v4.json"
)
DEFAULT_V2_RUN = (
    DEFAULT_PRIVATE_ROOT
    / "role_compatibility_v2_audits"
    / "finqa-role-compatibility-v2-audit-v4"
)
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_role_compatibility_v3_upper_bound_public_v1.json"
)
IMPLEMENTATION_FILES = (
    "app/external_datasets/finqa_semantic_program_v3.py",
    "app/external_datasets/finqa_role_compatibility_v3.py",
    "app/external_datasets/finqa_role_compatibility_protocol_v3.py",
    "scripts/diagnose_finqa_role_compatibility_v3_upper_bound.py",
)
_NUMBER = re.compile(r"(?<!\w)-?\d+(?:[.,]\d+)*(?:%|\b)")
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def _clean_role_query(value: str) -> str:
    value = _NUMBER.sub(" ", value)
    return " ".join(value.split())[:160].strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_once(path: Path, payload: bytes) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(
                "upper-bound evidence exists with different bytes"
            )
        return
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _role_hint(
    *,
    role,
    target,
    candidates,
    gold_evidence_ids: set[str],
    context: dict[str, str],
) -> SemanticRoleSpecV3:
    matches = [
        candidate
        for candidate in candidates
        if candidate.evidence_id in gold_evidence_ids
        and _target_retained(target, (candidate,))
    ]
    if not matches:
        matches = [
            candidate
            for candidate in candidates
            if _target_retained(target, (candidate,))
        ]
    if not matches:
        raise ValueError(f"oracle role {role.role_id} is absent from source pool")
    matches.sort(
        key=lambda candidate: (
            candidate.source_kind != "table_cell",
            -sum(
                bool(item)
                for item in (
                    candidate.metric,
                    candidate.entity,
                    candidate.row_header,
                    candidate.column_header,
                )
            ),
            candidate.candidate_id,
        )
    )
    candidate = matches[0]
    descriptor = " ".join(
        item
        for item in (
            candidate.metric,
            candidate.entity,
            candidate.row_header,
            candidate.column_header,
        )
        if item
    )
    if not descriptor:
        descriptor = context[candidate.evidence_id]
    query = _clean_role_query(descriptor)
    if len(query) < 2:
        query = role.semantic_role.replace("_", " ")
    period = candidate.period
    if period is None and candidate.fiscal_year is not None:
        period = str(candidate.fiscal_year)
    if period is None:
        period_match = _YEAR.search(descriptor)
        period = period_match.group(1) if period_match is not None else None
    return SemanticRoleSpecV3(
        role_id=role.role_id,
        semantic_role=role.semantic_role,
        period_role=role.period_role,
        role_query=query,
        expected_period=period,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the E6-v3 offline role-query upper-bound audit."
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--v2-protocol", type=Path, default=DEFAULT_V2_PROTOCOL)
    parser.add_argument("--v2-public", type=Path, default=DEFAULT_V2_PUBLIC)
    parser.add_argument("--v2-run", type=Path, default=DEFAULT_V2_RUN)
    parser.add_argument("--e5-run", type=Path, default=DEFAULT_E5_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol, protocol_sha256 = load_role_compatibility_protocol_v3(
        args.protocol.resolve()
    )
    if (
        _sha256(args.v2_protocol.resolve())
        != protocol.source_gate_e6_v2_protocol_sha256
        or _sha256(args.v2_public.resolve())
        != protocol.source_gate_e6_v2_public_sha256
        or _sha256(args.v2_run.resolve() / "manifest.json")
        != protocol.source_gate_e6_v2_private_manifest_sha256
        or _sha256(args.v2_run.resolve() / "details.jsonl")
        != protocol.source_gate_e6_v2_private_details_sha256
    ):
        raise ValueError("E6-v3 source evidence does not match protocol")
    cases, _ = load_finqa_split(
        (DEFAULT_SOURCE_ROOT / "dataset" / "dev.json").resolve(),
        expected_sha256=FINQA_DEV_SHA256,
    )
    cases_by_id = {case.id: case for case in cases}
    rows = tuple(
        FinQASemanticPlanningCase.model_validate(json.loads(line))
        for line in (args.e5_run.resolve() / "details.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    )
    if (
        len(rows) != protocol.calibration_case_count
        or case_ids_sha256([item.case_id for item in rows])
        != protocol.calibration_case_ids_sha256
    ):
        raise ValueError("E6-v3 calibration cohort does not match protocol")
    guard = RetrievedContentGuard()
    role_count = retained_4 = retained_8 = complete_8 = 0
    typed_count = route_matches = failures = 0
    baseline_edges = selected_edges = 0
    failed_cases = []
    for source_row in rows:
        case = cases_by_id[source_row.case_id]
        oracle = build_oracle_semantic_program_v2(
            question=case.qa.question,
            program=case.qa.program,
            source_bound_constant_ids=_source_bound_constant_ids(case),
        )
        runtime_route = route_finqa_numeric_capability(case.qa.question)
        route_matches += runtime_route == oracle.capability_route
        if oracle.skeleton is None:
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
        units = {
            unit.unit_id: unit for unit in build_finqa_evidence_units(case)
        }
        context = {
            unit_id: units[unit_id].text
            for unit_id in admission.admitted_unit_ids
        }
        target_by_role = {
            target.role_id: target for target in oracle.evidence_targets
        }
        skeleton = SemanticProgramSkeletonV3(
            roles=tuple(
                _role_hint(
                    role=role,
                    target=target_by_role[role.role_id],
                    candidates=candidates,
                    gold_evidence_ids=set(case.qa.gold_inds),
                    context=context,
                )
                for role in oracle.skeleton.roles
            ),
            steps=oracle.skeleton.steps,
            output_step_id=oracle.skeleton.output_step_id,
        )
        try:
            matrix = build_role_candidate_compatibility_matrix_v3(
                question=case.qa.question,
                skeleton=skeleton,
                candidates=candidates,
                admitted_evidence_ids=admitted_ids,
                intent=extract_financial_question_intent_v2(
                    case.qa.question
                ),
                evidence_context_by_id=context,
            )
        except ValueError as error:
            failures += 1
            failed_cases.append(
                {"case_id": case.id, "reason": str(error)}
            )
            role_count += len(oracle.evidence_targets)
            baseline_edges += len(candidates) * len(oracle.evidence_targets)
            continue
        candidate_by_id = {
            candidate.candidate_id: candidate for candidate in candidates
        }
        case_complete = True
        for allowlist in matrix.role_allowlists:
            target = target_by_role[allowlist.role_id]
            selected = tuple(
                candidate_by_id[candidate_id]
                for candidate_id in allowlist.candidate_ids
            )
            role_count += 1
            at_4 = _target_retained(target, selected[:4])
            at_8 = _target_retained(target, selected)
            retained_4 += at_4
            retained_8 += at_8
            case_complete = case_complete and at_8
        complete_8 += case_complete
        baseline_edges += len(candidates) * len(oracle.evidence_targets)
        selected_edges += sum(
            len(item.candidate_ids) for item in matrix.role_allowlists
        )
    role_recall_4 = retained_4 / role_count
    role_recall_8 = retained_8 / role_count
    complete_rate = complete_8 / typed_count
    edge_reduction = (
        1 - selected_edges / baseline_edges if baseline_edges else 0
    )
    route_accuracy = route_matches / len(rows)
    passed = (
        failures == 0
        and route_accuracy
        >= protocol.gates.min_runtime_capability_route_accuracy
        and typed_count / len(rows)
        >= protocol.gates.min_typed_eligible_case_rate
        and role_recall_4 >= protocol.gates.min_evidence_role_recall_at_4
        and role_recall_8 >= protocol.gates.min_evidence_role_recall_at_8
        and complete_rate
        >= protocol.gates.min_complete_typed_case_rate_at_8
        and edge_reduction
        >= protocol.gates.min_role_candidate_edge_reduction_rate
        and verify_no_gold_runtime_inputs_v3()
    )
    payload = {
        "claim": "OFFLINE_GOLD_DESCRIPTOR_UPPER_BOUND_ONLY",
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "case_count": len(rows),
        "typed_case_count": typed_count,
        "failed_typed_case_count": failures,
        "runtime_route_accuracy": route_accuracy,
        "role_count": role_count,
        "role_query_schema_valid_rate": 1.0,
        "role_recall_at_4": role_recall_4,
        "role_recall_at_8": role_recall_8,
        "complete_typed_case_rate_at_8": complete_rate,
        "edge_reduction_rate": edge_reduction,
        "failed_cases": failed_cases,
        "decision": (
            "UPPER_BOUND_INPUT_GATE_PASSED"
            if passed
            else "UPPER_BOUND_INPUT_GATE_FAILED"
        ),
        "no_gold_runtime_input_verified": verify_no_gold_runtime_inputs_v3(),
        "model_call_count": 0,
        "serving_route_status": "DISABLED",
        "source_evidence_sha256": {
            "v2_protocol": _sha256(args.v2_protocol.resolve()),
            "v2_public": _sha256(args.v2_public.resolve()),
            "v2_private_manifest": _sha256(
                args.v2_run.resolve() / "manifest.json"
            ),
            "v2_private_details": _sha256(
                args.v2_run.resolve() / "details.jsonl"
            ),
        },
        "implementation_sha256": {
            relative: _sha256(REPOSITORY_ROOT / relative)
            for relative in IMPLEMENTATION_FILES
        },
        "non_claims": [
            "not planner quality",
            "not answer accuracy",
            "not held-out evaluation",
        ],
    }
    content = (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")
    _write_once(args.output, content)
    print(
        json.dumps(
            {
                "decision": payload["decision"],
                "output": str(args.output.resolve()),
                "role_recall_at_4": role_recall_4,
                "role_recall_at_8": role_recall_8,
                "complete_typed_case_rate_at_8": complete_rate,
                "edge_reduction_rate": edge_reduction,
                "model_call_count": 0,
                "serving_route_status": "DISABLED",
            },
            indent=2,
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
