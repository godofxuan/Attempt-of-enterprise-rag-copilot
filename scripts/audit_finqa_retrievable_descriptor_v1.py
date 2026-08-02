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
    build_finqa_evidence_units,
    load_finqa_split,
)
from app.external_datasets.finqa_descriptor_candidate_reranker_v1 import (
    rerank_descriptor_candidates_v1,
)
from app.external_datasets.finqa_descriptor_catalog_protocol_v1 import (
    load_descriptor_catalog_protocol_v1,
)
from app.external_datasets.finqa_descriptor_retriever_v5 import (
    DeterministicFinQADescriptorRetrieverV5,
)
from app.external_datasets.finqa_numeric_evidence_v2 import (
    admit_finqa_numeric_evidence_closure_v2,
    expand_finqa_numeric_evidence_v2,
    extract_finqa_numeric_candidates_v2,
)
from app.external_datasets.finqa_retrievable_descriptor_protocol_v1 import (
    load_retrievable_descriptor_protocol_v1,
)
from app.external_datasets.finqa_role_compatibility_audit_v2 import (
    _source_bound_constant_ids,
    _target_retained,
    build_oracle_semantic_program_v2,
)
from app.external_datasets.finqa_role_compatibility_v2 import (
    route_finqa_numeric_capability,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    build_retrievable_safe_descriptor_catalog_v3,
    catalog_prompt_payload_v3,
)
from app.external_datasets.finqa_semantic_calibration_run import (
    FinQASemanticPlanningCase,
)
from app.external_datasets.finqa_typed_calibration import case_ids_sha256
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)
from app.security.retrieved_content import RetrievedContentGuard
from scripts import audit_finqa_descriptor_catalog_upper_bound_v1 as catalog_audit
from scripts import audit_finqa_role_query_planner_v1 as evidence_io


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_retrievable_descriptor_protocol_v1.json"
)
DEFAULT_CATALOG_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_descriptor_catalog_protocol_v1.json"
)
DEFAULT_CATALOG_UPPER_BOUND = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_descriptor_catalog_upper_bound_public_v2.json"
)
DEFAULT_RETRIEVER_V2 = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_descriptor_retriever_public_v2.json"
)
DEFAULT_E5_RUN = evidence_io.DEFAULT_E5_RUN
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_retrievable_descriptor_public_v1.json"
)
DEFAULT_PRIVATE_OUTPUT = (
    DEFAULT_PRIVATE_ROOT
    / "retrievable_descriptor_audits"
    / "finqa-retrievable-descriptor-e8-v1"
)
IMPLEMENTATION_FILES = (
    "app/external_datasets/finqa_retrievable_descriptor_protocol_v1.py",
    "app/external_datasets/finqa_safe_descriptor_catalog_v3.py",
    "app/external_datasets/finqa_descriptor_retriever_v5.py",
    "app/external_datasets/finqa_descriptor_candidate_reranker_v1.py",
    "scripts/audit_finqa_retrievable_descriptor_v1.py",
)


def _candidate_tuple(candidate_ids, candidate_by_id):
    return tuple(candidate_by_id[candidate_id] for candidate_id in candidate_ids)


