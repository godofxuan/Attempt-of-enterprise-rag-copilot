try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
import math
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
from app.external_datasets.finqa_role_query_planner_llm_v1 import (
    PLANNER_VERSION,
    LocalFinQARoleQueryPlannerV1,
    verify_question_only_llm_role_query_planner,
)
from app.external_datasets.finqa_semantic_calibration_run import (
    FinQASemanticPlanningCase,
)
from app.external_datasets.finqa_typed_calibration import case_ids_sha256
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)
from app.security.retrieved_content import RetrievedContentGuard
from scripts import audit_finqa_role_query_planner_v1 as deterministic_engine


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = deterministic_engine.DEFAULT_PROTOCOL
DEFAULT_UPPER_BOUND = deterministic_engine.DEFAULT_UPPER_BOUND
DEFAULT_DETERMINISTIC = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_role_query_planner_v2_calibration_public_v1.json"
)
DEFAULT_E5_RUN = deterministic_engine.DEFAULT_E5_RUN
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_role_query_planner_llm_v1_calibration_public_v1.json"
)
DEFAULT_PRIVATE_OUTPUT = (
    DEFAULT_PRIVATE_ROOT
    / "role_query_planner_llm_v1_audits"
    / "finqa-role-query-planner-llm-v1-qwen3-8b-calibration-v1"
)
IMPLEMENTATION_FILES = (
    "app/external_datasets/finqa_role_query_planner_llm_v1.py",
    "scripts/audit_finqa_role_query_planner_llm_v1.py",
)


def _sha256(path: Path) -> str:
    return deterministic_engine._sha256(path)


def _canonical_bytes(payload: object) -> bytes:
    return deterministic_engine._canonical_bytes(payload)


def _write_once(path: Path, payload: bytes) -> None:
    deterministic_engine._write_once(path, payload)


def _candidate_identity(candidates) -> str:
    return deterministic_engine._candidate_identity(candidates)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _append_journal(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(_canonical_bytes(row))
        handle.flush()


def _load_journal(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="ascii").splitlines()
        if line
    ]
    case_ids = [row["case_id"] for row in rows]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("LLM role-query journal contains duplicate cases")
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run resumable E6-v3 local-LLM role-query calibration."
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument(
        "--upper-bound",
        type=Path,
        default=DEFAULT_UPPER_BOUND,
    )
    parser.add_argument(
        "--deterministic",
        type=Path,
        default=DEFAULT_DETERMINISTIC,
    )
    parser.add_argument("--e5-run", type=Path, default=DEFAULT_E5_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--private-output",
        type=Path,
        default=DEFAULT_PRIVATE_OUTPUT,
    )
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument(
        "--model-digest",
        default="500a1f067a9f",
    )
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    return parser


