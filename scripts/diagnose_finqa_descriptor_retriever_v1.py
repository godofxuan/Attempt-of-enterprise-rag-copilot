try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
from collections import Counter
from pathlib import Path

from app.external_datasets.finqa import (
    DEFAULT_SOURCE_ROOT,
    FINQA_DEV_SHA256,
    build_finqa_evidence_units,
    load_finqa_split,
)
from app.external_datasets.finqa_descriptor_retriever_v1 import (
    DeterministicFinQADescriptorRetrieverV1,
)
from app.external_datasets.finqa_descriptor_retriever_v2 import (
    DeterministicFinQADescriptorRetrieverV2,
)
from app.external_datasets.finqa_numeric_evidence_v2 import (
    admit_finqa_numeric_evidence_closure_v2,
    expand_finqa_numeric_evidence_v2,
    extract_finqa_numeric_candidates_v2,
)
from app.external_datasets.finqa_role_compatibility import (
    _role_anchor_tokens,
    _tokens,
)
from app.external_datasets.finqa_role_compatibility_audit_v2 import (
    _source_bound_constant_ids,
    build_oracle_semantic_program_v2,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v2 import (
    build_contextual_safe_descriptor_catalog_v2,
)
from app.external_datasets.finqa_semantic_calibration_run import (
    FinQASemanticPlanningCase,
)
from app.security.retrieved_content import RetrievedContentGuard
from scripts import audit_finqa_role_query_planner_v1 as evidence_io


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_E5_RUN = evidence_io.DEFAULT_E5_RUN
DEFAULT_RETRIEVER_DETAILS = (
    REPOSITORY_ROOT
    / ".private/external_datasets/finqa/descriptor_retriever_audits/"
    "finqa-deterministic-descriptor-retriever-v1/details.jsonl"
)
DEFAULT_ORACLE_DETAILS = (
    REPOSITORY_ROOT
    / ".private/external_datasets/finqa/descriptor_catalog_upper_bound_audits/"
    "finqa-descriptor-catalog-upper-bound-v2/details.jsonl"
)


def _jsonl(path: Path) -> tuple[dict[str, object], ...]:
    return tuple(
        json.loads(line)
        for line in path.resolve().read_text(encoding="utf-8").splitlines()
        if line
    )


def _descriptor_text(descriptor) -> str:
    return " ".join(
        value
        for value in (
            descriptor.metric,
            descriptor.entity,
            descriptor.row_header,
            descriptor.column_header,
        )
        if value
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Diagnose deterministic FinQA descriptor misses."
    )
    parser.add_argument("--e5-run", type=Path, default=DEFAULT_E5_RUN)
    parser.add_argument(
        "--retriever-details", type=Path, default=DEFAULT_RETRIEVER_DETAILS
    )
    parser.add_argument(
        "--oracle-details", type=Path, default=DEFAULT_ORACLE_DETAILS
    )
    parser.add_argument(
        "--retriever-version", choices=("v1", "v2"), default="v1"
    )
    parser.add_argument("--max-details", type=int, default=8)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cases, _ = load_finqa_split(
        (DEFAULT_SOURCE_ROOT / "dataset" / "dev.json").resolve(),
        expected_sha256=FINQA_DEV_SHA256,
    )
    cases_by_id = {case.id: case for case in cases}
    source_rows = {
        row.case_id: row
        for row in (
            FinQASemanticPlanningCase.model_validate(json.loads(line))
            for line in (args.e5_run.resolve() / "details.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line
        )
    }
    retriever_rows = {row["case_id"]: row for row in _jsonl(args.retriever_details)}
    oracle_rows = {row["case_id"]: row for row in _jsonl(args.oracle_details)}
    guard = RetrievedContentGuard()
    retriever = (
        DeterministicFinQADescriptorRetrieverV1()
        if args.retriever_version == "v1"
        else DeterministicFinQADescriptorRetrieverV2()
    )
    diagnoses = []
    for case_id, audit_row in retriever_rows.items():
        failed_roles = {
            item["role_id"]: item
            for item in audit_row.get("retention", [])
            if not item["retained_at_8"]
        }
        if not failed_roles:
            continue
        case = cases_by_id[case_id]
        source_row = source_rows[case_id]
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
            case, closure=closure, guard=guard
        )
        admitted_ids = set(admission.admitted_unit_ids)
        candidates = tuple(
            candidate
            for candidate in extract_finqa_numeric_candidates_v2(
                case, admitted_evidence_ids=admitted_ids
            ).candidates
            if candidate.role == "operand"
        )
        units = {unit.unit_id: unit for unit in build_finqa_evidence_units(case)}
        context = {
            unit_id: units[unit_id].text
            for unit_id in admission.admitted_unit_ids
        }
        catalog = build_contextual_safe_descriptor_catalog_v2(
            candidates=candidates,
            admitted_evidence_ids=admitted_ids,
            evidence_context_by_id=context,
            guard=guard,
        ).catalog
        descriptors = {item.descriptor_id: item for item in catalog.descriptors}
        selector_result = retriever.select(
            question=case.qa.question,
            skeleton=oracle.skeleton,
            catalog=catalog,
        )
        ranking_by_role = {
            item.role_id: item.ranked_descriptors
            for item in selector_result.rankings
        }
        oracle_role_by_id = {
            item["role_id"]: item
            for item in oracle_rows[case_id]["roles"]
        }
        skeleton_role_by_id = {
            item.role_id: item for item in oracle.skeleton.roles
        }
        question_tokens = _tokens(case.qa.question)
        for role_id, failed in failed_roles.items():
            role = skeleton_role_by_id[role_id]
            oracle_ids = tuple(
                oracle_role_by_id[role_id]["oracle_descriptor_ids"]
            )
            selected_ids = tuple(failed["descriptor_ids"])
            ranks = {
                rank.descriptor_id: index
                for index, rank in enumerate(
                    ranking_by_role[role_id], start=1
                )
            }
            oracle_texts = tuple(
                _descriptor_text(descriptors[item]) for item in oracle_ids
            )
            oracle_tokens = frozenset().union(
                *(_tokens(text) for text in oracle_texts)
            )
            anchor_tokens = _role_anchor_tokens(
                case.qa.question, role.semantic_role
            )
            oracle_selected = bool(set(oracle_ids) & set(selected_ids))
            if oracle_selected:
                category = "SELECTED_BUT_CANDIDATE_RANKING_MISS"
            elif question_tokens & oracle_tokens:
                category = "LEXICAL_SIGNAL_RANKED_BELOW_TOP4"
            else:
                category = "NO_QUESTION_LEXICAL_SIGNAL"
            diagnoses.append(
                {
                    "case_id": case_id,
                    "role_id": role_id,
                    "semantic_role": role.semantic_role,
                    "question": case.qa.question,
                    "category": category,
                    "oracle_descriptor_ids": oracle_ids,
                    "oracle_descriptor_ranks": {
                        item: ranks[item] for item in oracle_ids
                    },
                    "oracle_descriptor_texts": oracle_texts,
                    "question_overlap_tokens": sorted(
                        question_tokens & oracle_tokens
                    ),
                    "anchor_overlap_tokens": sorted(
                        anchor_tokens & oracle_tokens
                    ),
                    "selected_descriptor_ids": selected_ids,
                }
            )
    categories = Counter(item["category"] for item in diagnoses)
    rank_buckets = Counter(
        (
            "rank_5_to_8"
            if min(item["oracle_descriptor_ranks"].values()) <= 8
            else "rank_after_8"
        )
        for item in diagnoses
    )
    output = {
        "failed_role_count": len(diagnoses),
        "categories": dict(sorted(categories.items())),
        "oracle_rank_buckets": dict(sorted(rank_buckets.items())),
        "diagnoses": diagnoses[: max(0, args.max_details)],
    }
    print(json.dumps(output, indent=2, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