def _evaluate_case(
    *,
    case,
    source_row,
    selector,
    guard,
    forbidden_fields,
    descriptor_priority_step,
    candidate_local_weight,
):
    oracle = build_oracle_semantic_program_v2(
        question=case.qa.question,
        program=case.qa.program,
        source_bound_constant_ids=_source_bound_constant_ids(case),
    )
    route_match = (
        route_finqa_numeric_capability(case.qa.question)
        == oracle.capability_route
    )
    if oracle.skeleton is None:
        return {
            "case_id": case.id,
            "status": "FALLBACK_ROUTED",
            "route_match": route_match,
            "model_call_count": 0,
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
    units = {unit.unit_id: unit for unit in build_finqa_evidence_units(case)}
    context = {
        unit_id: units[unit_id].text
        for unit_id in admission.admitted_unit_ids
    }
    evidence_rank_by_id = {
        unit_id: index
        for index, unit_id in enumerate(admission.admitted_unit_ids)
    }
    reversed_context = dict(reversed(tuple(context.items())))
    identity_before = evidence_io._candidate_identity(candidates)
    baseline_edges = len(candidates) * len(oracle.evidence_targets)
    try:
        catalog_build = build_retrievable_safe_descriptor_catalog_v3(
            candidates=candidates,
            admitted_evidence_ids=admitted_ids,
            evidence_context_by_id=context,
            guard=guard,
        )
        reverse_build = build_retrievable_safe_descriptor_catalog_v3(
            candidates=tuple(reversed(candidates)),
            admitted_evidence_ids=admitted_ids,
            evidence_context_by_id=reversed_context,
            guard=guard,
        )
        selection = selector.select(
            question=case.qa.question,
            skeleton=oracle.skeleton,
            catalog=catalog_build.catalog,
        )
        reverse_selection = selector.select(
            question=case.qa.question,
            skeleton=oracle.skeleton,
            catalog=reverse_build.catalog,
        )
    except Exception as error:
        return {
            "case_id": case.id,
            "status": "E8_ERROR",
            "reason": f"{type(error).__name__}:{error}",
            "route_match": route_match,
            "model_call_count": 0,
            "evidence_role_count": len(oracle.evidence_targets),
            "source_candidate_count": len(candidates),
            "represented_candidate_count": 0,
            "baseline_role_candidate_edges": baseline_edges,
            "selected_role_candidate_edges": 0,
            "retention": [],
        }

    prompt_payload = catalog_prompt_payload_v3(catalog_build.catalog)
    prompt_chars = len(json.dumps(prompt_payload, ensure_ascii=True))
    prompt_leakage = catalog_audit._prompt_has_forbidden_fields(
        prompt_payload,
        forbidden_fields,
    )
    intent = extract_financial_question_intent_v2(case.qa.question)
    role_by_id = {role.role_id: role for role in oracle.skeleton.roles}
    target_by_id = {
        target.role_id: target for target in oracle.evidence_targets
    }
    selection_by_role = {
        item.role_id: item.descriptor_ids
        for item in selection.selections.selections
    }
    reverse_selection_by_role = {
        item.role_id: item.descriptor_ids
        for item in reverse_selection.selections.selections
    }
    candidate_by_id = {item.candidate_id: item for item in candidates}
    reverse_candidate_by_id = {
        item.candidate_id: item for item in reversed(candidates)
    }
    retentions = []
    selected_edges = 0
    case_invariant = (
        catalog_build.catalog == reverse_build.catalog
        and catalog_build.candidate_ids_by_descriptor
        == reverse_build.candidate_ids_by_descriptor
        and selection_by_role == reverse_selection_by_role
    )
    for role_id, descriptor_ids in selection_by_role.items():
        role = role_by_id[role_id]
        target = target_by_id[role_id]
        oracle_descriptor_ids = catalog_audit._oracle_descriptor_ids(
            target=target,
            candidates=candidates,
            candidate_ids_by_descriptor=(
                catalog_build.candidate_ids_by_descriptor
            ),
        )
        descriptor_hit = bool(
            set(descriptor_ids).intersection(oracle_descriptor_ids)
        )
        runtime_rank = rerank_descriptor_candidates_v1(
            question=case.qa.question,
            role=role,
            skeleton=oracle.skeleton,
            selected_descriptor_ids=descriptor_ids,
            catalog_build=catalog_build,
            candidates=candidates,
            intent=intent,
            evidence_context_by_id=context,
            evidence_rank_by_id=evidence_rank_by_id,
            descriptor_priority_step=descriptor_priority_step,
            candidate_local_weight=candidate_local_weight,
        )
        reverse_rank = rerank_descriptor_candidates_v1(
            question=case.qa.question,
            role=role,
            skeleton=oracle.skeleton,
            selected_descriptor_ids=reverse_selection_by_role[role_id],
            catalog_build=reverse_build,
            candidates=tuple(reversed(candidates)),
            intent=intent,
            evidence_context_by_id=reversed_context,
            evidence_rank_by_id=evidence_rank_by_id,
            descriptor_priority_step=descriptor_priority_step,
            candidate_local_weight=candidate_local_weight,
        )
        case_invariant = case_invariant and (
            runtime_rank.candidate_ids == reverse_rank.candidate_ids
        )
        runtime_candidates = _candidate_tuple(
            runtime_rank.candidate_ids,
            candidate_by_id,
        )
        oracle_candidate_ids: tuple[str, ...] = ()
        if oracle_descriptor_ids:
            oracle_rank = rerank_descriptor_candidates_v1(
                question=case.qa.question,
                role=role,
                skeleton=oracle.skeleton,
                selected_descriptor_ids=oracle_descriptor_ids,
                catalog_build=catalog_build,
                candidates=candidates,
                intent=intent,
                evidence_context_by_id=context,
                evidence_rank_by_id=evidence_rank_by_id,
                descriptor_priority_step=descriptor_priority_step,
                candidate_local_weight=candidate_local_weight,
            )
            oracle_candidate_ids = oracle_rank.candidate_ids
        oracle_candidates = _candidate_tuple(
            oracle_candidate_ids,
            candidate_by_id,
        )
        selected_edges += len(runtime_candidates)
        retentions.append(
            {
                "role_id": role_id,
                "descriptor_ids": list(descriptor_ids),
                "oracle_descriptor_ids": list(oracle_descriptor_ids),
                "descriptor_hit_at_4": descriptor_hit,
                "ranked_candidate_ids": list(runtime_rank.candidate_ids),
                "retained_at_4": _target_retained(
                    target,
                    runtime_candidates[:4],
                ),
                "retained_at_8": _target_retained(target, runtime_candidates),
                "oracle_ranked_candidate_ids": list(oracle_candidate_ids),
                "oracle_retained_at_8": _target_retained(
                    target,
                    oracle_candidates,
                ),
            }
        )
    descriptor_complete = all(
        item["descriptor_hit_at_4"] for item in retentions
    )
    candidate_complete = all(item["retained_at_8"] for item in retentions)
    return {
        "case_id": case.id,
        "status": "EVALUATED",
        "route_match": route_match,
        "model_call_count": selection.generation_calls,
        "evidence_role_count": len(oracle.evidence_targets),
        "source_candidate_count": len(candidates),
        "represented_candidate_count": (
            catalog_build.catalog.represented_candidate_count
        ),
        "quarantined_candidate_count": (
            catalog_build.catalog.quarantined_candidate_count
        ),
        "baseline_role_candidate_edges": baseline_edges,
        "selected_role_candidate_edges": selected_edges,
        "descriptor_complete_at_4": descriptor_complete,
        "candidate_complete_at_8": candidate_complete,
        "prompt_chars": prompt_chars,
        "prompt_leakage": prompt_leakage,
        "guard_scan_before_projection": True,
        "input_order_invariant": case_invariant,
        "candidate_identity_preserved": (
            identity_before == evidence_io._candidate_identity(candidates)
            and identity_before
            == evidence_io._candidate_identity(tuple(reverse_candidate_by_id.values()))
        ),
        "catalog_sha256": catalog_build.catalog.catalog_sha256,
        "descriptor_count": catalog_build.catalog.descriptor_count,
        "retention": retentions,
    }


def _summarize(rows, protocol):
    typed = [row for row in rows if row["status"] != "FALLBACK_ROUTED"]
    evaluated = [row for row in typed if row["status"] == "EVALUATED"]
    retentions = [item for row in evaluated for item in row["retention"]]
    role_count = sum(row.get("evidence_role_count", 0) for row in typed)
    source_candidates = sum(
        row.get("source_candidate_count", 0) for row in typed
    )
    represented = sum(
        row.get("represented_candidate_count", 0) for row in typed
    )
    descriptor_hits = sum(item["descriptor_hit_at_4"] for item in retentions)
    candidate_4 = sum(item["retained_at_4"] for item in retentions)
    candidate_8 = sum(item["retained_at_8"] for item in retentions)
    oracle_candidate_8 = sum(
        item["oracle_retained_at_8"] for item in retentions
    )
    conditional_8 = sum(
        item["retained_at_8"]
        for item in retentions
        if item["descriptor_hit_at_4"]
    )
    descriptor_complete = sum(
        row.get("descriptor_complete_at_4", False) for row in typed
    )
    candidate_complete = sum(
        row.get("candidate_complete_at_8", False) for row in typed
    )
    baseline_edges = sum(
        row.get("baseline_role_candidate_edges", 0) for row in typed
    )
    selected_edges = sum(
        row.get("selected_role_candidate_edges", 0) for row in typed
    )
    metrics = {
        "source_candidate_catalog_coverage": represented / source_candidates,
        "oracle_candidate_recall_at_8": oracle_candidate_8 / role_count,
        "descriptor_recall_at_4": descriptor_hits / role_count,
        "descriptor_complete_case_rate_at_4": (
            descriptor_complete / len(typed)
        ),
        "candidate_recall_at_4": candidate_4 / role_count,
        "candidate_recall_at_8": candidate_8 / role_count,
        "candidate_complete_case_rate_at_8": candidate_complete / len(typed),
        "conditional_candidate_retention_at_8": (
            conditional_8 / descriptor_hits if descriptor_hits else 0.0
        ),
        "candidate_edge_reduction_rate": 1 - selected_edges / baseline_edges,
    }
    gates = protocol.progress_gates
    checks = {
        "source_candidate_catalog_coverage": (
            metrics["source_candidate_catalog_coverage"]
            >= gates.min_source_candidate_catalog_coverage
        ),
        "oracle_candidate_recall_at_8": (
            metrics["oracle_candidate_recall_at_8"]
            >= gates.min_oracle_candidate_recall_at_8
        ),
        "descriptor_recall_at_4": (
            metrics["descriptor_recall_at_4"]
            >= gates.min_descriptor_recall_at_4
        ),
        "descriptor_complete_case_rate_at_4": (
            metrics["descriptor_complete_case_rate_at_4"]
            >= gates.min_descriptor_complete_case_rate_at_4
        ),
        "candidate_recall_at_4": (
            metrics["candidate_recall_at_4"]
            >= gates.min_candidate_recall_at_4
        ),
        "candidate_recall_at_8": (
            metrics["candidate_recall_at_8"]
            >= gates.min_candidate_recall_at_8
        ),
        "candidate_complete_case_rate_at_8": (
            metrics["candidate_complete_case_rate_at_8"]
            >= gates.min_candidate_complete_case_rate_at_8
        ),
        "conditional_candidate_retention_at_8": (
            metrics["conditional_candidate_retention_at_8"]
            >= gates.min_conditional_candidate_retention_at_8
        ),
        "candidate_edge_reduction_rate": (
            metrics["candidate_edge_reduction_rate"]
            >= gates.min_candidate_edge_reduction_rate
        ),
        "schema_valid_rate": len(evaluated) == len(typed),
        "zero_model_calls": sum(
            row.get("model_call_count", 0) for row in typed
        ) == 0,
        "zero_forbidden_field_leakage": not any(
            row.get("prompt_leakage", True) for row in typed
        ),
        "candidate_identity_preservation": all(
            row.get("candidate_identity_preserved", False)
            for row in evaluated
        ),
        "input_order_invariance": all(
            row.get("input_order_invariant", False) for row in evaluated
        ),
        "guard_scan_before_projection": all(
            row.get("guard_scan_before_projection", False)
            for row in evaluated
        ),
        "serving_route_disabled": True,
    }
    long_term = protocol.long_term_targets
    long_term_checks = {
        "descriptor_recall_at_4": (
            metrics["descriptor_recall_at_4"]
            >= long_term.min_descriptor_recall_at_4
        ),
        "candidate_recall_at_8": (
            metrics["candidate_recall_at_8"]
            >= long_term.min_candidate_recall_at_8
        ),
        "candidate_complete_case_rate_at_8": (
            metrics["candidate_complete_case_rate_at_8"]
            >= long_term.min_candidate_complete_case_rate_at_8
        ),
    }
    return {
        "typed_case_count": len(typed),
        "failed_typed_case_count": len(typed) - len(evaluated),
        "role_count": role_count,
        "source_candidate_count": source_candidates,
        "represented_candidate_count": represented,
        "max_descriptor_prompt_chars_observed": max(
            (row.get("prompt_chars", 0) for row in evaluated),
            default=0,
        ),
        "model_call_count": sum(
            row.get("model_call_count", 0) for row in typed
        ),
        "runtime_route_accuracy": sum(row["route_match"] for row in rows)
        / len(rows),
        **metrics,
        "progress_gate_checks": checks,
        "progress_decision": (
            "E8_DEVELOPMENT_PROGRESS_GATE_PASSED"
            if all(checks.values())
            else "E8_DEVELOPMENT_PROGRESS_GATE_FAILED"
        ),
        "long_term_target_checks": long_term_checks,
        "long_term_target_status": (
            "LONG_TERM_TARGETS_MET"
            if all(long_term_checks.values())
            else "LONG_TERM_TARGETS_NOT_MET"
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run E8 retrievable-descriptor and candidate-reranker audit."
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
    parser.add_argument(
        "--descriptor-priority-step",
        type=float,
        default=0.0,
        choices=(0.0, 1.0, 2.0, 4.0, 8.0),
    )
    parser.add_argument(
        "--candidate-local-weight",
        type=float,
        default=1.0,
        choices=(0.0, 1.0),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol, protocol_sha256 = load_retrievable_descriptor_protocol_v1(
        args.protocol.resolve()
    )
    catalog_protocol, catalog_protocol_sha256 = (
        load_descriptor_catalog_protocol_v1(args.catalog_protocol.resolve())
    )
    catalog_upper_bound_path = args.catalog_upper_bound.resolve()
    retriever_v2_path = args.retriever_v2.resolve()
    if (
        catalog_protocol_sha256
        != protocol.source_e7_catalog_protocol_sha256
        or evidence_io._sha256(catalog_upper_bound_path)
        != protocol.source_e7_catalog_upper_bound_v2_sha256
        or evidence_io._sha256(retriever_v2_path)
        != protocol.source_e7_retriever_v2_result_sha256
    ):
        raise ValueError("E8 source evidence does not match frozen protocol")

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
        or case_ids_sha256([row.case_id for row in source_rows])
        != protocol.calibration_case_ids_sha256
    ):
        raise ValueError("E8 calibration cohort is invalid")

    selector = DeterministicFinQADescriptorRetrieverV5()
    guard = RetrievedContentGuard()
    rows = [
        _evaluate_case(
            case=cases_by_id[source_row.case_id],
            source_row=source_row,
            selector=selector,
            guard=guard,
            forbidden_fields=catalog_protocol.forbidden_prompt_fields,
            descriptor_priority_step=args.descriptor_priority_step,
            candidate_local_weight=args.candidate_local_weight,
        )
        for source_row in source_rows
    ]
    summary = _summarize(rows, protocol)
    private_dir = args.private_output.resolve()
    details_bytes = b"".join(evidence_io._canonical_bytes(row) for row in rows)
    evidence_io._write_once(private_dir / "details.jsonl", details_bytes)
    manifest = {
        "schema_version": "finqa_retrievable_descriptor_manifest_v1",
        "run_id": private_dir.name,
        "protocol_sha256": protocol_sha256,
        "catalog_protocol_sha256": catalog_protocol_sha256,
        "catalog_upper_bound_sha256": evidence_io._sha256(
            catalog_upper_bound_path
        ),
        "retriever_v2_result_sha256": evidence_io._sha256(retriever_v2_path),
        "source_details_sha256": evidence_io._sha256(source_details),
        "details_sha256": evidence_io._sha256(private_dir / "details.jsonl"),
        "case_count": len(rows),
        "model_call_count": summary["model_call_count"],
        "descriptor_priority_step": args.descriptor_priority_step,
        "candidate_local_weight": args.candidate_local_weight,
    }
    evidence_io._write_once(
        private_dir / "manifest.json",
        evidence_io._canonical_bytes(manifest),
    )
    baseline = protocol.baseline.model_dump(mode="json")
    comparable_metrics = tuple(baseline)
    public = {
        "claim": "DISCLOSED_DEVELOPMENT_RETRIEVABLE_DESCRIPTOR_CALIBRATION",
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "source_e7_catalog_protocol_sha256": catalog_protocol_sha256,
        "source_e7_catalog_upper_bound_v2_sha256": evidence_io._sha256(
            catalog_upper_bound_path
        ),
        "source_e7_retriever_v2_result_sha256": evidence_io._sha256(
            retriever_v2_path
        ),
        "private_manifest_sha256": evidence_io._sha256(
            private_dir / "manifest.json"
        ),
        "private_details_sha256": evidence_io._sha256(
            private_dir / "details.jsonl"
        ),
        "case_count": len(rows),
        "descriptor_priority_step": args.descriptor_priority_step,
        "candidate_local_weight": args.candidate_local_weight,
        **summary,
        "baseline": baseline,
        "delta_vs_e7_baseline": {
            metric: summary[metric] - baseline[metric]
            for metric in comparable_metrics
        },
        "internal_validation_status": protocol.internal_validation_status,
        "frozen_test_status": protocol.frozen_test_status,
        "serving_route_status": "DISABLED",
        "implementation_sha256": {
            relative: evidence_io._sha256(REPOSITORY_ROOT / relative)
            for relative in IMPLEMENTATION_FILES
        },
        "non_claims": list(protocol.non_claims),
    }
    evidence_io._write_once(
        args.output.resolve(),
        evidence_io._canonical_bytes(public),
    )
    print(json.dumps(public, indent=2, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