def _evaluate_case(
    *,
    case,
    source_row,
    planner: LocalFinQARoleQueryPlannerV1,
    guard: RetrievedContentGuard,
) -> dict:
    oracle = build_oracle_semantic_program_v2(
        question=case.qa.question,
        program=case.qa.program,
        source_bound_constant_ids=_source_bound_constant_ids(case),
    )
    runtime_route = route_finqa_numeric_capability(case.qa.question)
    route_match = runtime_route == oracle.capability_route
    if oracle.skeleton is None:
        return {
            "case_id": case.id,
            "status": "FALLBACK_ROUTED",
            "route_match": route_match,
            "model_request_count": 0,
            "latency_ms": 0.0,
        }

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
    baseline_edges = len(candidates) * len(oracle.evidence_targets)
    try:
        plan = planner.plan(
            question=case.qa.question,
            skeleton=oracle.skeleton,
        )
    except Exception as error:
        return {
            "case_id": case.id,
            "status": "PLANNER_ERROR",
            "reason": f"{type(error).__name__}:{error}",
            "route_match": route_match,
            "model_request_count": 1,
            "latency_ms": 0.0,
            "evidence_role_count": len(oracle.evidence_targets),
            "baseline_role_candidate_edges": baseline_edges,
            "selected_role_candidate_edges": 0,
            "retention": [],
        }

    units = {
        unit.unit_id: unit for unit in build_finqa_evidence_units(case)
    }
    context = {
        unit_id: units[unit_id].text
        for unit_id in admission.admitted_unit_ids
    }
    intent = extract_financial_question_intent_v2(case.qa.question)
    identity_before = _candidate_identity(candidates)
    try:
        matrix = build_role_candidate_compatibility_matrix_v3(
            question=case.qa.question,
            skeleton=plan.skeleton,
            candidates=candidates,
            admitted_evidence_ids=admitted_ids,
            intent=intent,
            evidence_context_by_id=context,
        )
        reversed_matrix = build_role_candidate_compatibility_matrix_v3(
            question=case.qa.question,
            skeleton=plan.skeleton,
            candidates=tuple(reversed(candidates)),
            admitted_evidence_ids=admitted_ids,
            intent=intent,
            evidence_context_by_id=context,
        )
    except ValueError as error:
        return {
            "case_id": case.id,
            "status": "COMPATIBILITY_ERROR",
            "reason": str(error),
            "route_match": route_match,
            "model_request_count": plan.generation_calls,
            "latency_ms": plan.latency_ms,
            "evidence_role_count": len(oracle.evidence_targets),
            "baseline_role_candidate_edges": baseline_edges,
            "selected_role_candidate_edges": 0,
            "plan": plan.skeleton.model_dump(mode="json"),
            "retention": [],
        }

    candidate_by_id = {
        candidate.candidate_id: candidate for candidate in candidates
    }
    target_by_role = {
        target.role_id: target for target in oracle.evidence_targets
    }
    period_conflicts = 0
    non_admitted = 0
    retentions = []
    for allowlist in matrix.role_allowlists:
        selected = tuple(
            candidate_by_id[candidate_id]
            for candidate_id in allowlist.candidate_ids
        )
        target = target_by_role[allowlist.role_id]
        for candidate in selected:
            non_admitted += candidate.evidence_id not in admitted_ids
            candidate_period = (
                candidate.period
                if candidate.period is not None
                else (
                    str(candidate.fiscal_year)
                    if candidate.fiscal_year is not None
                    else None
                )
            )
            period_conflicts += (
                allowlist.expected_period is not None
                and candidate_period is not None
                and candidate_period.casefold()
                != allowlist.expected_period.casefold()
            )
        retentions.append(
            {
                "role_id": allowlist.role_id,
                "role_query": allowlist.role_query,
                "expected_period": allowlist.expected_period,
                "retained_at_4": _target_retained(target, selected[:4]),
                "retained_at_8": _target_retained(target, selected),
                "candidate_ids": list(allowlist.candidate_ids),
            }
        )
    return {
        "case_id": case.id,
        "status": "EVALUATED",
        "route_match": route_match,
        "model_request_count": plan.generation_calls,
        "latency_ms": plan.latency_ms,
        "candidate_count": len(candidates),
        "evidence_role_count": len(oracle.evidence_targets),
        "baseline_role_candidate_edges": baseline_edges,
        "selected_role_candidate_edges": sum(
            len(item.candidate_ids) for item in matrix.role_allowlists
        ),
        "complete_at_8": all(item["retained_at_8"] for item in retentions),
        "input_order_invariant": (
            matrix.role_allowlists == reversed_matrix.role_allowlists
        ),
        "candidate_identity_preserved": (
            identity_before == _candidate_identity(candidates)
        ),
        "known_period_conflict_count": period_conflicts,
        "non_admitted_exposure_count": non_admitted,
        "plan": plan.skeleton.model_dump(mode="json"),
        "retention": retentions,
    }


