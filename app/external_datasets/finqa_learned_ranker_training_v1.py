from __future__ import annotations

import hashlib
import json
import re
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.external_datasets.finqa import (
    FinQACase,
    build_finqa_evidence_units,
)
from app.external_datasets.finqa_learned_descriptor_ranker_v1 import (
    BalancedRidgeFitV1,
    build_learned_descriptor_ranker_artifact_v1,
    descriptor_feature_vector_v1,
    fit_balanced_ridge_v1,
)
from app.external_datasets.finqa_learned_ranker_protocol_v1 import (
    FinQALearnedRankerProtocolV1,
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
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    build_retrievable_safe_descriptor_catalog_v3,
)
from app.security.retrieved_content import RetrievedContentGuard


FOLD_ALGORITHM_VERSION = "sha256_weighted_greedy_company_kfold_v1"
_OPERATION = re.compile(r"([a-z_]+)\(")
_COMPANY = re.compile(r"^[A-Z0-9.-]{1,32}$")


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def strings_sha256(values: Sequence[str]) -> str:
    normalized = sorted(values)
    if not normalized or len(normalized) != len(set(normalized)):
        raise ValueError("hashed string collection must be non-empty and unique")
    return hashlib.sha256(_canonical_bytes(normalized)).hexdigest()


def finqa_company_id(filename: str) -> str:
    normalized = filename.replace("\\", "/")
    parts = normalized.split("/")
    if (
        len(parts) < 3
        or any(part in {"", ".", ".."} for part in parts)
        or not _COMPANY.fullmatch(parts[0])
    ):
        raise ValueError("FinQA filename has no safe company group")
    return parts[0]


def normalized_question(question: str) -> str:
    result = " ".join(question.casefold().split())
    if not result or len(result) > 2_000:
        raise ValueError("FinQA question is outside training budget")
    return result


def is_supported_training_case(
    case: FinQACase,
    *,
    supported_operations: Sequence[str],
    max_program_steps: int,
) -> bool:
    operations = tuple(_OPERATION.findall(case.qa.program))
    return (
        bool(operations)
        and len(operations) <= max_program_steps
        and set(operations).issubset(supported_operations)
    )


def assign_company_folds_v1(
    case_count_by_company: Mapping[str, int],
    *,
    fold_count: int,
    seed: str,
) -> dict[str, int]:
    if (
        not case_count_by_company
        or fold_count < 2
        or len(case_count_by_company) < fold_count
        or not seed
        or any(
            not _COMPANY.fullmatch(company) or count < 1
            for company, count in case_count_by_company.items()
        )
    ):
        raise ValueError("company fold inputs are invalid")
    ordered = sorted(
        case_count_by_company,
        key=lambda company: (
            -case_count_by_company[company],
            hashlib.sha256(f"{seed}\0{company}".encode("ascii")).hexdigest(),
            company,
        ),
    )
    fold_rows = [0] * fold_count
    fold_groups = [0] * fold_count
    assignment: dict[str, int] = {}
    for company in ordered:
        fold_index = min(
            range(fold_count),
            key=lambda index: (fold_rows[index], fold_groups[index], index),
        )
        assignment[company] = fold_index
        fold_rows[fold_index] += case_count_by_company[company]
        fold_groups[fold_index] += 1
    return assignment


def model_input_unit_ids(case: FinQACase) -> tuple[str, ...]:
    selected: list[str] = []
    for item in case.qa.model_input:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], str)
            or not item[0]
            or not item[1]
        ):
            raise ValueError("FinQA model_input row is malformed")
        if item[0] not in selected:
            selected.append(item[0])
    if not selected or not set(case.qa.gold_inds).issubset(selected):
        raise ValueError("FinQA model_input does not cover train gold evidence")
    return tuple(selected)


