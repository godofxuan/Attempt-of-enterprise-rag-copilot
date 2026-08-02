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
from app.external_datasets.finqa_numeric_evidence_v2 import (
    NumericCandidateV2,
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
    EvidenceRoleTargetV2,
    _source_bound_constant_ids,
    _target_retained,
    build_oracle_semantic_program_v2,
)
from app.external_datasets.finqa_role_compatibility_v2 import (
    _expected_period_v2,
    hard_compatible_candidates_for_role_v2,
)
from app.external_datasets.finqa_semantic_calibration_run import (
    FinQASemanticPlanningCase,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)
from app.security.retrieved_content import RetrievedContentGuard


DEFAULT_E5_RUN = (
    DEFAULT_PRIVATE_ROOT
    / "semantic_planning_calibration_runs"
    / "finqa-semantic-planning-calibration-v1"
)


def _candidate_payload(
    candidate: NumericCandidateV2,
    *,
    rank: int,
    score: float,
    reasons: tuple[str, ...],
) -> dict[str, object]:
    return {
        "rank": rank,
        "score": score,
        "score_reasons": reasons,
        "candidate_id": candidate.candidate_id,
        "evidence_id": candidate.evidence_id,
        "value": str(candidate.normalized_value),
        "unit": candidate.unit,
        "scale": candidate.scale,
        "period": candidate.period,
        "fiscal_year": candidate.fiscal_year,
        "metric": candidate.metric,
        "entity": candidate.entity,
        "row_header": candidate.row_header,
        "column_header": candidate.column_header,
    }


def _rank_role(
    *,
    question: str,
    role,
    skeleton,
    target: EvidenceRoleTargetV2,
    candidates: tuple[NumericCandidateV2, ...],
    intent,
    context: dict[str, str],
) -> dict[str, object]:
    expected_period = _expected_period_v2(
        question=question,
        role=role,
        intent=intent,
    )
    question_tokens = _tokens(question)
    anchor_tokens = _role_anchor_tokens(question, role.semantic_role)
    evidence_rank = {
        evidence_id: index for index, evidence_id in enumerate(context)
    }
    hard = hard_compatible_candidates_for_role_v2(
        role=role,
        skeleton=skeleton,
        candidates=candidates,
        intent=intent,
        question=question,
    )
    scored = []
    for candidate in hard:
        score, reasons = _candidate_score(
            question_tokens=question_tokens,
            anchor_tokens=anchor_tokens,
            candidate=candidate,
            expected_period=expected_period,
            evidence_context=context.get(candidate.evidence_id),
            evidence_rank=evidence_rank.get(
                candidate.evidence_id,
                len(evidence_rank),
            ),
        )
        scored.append((score, candidate.candidate_id, candidate, reasons))
    scored.sort(key=lambda item: (-item[0], item[1]))
    target_rows = [
        (rank, item)
        for rank, item in enumerate(scored, start=1)
        if _target_retained(target, (item[2],))
    ]
    best_rank = target_rows[0][0] if target_rows else None
    return {
        "role_id": role.role_id,
        "semantic_role": role.semantic_role,
        "period_role": role.period_role,
        "expected_period": expected_period,
        "target_value": str(target.value),
        "hard_candidate_count": len(hard),
        "best_target_rank": best_rank,
        "target_candidates": [
            _candidate_payload(
                item[2],
                rank=rank,
                score=item[0],
                reasons=item[3],
            )
            for rank, item in target_rows[:4]
        ],
        "top_candidates": [
            _candidate_payload(
                item[2],
                rank=rank,
                score=item[0],
                reasons=item[3],
            )
            for rank, item in enumerate(scored[:8], start=1)
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Explain missed Gate E6-v2 evidence-role rankings."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_SOURCE_ROOT / "dataset" / "dev.json",
    )
    parser.add_argument("--e5-run", type=Path, default=DEFAULT_E5_RUN)
    parser.add_argument("--case-id")
    parser.add_argument(
        "--include-retained",
        action="store_true",
        help="Include roles already retained in the top eight.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cases, _ = load_finqa_split(
        args.dataset.resolve(),
        expected_sha256=FINQA_DEV_SHA256,
    )
    cases_by_id = {case.id: case for case in cases}
    source_rows = tuple(
        FinQASemanticPlanningCase.model_validate(json.loads(line))
        for line in (args.e5_run.resolve() / "details.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    )
    guard = RetrievedContentGuard()
    output = []
    for source_row in source_rows:
        if args.case_id is not None and source_row.case_id != args.case_id:
            continue
        case = cases_by_id[source_row.case_id]
        oracle = build_oracle_semantic_program_v2(
            question=case.qa.question,
            program=case.qa.program,
            source_bound_constant_ids=_source_bound_constant_ids(case),
        )
        if oracle.skeleton is None:
            continue
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
        intent = extract_financial_question_intent_v2(case.qa.question)
        target_by_role = {
            target.role_id: target for target in oracle.evidence_targets
        }
        roles = [
            _rank_role(
                question=case.qa.question,
                role=role,
                skeleton=oracle.skeleton,
                target=target_by_role[role.role_id],
                candidates=candidates,
                intent=intent,
                context=context,
            )
            for role in oracle.skeleton.roles
        ]
        selected = (
            roles
            if args.include_retained
            else [
                role
                for role in roles
                if role["best_target_rank"] is None
                or role["best_target_rank"] > 8
            ]
        )
        if selected:
            output.append(
                {
                    "case_id": case.id,
                    "question": case.qa.question,
                    "program": case.qa.program,
                    "roles": selected,
                }
            )
    print(json.dumps(output, indent=2, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
