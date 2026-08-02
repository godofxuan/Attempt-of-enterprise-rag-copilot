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
from app.external_datasets.finqa_descriptor_catalog_protocol_v1 import (
    load_descriptor_catalog_protocol_v1,
)
from app.external_datasets.finqa_descriptor_selector_protocol_v1 import (
    load_descriptor_selector_protocol_v1,
)
from app.external_datasets.finqa_descriptor_selector_v1 import (
    LocalFinQADescriptorSelectorV1,
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
from app.external_datasets.finqa_safe_descriptor_catalog_v1 import (
    catalog_prompt_payload_v1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v2 import (
    build_contextual_safe_descriptor_catalog_v2,
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
from scripts import audit_finqa_role_query_planner_llm_v1 as live_io
from scripts import audit_finqa_role_query_planner_v1 as evidence_io


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_descriptor_selector_protocol_v1.json"
)
DEFAULT_CATALOG_PROTOCOL = catalog_audit.DEFAULT_PROTOCOL
DEFAULT_CATALOG_UPPER_BOUND = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_descriptor_catalog_upper_bound_public_v2.json"
)
DEFAULT_E5_RUN = evidence_io.DEFAULT_E5_RUN
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_descriptor_selector_live_public_v1.json"
)
DEFAULT_PRIVATE_OUTPUT = (
    DEFAULT_PRIVATE_ROOT
    / "descriptor_selector_live_audits"
    / "finqa-descriptor-selector-live-qwen3-8b-v1"
)
COMPARISON_EVIDENCE = {
    "deterministic_question_only_v2": (
        REPOSITORY_ROOT
        / "docs/external_datasets/evidence/finqa_role_query_planner_v2_calibration_public_v1.json"
    ),
    "free_query_llm_v1": (
        REPOSITORY_ROOT
        / "docs/external_datasets/evidence/finqa_role_query_planner_llm_v1_calibration_public_v1.json"
    ),
}
IMPLEMENTATION_FILES = (
    "app/external_datasets/finqa_safe_descriptor_catalog_v1.py",
    "app/external_datasets/finqa_safe_descriptor_catalog_v2.py",
    "app/external_datasets/finqa_descriptor_selector_v1.py",
    "app/external_datasets/finqa_descriptor_selector_protocol_v1.py",
    "scripts/audit_finqa_descriptor_selector_live_v1.py",
)