@dataclass(frozen=True)
class DescriptorRoleTrainingGroupV1:
    case_id: str
    company_id: str
    role_id: str
    descriptor_ids: tuple[str, ...]
    features: tuple[tuple[float, ...], ...]
    labels: tuple[bool, ...]

    def __post_init__(self) -> None:
        count = len(self.descriptor_ids)
        if (
            not self.case_id
            or not _COMPANY.fullmatch(self.company_id)
            or not self.role_id
            or count == 0
            or len(self.features) != count
            or len(self.labels) != count
            or len(set(self.descriptor_ids)) != count
            or not any(self.labels)
        ):
            raise ValueError("descriptor role training group is invalid")


@dataclass(frozen=True)
class PreparedTrainingCaseV1:
    case_id: str
    company_id: str
    role_groups: tuple[DescriptorRoleTrainingGroupV1, ...]
    source_candidate_count: int
    descriptor_count: int
    normalized_empty_table_cell_count: int


def normalize_empty_table_cells_v1(
    case: FinQACase,
) -> tuple[FinQACase, int]:
    normalized = []
    replacement_count = 0
    for row in case.table:
        normalized_row = []
        for cell in row:
            if cell.strip():
                normalized_row.append(cell)
            else:
                normalized_row.append("N/A")
                replacement_count += 1
        normalized.append(normalized_row)
    if replacement_count == 0:
        return case, 0
    payload = case.model_dump()
    payload["table"] = normalized
    return FinQACase.model_validate(payload), replacement_count


def prepare_training_case_v1(
    case: FinQACase,
    *,
    guard: RetrievedContentGuard,
) -> PreparedTrainingCaseV1:
    extraction_case, normalized_empty_cells = normalize_empty_table_cells_v1(case)
    selected_ids = model_input_unit_ids(case)
    oracle = build_oracle_semantic_program_v2(
        question=case.qa.question,
        program=case.qa.program,
        source_bound_constant_ids=_source_bound_constant_ids(case),
    )
    if oracle.skeleton is None:
        raise ValueError("eligible E9 case did not produce a typed skeleton")
    closure = expand_finqa_numeric_evidence_v2(
        case,
        selected_unit_ids=selected_ids,
    )
    admission = admit_finqa_numeric_evidence_closure_v2(
        case,
        closure=closure,
        guard=guard,
    )
    admitted_ids = set(admission.admitted_unit_ids)
    if not admitted_ids:
        raise ValueError("eligible E9 case has no admitted evidence")
    candidates = tuple(
        candidate
        for candidate in extract_finqa_numeric_candidates_v2(
            extraction_case,
            admitted_evidence_ids=admitted_ids,
        ).candidates
        if candidate.role == "operand"
    )
    units = {unit.unit_id: unit for unit in build_finqa_evidence_units(case)}
    context = {
        unit_id: units[unit_id].text for unit_id in admission.admitted_unit_ids
    }
    catalog_build = build_retrievable_safe_descriptor_catalog_v3(
        candidates=candidates,
        admitted_evidence_ids=admitted_ids,
        evidence_context_by_id=context,
        guard=guard,
    )
    candidate_by_id = {item.candidate_id: item for item in candidates}
    target_by_role = {item.role_id: item for item in oracle.evidence_targets}
    groups: list[DescriptorRoleTrainingGroupV1] = []
    for role in oracle.skeleton.roles:
        target = target_by_role[role.role_id]
        descriptor_ids = tuple(
            item.descriptor_id for item in catalog_build.catalog.descriptors
        )
        labels = tuple(
            any(
                _target_retained(target, (candidate_by_id[candidate_id],))
                for candidate_id in catalog_build.candidate_ids_by_descriptor[
                    descriptor_id
                ]
            )
            for descriptor_id in descriptor_ids
        )
        if not any(labels):
            continue
        features = tuple(
            descriptor_feature_vector_v1(case.qa.question, role, descriptor)
            for descriptor in catalog_build.catalog.descriptors
        )
        groups.append(
            DescriptorRoleTrainingGroupV1(
                case_id=case.id,
                company_id=finqa_company_id(case.filename),
                role_id=role.role_id,
                descriptor_ids=descriptor_ids,
                features=features,
                labels=labels,
            )
        )
    return PreparedTrainingCaseV1(
        case_id=case.id,
        company_id=finqa_company_id(case.filename),
        role_groups=tuple(groups),
        source_candidate_count=len(candidates),
        descriptor_count=catalog_build.catalog.descriptor_count,
        normalized_empty_table_cell_count=normalized_empty_cells,
    )


