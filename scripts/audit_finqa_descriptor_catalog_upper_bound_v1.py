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
from app.external_datasets.finqa_descriptor_catalog_protocol_v1 import (
    load_descriptor_catalog_protocol_v1,
)
from app.external_datasets.finqa_numeric_evidence_v2 import (
    admit_finqa_numeric_evidence_closure_v2,
    expand_finqa_numeric_evidence_v2,
    extract_finqa_numeric_candidates_v2,
)
from app.external_datasets.finqa_role_compatibility import (
    _candidate_score,
    _role_anchor_tokens,
    _tokens,
)
from app.external_datasets.finqa_role_compatibility_audit_v2 import (
    _source_bound_constant_ids,
    _target_retained,
    build_oracle_semantic_program_v2,
)
from app.external_datasets.finqa_role_compatibility_v2 import (
    _expected_period_v2,
    hard_compatible_candidates_for_role_v2,
    route_finqa_numeric_capability,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v1 import (
    build_safe_descriptor_catalog_v1,
    catalog_prompt_payload_v1,
)
from app.external_datasets.finqa_semantic_calibration_run import (
    FinQASemanticPlanningCase,
)
from app.external_datasets.finqa_typed_calibration import case_ids_sha256
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)
from app.security.retrieved_content import RetrievedContentGuard
from scripts import audit_finqa_role_query_planner_v1 as evidence_io


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_descriptor_catalog_protocol_v1.json"
)
DEFAULT_E5_RUN = evidence_io.DEFAULT_E5_RUN
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_descriptor_catalog_upper_bound_public_v1.json"
)
DEFAULT_PRIVATE_OUTPUT = (
    DEFAULT_PRIVATE_ROOT
    / "descriptor_catalog_upper_bound_audits"
    / "finqa-descriptor-catalog-upper-bound-v1"
)
SOURCE_FILES = {
    "e6_v3_protocol": (
        REPOSITORY_ROOT
        / "docs/external_datasets/evidence/finqa_role_compatibility_protocol_v3.json"
    ),
    "e6_v3_upper_bound": (
        REPOSITORY_ROOT
        / "docs/external_datasets/evidence/finqa_role_compatibility_v3_upper_bound_public_v1.json"
    ),
    "deterministic_v2": (
        REPOSITORY_ROOT
        / "docs/external_datasets/evidence/finqa_role_query_planner_v2_calibration_public_v1.json"
    ),
    "local_llm_v1": (
        REPOSITORY_ROOT
        / "docs/external_datasets/evidence/finqa_role_query_planner_llm_v1_calibration_public_v1.json"
    ),
}
IMPLEMENTATION_FILES = (
    "app/external_datasets/finqa_safe_descriptor_catalog_v1.py",
    "app/external_datasets/finqa_descriptor_catalog_protocol_v1.py",
    "scripts/audit_finqa_descriptor_catalog_upper_bound_v1.py",
)


def _sha256(path: Path) -> str:
    return evidence_io._sha256(path)


def _canonical_bytes(payload: object) -> bytes:
    return evidence_io._canonical_bytes(payload)


def _write_once(path: Path, payload: bytes) -> None:
    evidence_io._write_once(path, payload)


def _prompt_has_forbidden_fields(payload: dict, forbidden: tuple[str, ...]) -> bool:
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    return any(f'"{field}"' in serialized for field in forbidden)