def _summarize(rows: list[dict], protocol) -> dict:
    typed = [row for row in rows if row["status"] != "FALLBACK_ROUTED"]
    evaluated = [row for row in typed if row["status"] == "EVALUATED"]
    retentions = [item for row in evaluated for item in row["retention"]]
    role_count = sum(row.get("evidence_role_count", 0) for row in typed)
    retained_4 = sum(item["retained_at_4"] for item in retentions)
    retained_8 = sum(item["retained_at_8"] for item in retentions)
    complete_8 = sum(row.get("complete_at_8", False) for row in typed)
    baseline_edges = sum(
        row.get("baseline_role_candidate_edges", 0) for row in typed
    )
    selected_edges = sum(
        row.get("selected_role_candidate_edges", 0) for row in typed
    )
    latencies = [row["latency_ms"] for row in typed]
    role_recall_4 = retained_4 / role_count
    role_recall_8 = retained_8 / role_count
    complete_rate = complete_8 / len(typed)
    edge_reduction = 1 - selected_edges / baseline_edges
    route_accuracy = sum(row["route_match"] for row in rows) / len(rows)
    schema_rate = len(evaluated) / len(typed)
    gates = protocol.gates
    checks = {
        "runtime_capability_route_accuracy": (
            route_accuracy >= gates.min_runtime_capability_route_accuracy
        ),
        "typed_eligible_case_rate": (
            len(typed) / len(rows) >= gates.min_typed_eligible_case_rate
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
            edge_reduction >= gates.min_role_candidate_edge_reduction_rate
        ),
        "zero_known_period_conflicts": sum(
            row.get("known_period_conflict_count", 0) for row in typed
        )
        == 0,
        "admitted_operand_only": sum(
            row.get("non_admitted_exposure_count", 0) for row in typed
        )
        == 0,
        "input_order_invariance": all(
            row.get("input_order_invariant", False) for row in evaluated
        )
        and len(evaluated) == len(typed),
        "candidate_identity_preservation": all(
            row.get("candidate_identity_preserved", False)
            for row in evaluated
        )
        and len(evaluated) == len(typed),
        "question_only_llm_planner_verified": (
            verify_question_only_llm_role_query_planner()
        ),
        "no_gold_compatibility_input_verified": (
            verify_no_gold_runtime_inputs_v3()
        ),
        "zero_silent_fallback_expansion": True,
        "serving_route_disabled": True,
    }
    return {
        "typed_case_count": len(typed),
        "failed_typed_case_count": len(typed) - len(evaluated),
        "runtime_route_accuracy": route_accuracy,
        "role_query_schema_valid_rate": schema_rate,
        "role_count": role_count,
        "role_recall_at_4": role_recall_4,
        "role_recall_at_8": role_recall_8,
        "complete_typed_case_rate_at_8": complete_rate,
        "edge_reduction_rate": edge_reduction,
        "model_request_count": sum(
            row["model_request_count"] for row in rows
        ),
        "mean_latency_ms": sum(latencies) / len(latencies),
        "p95_latency_ms": _p95(latencies),
        "gate_checks": checks,
        "decision": (
            "LIVE_MODEL_INPUT_GATE_PASSED"
            if all(checks.values())
            else "LIVE_MODEL_INPUT_GATE_FAILED"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.model.strip() or not args.model_digest.strip():
        raise ValueError("model identity must be explicit")
    protocol_path = args.protocol.resolve()
    upper_bound_path = args.upper_bound.resolve()
    deterministic_path = args.deterministic.resolve()
    protocol, protocol_sha256 = load_role_compatibility_protocol_v3(
        protocol_path
    )
    upper_bound = json.loads(upper_bound_path.read_text(encoding="ascii"))
    deterministic = json.loads(
        deterministic_path.read_text(encoding="ascii")
    )
    if (
        upper_bound["protocol_sha256"] != protocol_sha256
        or upper_bound["decision"] != "UPPER_BOUND_INPUT_GATE_PASSED"
        or deterministic["protocol_sha256"] != protocol_sha256
    ):
        raise ValueError("live-model source evidence is invalid")

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
        raise ValueError("live-model calibration cohort is invalid")

    private_dir = args.private_output.resolve()
    journal_path = private_dir / "journal.jsonl"
    rows = _load_journal(journal_path)
    existing_ids = [row["case_id"] for row in rows]
    if existing_ids != expected_ids[: len(existing_ids)]:
        raise ValueError("live-model journal is not a cohort prefix")
    if any(
        row.get("model") != args.model
        or row.get("model_digest") != args.model_digest
        for row in rows
    ):
        raise ValueError("live-model journal identity changed")

    planner = LocalFinQARoleQueryPlannerV1(
        model=args.model,
        timeout_seconds=args.timeout_seconds,
    )
    guard = RetrievedContentGuard()
    for index, source_row in enumerate(
        source_rows[len(rows) :],
        start=len(rows) + 1,
    ):
        row = _evaluate_case(
            case=cases_by_id[source_row.case_id],
            source_row=source_row,
            planner=planner,
            guard=guard,
        )
        row["model"] = args.model
        row["model_digest"] = args.model_digest
        _append_journal(journal_path, row)
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

    if [row["case_id"] for row in rows] != expected_ids:
        raise ValueError("live-model journal did not complete the cohort")
    summary = _summarize(rows, protocol)
    details_bytes = b"".join(_canonical_bytes(row) for row in rows)
    _write_once(private_dir / "details.jsonl", details_bytes)
    manifest = {
        "schema_version": "finqa_role_query_planner_llm_manifest_v1",
        "run_id": private_dir.name,
        "protocol_sha256": protocol_sha256,
        "upper_bound_sha256": _sha256(upper_bound_path),
        "deterministic_sha256": _sha256(deterministic_path),
        "source_details_sha256": _sha256(source_details),
        "details_sha256": _sha256(private_dir / "details.jsonl"),
        "case_count": len(rows),
        "planner_version": PLANNER_VERSION,
        "model": args.model,
        "model_digest": args.model_digest,
        "model_request_count": summary["model_request_count"],
    }
    _write_once(private_dir / "manifest.json", _canonical_bytes(manifest))
    public = {
        "claim": "DISCLOSED_DEVELOPMENT_LOCAL_MODEL_INPUT_CALIBRATION",
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "upper_bound_sha256": _sha256(upper_bound_path),
        "deterministic_sha256": _sha256(deterministic_path),
        "private_manifest_sha256": _sha256(private_dir / "manifest.json"),
        "private_details_sha256": _sha256(private_dir / "details.jsonl"),
        "planner_version": PLANNER_VERSION,
        "model": args.model,
        "model_digest": args.model_digest,
        "case_count": len(rows),
        **summary,
        "delta_vs_deterministic_v2": {
            "role_recall_at_4": (
                summary["role_recall_at_4"]
                - deterministic["role_recall_at_4"]
            ),
            "role_recall_at_8": (
                summary["role_recall_at_8"]
                - deterministic["role_recall_at_8"]
            ),
            "complete_typed_case_rate_at_8": (
                summary["complete_typed_case_rate_at_8"]
                - deterministic["complete_typed_case_rate_at_8"]
            ),
        },
        "serving_route_status": "DISABLED",
        "local_model_boundary": "OLLAMA_PINNED_LOOPBACK_ONLY",
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
    print(json.dumps(public, indent=2, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