@dataclass(frozen=True)
class FoldMetricV1:
    fold_index: int
    case_count: int
    company_count: int
    role_count: int
    e8_descriptor_recall_at_4: float
    learned_descriptor_recall_at_4: float


@dataclass(frozen=True)
class GroupedCrossValidationResultV1:
    folds: tuple[FoldMetricV1, ...]
    e8_descriptor_recall_at_4: float
    learned_descriptor_recall_at_4: float
    learned_delta_at_4: float
    learned_fold_recall_stddev: float


def _flatten_groups(
    groups: Sequence[DescriptorRoleTrainingGroupV1],
) -> tuple[tuple[tuple[float, ...], ...], tuple[bool, ...]]:
    features = tuple(feature for group in groups for feature in group.features)
    labels = tuple(label for group in groups for label in group.labels)
    if not features or not any(labels) or all(labels):
        raise ValueError("training fold has an invalid label distribution")
    return features, labels


def _role_hit_at_4(
    group: DescriptorRoleTrainingGroupV1,
    *,
    fit: BalancedRidgeFitV1 | None,
) -> bool:
    if fit is None:
        ranked = sorted(
            range(len(group.descriptor_ids)),
            key=lambda index: (
                -group.features[index][0],
                group.descriptor_ids[index],
            ),
        )
    else:
        ranked = sorted(
            range(len(group.descriptor_ids)),
            key=lambda index: (
                -fit.score(group.features[index]),
                -group.features[index][0],
                group.descriptor_ids[index],
            ),
        )
    return any(group.labels[index] for index in ranked[:4])


def grouped_cross_validate_v1(
    cases: Sequence[PreparedTrainingCaseV1],
    *,
    company_folds: Mapping[str, int],
    fold_count: int,
    l2_penalty: float,
) -> GroupedCrossValidationResultV1:
    if not cases or set(case.company_id for case in cases) - set(company_folds):
        raise ValueError("cross-validation company assignment is incomplete")
    fold_metrics = []
    total_e8_hits = 0
    total_learned_hits = 0
    total_roles = 0
    for fold_index in range(fold_count):
        train_groups = tuple(
            group
            for case in cases
            if company_folds[case.company_id] != fold_index
            for group in case.role_groups
        )
        held_cases = tuple(
            case
            for case in cases
            if company_folds[case.company_id] == fold_index
        )
        held_groups = tuple(group for case in held_cases for group in case.role_groups)
        train_features, train_labels = _flatten_groups(train_groups)
        fit = fit_balanced_ridge_v1(
            train_features,
            train_labels,
            l2_penalty=l2_penalty,
        )
        e8_hits = sum(_role_hit_at_4(group, fit=None) for group in held_groups)
        learned_hits = sum(
            _role_hit_at_4(group, fit=fit) for group in held_groups
        )
        role_count = len(held_groups)
        if role_count == 0:
            raise ValueError("cross-validation fold has no labelable roles")
        fold_metrics.append(
            FoldMetricV1(
                fold_index=fold_index,
                case_count=len(held_cases),
                company_count=len({case.company_id for case in held_cases}),
                role_count=role_count,
                e8_descriptor_recall_at_4=e8_hits / role_count,
                learned_descriptor_recall_at_4=learned_hits / role_count,
            )
        )
        total_e8_hits += e8_hits
        total_learned_hits += learned_hits
        total_roles += role_count
    learned_recall = total_learned_hits / total_roles
    e8_recall = total_e8_hits / total_roles
    return GroupedCrossValidationResultV1(
        folds=tuple(fold_metrics),
        e8_descriptor_recall_at_4=e8_recall,
        learned_descriptor_recall_at_4=learned_recall,
        learned_delta_at_4=learned_recall - e8_recall,
        learned_fold_recall_stddev=statistics.pstdev(
            item.learned_descriptor_recall_at_4 for item in fold_metrics
        ),
    )