def _evaluate_case(*, case, source_row, selector, guard, forbidden_fields):
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
    units = {unit.unit_id: unit for unit in build_finqa_evidence_units(case)}
    context = {
        unit_id: units[unit_id].text
        for unit_id in admission.admitted_unit_ids
    }
    identity_before = evidence_io._candidate_identity(candidates)
    catalog_build = build_contextual_safe_descriptor_catalog_v2(
        candidates=candidates,
        admitted_evidence_ids=admitted_ids,
        evidence_context_by_id=context,
        guard=guard,
    )
    reverse_build = build_contextual_safe_descriptor_catalog_v2(
        candidates=tuple(reversed(candidates)),
        admitted_evidence_ids=admitted_ids,
        evidence_context_by_id=context,
        guard=guard,
    )
    prompt_payload = catalog_prompt_payload_v1(catalog_build.catalog)
    prompt_leakage = catalog_audit._prompt_has_forbidden_fields(
        prompt_payload,
        forbidden_fields,
    )
    baseline_edges = len(candidates) * len(oracle.evidence_targets)
    try:
        result = selector.select(
            question=case.qa.question,
            skeleton=oracle.skeleton,
            catalog=catalog_build.catalog,
        )
    except Exception as error:
        return {
            "case_id": case.id,
            "status": "SELECTOR_ERROR",
            "reason": f"{type(error).__name__}:{error}",
            "route_match": route_match,
            "model_request_count": 1,
            "latency_ms": 0.0,
            "evidence_role_count": len(oracle.evidence_targets),
            "baseline_role_candidate_edges": baseline_edges,
            "selected_role_candidate_edges": 0,
            "prompt_leakage": prompt_leakage,
            "retention": [],
        }
    intent = extract_financial_question_intent_v2(case.qa.question)
    role_by_id = {role.role_id: role for role in oracle.skeleton.roles}
    target_by_id = {
        target.role_id: target for target in oracle.evidence_targets
    }
    retentions = []
    selected_edges = 0
    for selection in result.selections.selections:
        selected_ids = set(
            catalog_build.candidate_ids_for_descriptors(
                selection.descriptor_ids
            )
        )
        ranked = catalog_audit._rank_selected_candidates(
            question=case.qa.question,
            role=role_by_id[selection.role_id],
            skeleton=oracle.skeleton,
            candidates=candidates,
            selected_candidate_ids=selected_ids,
            intent=intent,
            context=context,
        )
        selected_edges += len(ranked)
        target = target_by_id[selection.role_id]
        retentions.append(
            {
                "role_id": selection.role_id,
                "descriptor_ids": list(selection.descriptor_ids),
                "ranked_candidate_ids": [item.candidate_id for item in ranked],
                "retained_at_4": _target_retained(target, ranked[:4]),
                "retained_at_8": _target_retained(target, ranked),
            }
        )
    return {
        "case_id": case.id,
        "status": "EVALUATED",
        "route_match": route_match,
        "model_request_count": result.generation_calls,
        "latency_ms": result.latency_ms,
        "evidence_role_count": len(oracle.evidence_targets),
        "baseline_role_candidate_edges": baseline_edges,
        "selected_role_candidate_edges": selected_edges,
        "complete_at_8": all(item["retained_at_8"] for item in retentions),
        "prompt_leakage": prompt_leakage,
        "input_order_invariant": (
            catalog_build.catalog == reverse_build.catalog
            and catalog_build.candidate_ids_by_descriptor
            == reverse_build.candidate_ids_by_descriptor
        ),
        "candidate_identity_preserved": (
            identity_before == evidence_io._candidate_identity(candidates)
        ),
        "catalog_sha256": catalog_build.catalog.catalog_sha256,
        "descriptor_count": catalog_build.catalog.descriptor_count,
        "selections": result.selections.model_dump(mode="json"),
        "retention": retentions,
    }


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
        "model_request_budget": requests <= len(typed),
        "zero_prompt_leakage": not any(
            row.get("prompt_leakage", True) for row in typed
        ),
        "zero_non_enum_output": len(evaluated) == len(typed),
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
            "LIVE_DESCRIPTOR_SELECTOR_GATE_PASSED"
            if all(checks.values())
            else "LIVE_DESCRIPTOR_SELECTOR_GATE_FAILED"
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run resumable E7 local descriptor selector calibration."
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
    parser.add_argument("--e5-run", type=Path, default=DEFAULT_E5_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--private-output", type=Path, default=DEFAULT_PRIVATE_OUTPUT
    )
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol, protocol_sha256 = load_descriptor_selector_protocol_v1(
        args.protocol.resolve()
    )
    catalog_protocol, catalog_protocol_sha256 = (
        load_descriptor_catalog_protocol_v1(args.catalog_protocol.resolve())
    )
    upper_bound_path = args.catalog_upper_bound.resolve()
    upper_bound = json.loads(upper_bound_path.read_text(encoding="ascii"))
    if (
        catalog_protocol_sha256 != protocol.source_catalog_protocol_sha256
        or evidence_io._sha256(upper_bound_path)
        != protocol.source_catalog_upper_bound_v2_sha256
        or upper_bound["decision"] != "ORACLE_CATALOG_GATE_PASSED"
    ):
        raise ValueError("live descriptor selector source evidence is invalid")
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
        or case_ids_sha256(expected_ids) != protocol.calibration_case_ids_sha256
    ):
        raise ValueError("live descriptor selector cohort is invalid")
    private_dir = args.private_output.resolve()
    journal = private_dir / "journal.jsonl"
    rows = live_io._load_journal(journal)
    if [row["case_id"] for row in rows] != expected_ids[: len(rows)]:
        raise ValueError("live descriptor selector journal is not a cohort prefix")
    selector = LocalFinQADescriptorSelectorV1(
        model=protocol.model,
        timeout_seconds=args.timeout_seconds,
    )
    guard = RetrievedContentGuard()
    for index, source_row in enumerate(
        source_rows[len(rows) :], start=len(rows) + 1
    ):
        row = _evaluate_case(
            case=cases_by_id[source_row.case_id],
            source_row=source_row,
            selector=selector,
            guard=guard,
            forbidden_fields=catalog_protocol.forbidden_prompt_fields,
        )
        row["model"] = protocol.model
        row["model_digest"] = protocol.model_digest
        live_io._append_journal(journal, row)
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
    summary = _summarize(rows, protocol)
    details_bytes = b"".join(evidence_io._canonical_bytes(row) for row in rows)
    evidence_io._write_once(private_dir / "details.jsonl", details_bytes)
    manifest = {
        "schema_version": "finqa_descriptor_selector_live_manifest_v1",
        "run_id": private_dir.name,
        "protocol_sha256": protocol_sha256,
        "catalog_protocol_sha256": catalog_protocol_sha256,
        "catalog_upper_bound_sha256": evidence_io._sha256(upper_bound_path),
        "source_details_sha256": evidence_io._sha256(source_details),
        "details_sha256": evidence_io._sha256(private_dir / "details.jsonl"),
        "case_count": len(rows),
        "model": protocol.model,
        "model_digest": protocol.model_digest,
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
        "claim": "DISCLOSED_DEVELOPMENT_LOCAL_DESCRIPTOR_SELECTION_CALIBRATION",
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "catalog_protocol_sha256": catalog_protocol_sha256,
        "catalog_upper_bound_sha256": evidence_io._sha256(upper_bound_path),
        "private_manifest_sha256": evidence_io._sha256(
            private_dir / "manifest.json"
        ),
        "private_details_sha256": evidence_io._sha256(
            private_dir / "details.jsonl"
        ),
        "case_count": len(rows),
        "model": protocol.model,
        "model_digest": protocol.model_digest,
        **summary,
        "delta_vs_question_only_baselines": {
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