def _oracle_descriptor_ids(
    *,
    target,
    candidates,
    candidate_ids_by_descriptor: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    matching_ids = {
        candidate.candidate_id
        for candidate in candidates
        if _target_retained(target, (candidate,))
    }
    selected = [
        descriptor_id
        for descriptor_id, candidate_ids in candidate_ids_by_descriptor.items()
        if matching_ids.intersection(candidate_ids)
    ]
    selected.sort(
        key=lambda descriptor_id: (
            len(candidate_ids_by_descriptor[descriptor_id]),
            descriptor_id,
        )
    )
    return tuple(selected[:4])


def _rank_selected_candidates(
    *,
    question: str,
    role,
    skeleton,
    candidates,
    selected_candidate_ids: set[str],
    intent,
    context,
):
    expected_period = _expected_period_v2(
        question=question,
        role=role,
        intent=intent,
    )
    hard = hard_compatible_candidates_for_role_v2(
        role=role,
        skeleton=skeleton,
        candidates=candidates,
        intent=intent,
        question=question,
    )
    evidence_rank = {
        evidence_id: index for index, evidence_id in enumerate(context)
    }
    scored = []
    for candidate in hard:
        if candidate.candidate_id not in selected_candidate_ids:
            continue
        score, _ = _candidate_score(
            question_tokens=_tokens(question),
            anchor_tokens=_role_anchor_tokens(question, role.semantic_role),
            candidate=candidate,
            expected_period=expected_period,
            evidence_context=context.get(candidate.evidence_id),
            evidence_rank=evidence_rank.get(candidate.evidence_id, len(context)),
        )
        scored.append((score, candidate.candidate_id, candidate))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(item[2] for item in scored[:8])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run E7 safe descriptor catalog oracle upper bound."
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
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
    protocol, protocol_sha256 = load_descriptor_catalog_protocol_v1(
        args.protocol.resolve()
    )
    expected_source_hashes = {
        "e6_v3_protocol": protocol.source_gate_e6_v3_protocol_sha256,
        "e6_v3_upper_bound": protocol.source_gate_e6_v3_upper_bound_sha256,
        "deterministic_v2": protocol.source_deterministic_v2_sha256,
        "local_llm_v1": protocol.source_local_llm_v1_sha256,
    }
    actual_source_hashes = {
        name: _sha256(path) for name, path in SOURCE_FILES.items()
    }
    if actual_source_hashes != expected_source_hashes:
        raise ValueError("E7 source evidence does not match frozen protocol")

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
        raise ValueError("E7 calibration cohort is invalid")

    guard = RetrievedContentGuard()
    rows = []
    typed_count = route_matches = failures = 0
    role_count = retained_4 = retained_8 = complete_8 = 0
    source_candidates = represented = quarantined = 0
    baseline_edges = selected_edges = 0
    prompt_budget_valid = schema_valid = invariance = identity = 0
    leakage_count = empty_catalog_count = 0
    for source_row in source_rows:
        case = cases_by_id[source_row.case_id]
        oracle = build_oracle_semantic_program_v2(
            question=case.qa.question,
            program=case.qa.program,
            source_bound_constant_ids=_source_bound_constant_ids(case),
        )
        runtime_route = route_finqa_numeric_capability(case.qa.question)
        route_matches += runtime_route == oracle.capability_route
        if oracle.skeleton is None:
            rows.append({"case_id": case.id, "status": "FALLBACK_ROUTED"})
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
        source_candidates += len(candidates)
        identity_before = evidence_io._candidate_identity(candidates)
        try:
            catalog_build = build_safe_descriptor_catalog_v1(
                candidates=candidates,
                admitted_evidence_ids=admitted_ids,
                guard=guard,
            )
            reversed_build = build_safe_descriptor_catalog_v1(
                candidates=tuple(reversed(candidates)),
                admitted_evidence_ids=admitted_ids,
                guard=guard,
            )
        except ValueError as error:
            failures += 1
            empty_catalog_count += 1
            role_count += len(oracle.evidence_targets)
            baseline_edges += len(candidates) * len(oracle.evidence_targets)
            rows.append(
                {
                    "case_id": case.id,
                    "status": "CATALOG_ERROR",
                    "reason": str(error),
                }
            )
            continue
        schema_valid += 1
        invariance += (
            catalog_build.catalog == reversed_build.catalog
            and catalog_build.candidate_ids_by_descriptor
            == reversed_build.candidate_ids_by_descriptor
        )
        identity += identity_before == evidence_io._candidate_identity(candidates)
        represented += catalog_build.catalog.represented_candidate_count
        quarantined += catalog_build.catalog.quarantined_candidate_count
        prompt_payload = catalog_prompt_payload_v1(catalog_build.catalog)
        prompt_chars = len(json.dumps(prompt_payload, ensure_ascii=True))
        prompt_budget_valid += prompt_chars <= protocol.max_descriptor_prompt_chars
        leakage = _prompt_has_forbidden_fields(
            prompt_payload,
            protocol.forbidden_prompt_fields,
        )
        leakage_count += leakage
        units = {
            unit.unit_id: unit for unit in build_finqa_evidence_units(case)
        }
        context = {
            unit_id: units[unit_id].text
            for unit_id in admission.admitted_unit_ids
        }
        intent = extract_financial_question_intent_v2(case.qa.question)
        target_by_role = {
            target.role_id: target for target in oracle.evidence_targets
        }
        case_complete = True
        role_rows = []
        for role in oracle.skeleton.roles:
            target = target_by_role[role.role_id]
            descriptor_ids = _oracle_descriptor_ids(
                target=target,
                candidates=candidates,
                candidate_ids_by_descriptor=(
                    catalog_build.candidate_ids_by_descriptor
                ),
            )
            selected_ids = set(
                catalog_build.candidate_ids_for_descriptors(descriptor_ids)
            ) if descriptor_ids else set()
            ranked = _rank_selected_candidates(
                question=case.qa.question,
                role=role,
                skeleton=oracle.skeleton,
                candidates=candidates,
                selected_candidate_ids=selected_ids,
                intent=intent,
                context=context,
            )
            at_4 = _target_retained(target, ranked[:4])
            at_8 = _target_retained(target, ranked)
            role_count += 1
            retained_4 += at_4
            retained_8 += at_8
            case_complete = case_complete and at_8
            selected_edges += len(ranked)
            role_rows.append(
                {
                    "role_id": role.role_id,
                    "oracle_descriptor_ids": list(descriptor_ids),
                    "ranked_candidate_ids": [
                        candidate.candidate_id for candidate in ranked
                    ],
                    "retained_at_4": at_4,
                    "retained_at_8": at_8,
                }
            )
        complete_8 += case_complete
        baseline_edges += len(candidates) * len(oracle.evidence_targets)
        rows.append(
            {
                "case_id": case.id,
                "status": "EVALUATED",
                "catalog_sha256": catalog_build.catalog.catalog_sha256,
                "descriptor_count": catalog_build.catalog.descriptor_count,
                "prompt_chars": prompt_chars,
                "prompt_leakage": leakage,
                "complete_at_8": case_complete,
                "roles": role_rows,
            }
        )

    coverage = represented / source_candidates
    quarantine_rate = quarantined / source_candidates
    recall_4 = retained_4 / role_count
    recall_8 = retained_8 / role_count
    complete_rate = complete_8 / typed_count
    edge_reduction = 1 - selected_edges / baseline_edges
    gates = protocol.gates
    checks = {
        "source_candidate_catalog_coverage": (
            coverage >= gates.min_source_candidate_catalog_coverage
        ),
        "oracle_role_recall_at_4": recall_4 >= gates.min_oracle_role_recall_at_4,
        "oracle_role_recall_at_8": recall_8 >= gates.min_oracle_role_recall_at_8,
        "oracle_complete_typed_case_rate_at_8": (
            complete_rate >= gates.min_oracle_complete_typed_case_rate_at_8
        ),
        "candidate_edge_reduction_rate": (
            edge_reduction >= gates.min_candidate_edge_reduction_rate
        ),
        "descriptor_schema_valid_rate": schema_valid == typed_count,
        "empty_catalog_rate": empty_catalog_count == 0,
        "quarantined_descriptor_candidate_rate": (
            quarantine_rate <= gates.max_quarantined_descriptor_candidate_rate
        ),
        "descriptor_prompt_budget": prompt_budget_valid == typed_count,
        "zero_forbidden_prompt_field_leakage": leakage_count == 0,
        "candidate_identity_preservation": identity == typed_count,
        "input_order_invariance": invariance == typed_count,
        "guard_scan_before_prompt": True,
        "serving_route_disabled": True,
    }
    decision = (
        "ORACLE_CATALOG_GATE_PASSED"
        if failures == 0 and all(checks.values())
        else "ORACLE_CATALOG_GATE_FAILED"
    )
    details_bytes = b"".join(_canonical_bytes(row) for row in rows)
    private_dir = args.private_output.resolve()
    _write_once(private_dir / "details.jsonl", details_bytes)
    manifest = {
        "schema_version": "finqa_descriptor_catalog_upper_bound_manifest_v1",
        "run_id": private_dir.name,
        "protocol_sha256": protocol_sha256,
        "source_details_sha256": _sha256(source_details),
        "details_sha256": _sha256(private_dir / "details.jsonl"),
        "case_count": len(rows),
        "model_call_count": 0,
    }
    _write_once(private_dir / "manifest.json", _canonical_bytes(manifest))
    public = {
        "claim": "OFFLINE_GOLD_DESCRIPTOR_SELECTION_UPPER_BOUND_ONLY",
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "source_evidence_sha256": actual_source_hashes,
        "private_manifest_sha256": _sha256(private_dir / "manifest.json"),
        "private_details_sha256": _sha256(private_dir / "details.jsonl"),
        "case_count": len(rows),
        "typed_case_count": typed_count,
        "failed_typed_case_count": failures,
        "source_candidate_count": source_candidates,
        "represented_candidate_count": represented,
        "source_candidate_catalog_coverage": coverage,
        "quarantined_candidate_count": quarantined,
        "quarantined_descriptor_candidate_rate": quarantine_rate,
        "role_count": role_count,
        "oracle_role_recall_at_4": recall_4,
        "oracle_role_recall_at_8": recall_8,
        "oracle_complete_typed_case_rate_at_8": complete_rate,
        "candidate_edge_reduction_rate": edge_reduction,
        "runtime_route_accuracy": route_matches / len(rows),
        "gate_checks": checks,
        "decision": decision,
        "model_call_count": 0,
        "serving_route_status": "DISABLED",
        "implementation_sha256": {
            relative: _sha256(REPOSITORY_ROOT / relative)
            for relative in IMPLEMENTATION_FILES
        },
        "non_claims": [
            "not model descriptor-selection quality",
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