def select_eligible_train_cases_v1(
    raw_cases: Sequence[object],
    *,
    heldout_companies: set[str],
    heldout_questions: set[str],
    protocol: FinQALearnedRankerProtocolV1,
) -> tuple[FinQACase, ...]:
    selected = []
    for raw in raw_cases:
        if not isinstance(raw, dict) or not isinstance(raw.get("qa"), dict):
            raise ValueError("FinQA train row has no minimal selection schema")
        case_id = raw.get("id")
        filename = raw.get("filename")
        question = raw["qa"].get("question")
        program = raw["qa"].get("program")
        if not all(
            isinstance(value, str) and value
            for value in (case_id, filename, question, program)
        ):
            raise ValueError("FinQA train row selection fields are invalid")
        operations = tuple(_OPERATION.findall(program))
        if (
            finqa_company_id(filename) in heldout_companies
            or normalized_question(question) in heldout_questions
            or not operations
            or len(operations) > protocol.training_boundary.max_program_steps
            or not set(operations).issubset(
                protocol.training_boundary.supported_operations
            )
        ):
            continue
        selected.append(FinQACase.model_validate(raw))
    selected.sort(key=lambda item: item.id)
    if (
        len(selected) != protocol.training_boundary.eligible_case_count
        or strings_sha256([item.id for item in selected])
        != protocol.training_boundary.eligible_case_ids_sha256
    ):
        raise ValueError("eligible E9 train cohort does not match protocol")
    return tuple(selected)


def build_final_artifact_v1(
    cases: Sequence[PreparedTrainingCaseV1],
    *,
    protocol: FinQALearnedRankerProtocolV1,
    protocol_sha256: str,
):
    groups = tuple(group for case in cases for group in case.role_groups)
    features, labels = _flatten_groups(groups)
    fit = fit_balanced_ridge_v1(
        features,
        labels,
        l2_penalty=protocol.model.l2_penalty,
    )
    return build_learned_descriptor_ranker_artifact_v1(
        fit=fit,
        protocol_sha256=protocol_sha256,
        training_split_sha256=protocol.training_boundary.train_split_sha256,
        eligible_case_ids_sha256=(
            protocol.training_boundary.eligible_case_ids_sha256
        ),
        training_example_count=len(features),
        positive_example_count=sum(labels),
        l2_penalty=protocol.model.l2_penalty,
    )


def load_strict_json_array(path: Path, *, expected_sha256: str) -> list[object]:
    content = path.resolve().read_bytes()
    if (
        not content
        or len(content) > 128 * 1024 * 1024
        or hashlib.sha256(content).hexdigest() != expected_sha256
    ):
        raise ValueError("E9 training split does not match pinned bytes")
    payload = json.loads(content.decode("utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("E9 training split must be a non-empty array")
    return payload


def training_failure_counts(
    failures: Sequence[str],
) -> dict[str, int]:
    return dict(sorted(Counter(failures).items()))


__all__ = [
    "DescriptorRoleTrainingGroupV1",
    "FOLD_ALGORITHM_VERSION",
    "PreparedTrainingCaseV1",
    "assign_company_folds_v1",
    "build_final_artifact_v1",
    "finqa_company_id",
    "grouped_cross_validate_v1",
    "load_strict_json_array",
    "model_input_unit_ids",
    "normalize_empty_table_cells_v1",
    "normalized_question",
    "prepare_training_case_v1",
    "select_eligible_train_cases_v1",
    "strings_sha256",
]
