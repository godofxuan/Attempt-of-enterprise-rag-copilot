from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from app.external_datasets.finqa import (
    DEFAULT_PRIVATE_ROOT,
    DEFAULT_SOURCE_ROOT,
    FINQA_DEV_SHA256,
    load_finqa_split,
)
from app.external_datasets.finqa_learned_descriptor_ranker_v1 import (
    FEATURE_NAMES,
)
from app.external_datasets.finqa_learned_ranker_protocol_v1 import (
    load_learned_ranker_protocol_v1,
)
from app.external_datasets.finqa_learned_ranker_training_v1 import (
    assign_company_folds_v1,
    build_final_artifact_v1,
    finqa_company_id,
    grouped_cross_validate_v1,
    load_strict_json_array,
    normalized_question,
    prepare_training_case_v1,
    select_eligible_train_cases_v1,
    strings_sha256,
)
from app.security.retrieved_content import RetrievedContentGuard


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_learned_ranker_protocol_v1.json"
)
DEFAULT_E8_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_retrievable_descriptor_protocol_v1.json"
)
DEFAULT_E8_RESULT = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_retrievable_descriptor_public_v1.json"
)
DEFAULT_E5_DETAILS = (
    DEFAULT_PRIVATE_ROOT
    / "semantic_planning_calibration_runs"
    / "finqa-semantic-planning-calibration-v1"
    / "details.jsonl"
)
DEFAULT_ARTIFACT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_learned_descriptor_ranker_artifact_v1.json"
)
DEFAULT_CV_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_learned_descriptor_cv_public_v1.json"
)
DEFAULT_PRIVATE_OUTPUT = (
    DEFAULT_PRIVATE_ROOT
    / "learned_descriptor_ranker_runs"
    / "finqa-learned-descriptor-ranker-e9-v1"
)
IMPLEMENTATION_FILES = (
    "app/external_datasets/finqa_learned_ranker_protocol_v1.py",
    "app/external_datasets/finqa_learned_descriptor_ranker_v1.py",
    "app/external_datasets/finqa_learned_ranker_training_v1.py",
    "scripts/train_finqa_learned_descriptor_ranker_v1.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.resolve().read_bytes()).hexdigest()


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _write_once(path: Path, content: bytes) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"refusing to overwrite existing evidence: {path.name}")
        return
    path.write_bytes(content)


def _load_disclosed_development_ids(path: Path) -> tuple[str, ...]:
    rows = tuple(
        json.loads(line)
        for line in path.resolve().read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    case_ids = tuple(row.get("case_id") for row in rows)
    if (
        not case_ids
        or any(not isinstance(case_id, str) or not case_id for case_id in case_ids)
        or len(case_ids) != len(set(case_ids))
    ):
        raise ValueError("E9 disclosed development source is invalid")
    return case_ids


def _failure_code(error: Exception) -> str:
    message = str(error).splitlines()[0].strip()
    return f"{type(error).__name__}:{message}"[:240]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train and company-group cross-validate the E9 descriptor ranker."
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument(
        "--train",
        type=Path,
        default=DEFAULT_SOURCE_ROOT / "dataset/train.json",
    )
    parser.add_argument(
        "--dev",
        type=Path,
        default=DEFAULT_SOURCE_ROOT / "dataset/dev.json",
    )
    parser.add_argument("--e5-details", type=Path, default=DEFAULT_E5_DETAILS)
    parser.add_argument(
        "--artifact-output", type=Path, default=DEFAULT_ARTIFACT_OUTPUT
    )
    parser.add_argument("--cv-output", type=Path, default=DEFAULT_CV_OUTPUT)
    parser.add_argument(
        "--private-output", type=Path, default=DEFAULT_PRIVATE_OUTPUT
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    protocol, protocol_sha256 = load_learned_ranker_protocol_v1(args.protocol)
    if (
        _sha256(DEFAULT_E8_PROTOCOL) != protocol.source_e8_protocol_sha256
        or _sha256(DEFAULT_E8_RESULT) != protocol.source_e8_result_sha256
    ):
        raise ValueError("E9 immutable E8 source binding failed")
    development_ids = _load_disclosed_development_ids(args.e5_details)
    development_cases, development_sha256 = load_finqa_split(
        args.dev,
        expected_sha256=FINQA_DEV_SHA256,
    )
    development_by_id = {case.id: case for case in development_cases}
    if set(development_ids) - set(development_by_id):
        raise ValueError("E9 disclosed development IDs are outside pinned dev")
    disclosed_cases = tuple(development_by_id[case_id] for case_id in development_ids)
    heldout_companies = {finqa_company_id(case.filename) for case in disclosed_cases}
    heldout_questions = {
        normalized_question(case.qa.question) for case in disclosed_cases
    }
    boundary = protocol.training_boundary
    if (
        development_sha256 != protocol.development_split_sha256
        or strings_sha256(development_ids) != protocol.development_case_ids_sha256
        or len(heldout_companies) != boundary.disclosed_development_company_count
        or strings_sha256(tuple(heldout_companies))
        != boundary.disclosed_development_company_ids_sha256
        or strings_sha256(tuple(heldout_questions))
        != boundary.disclosed_development_question_templates_sha256
    ):
        raise ValueError("E9 disclosed development isolation binding failed")

    raw_train = load_strict_json_array(
        args.train,
        expected_sha256=boundary.train_split_sha256,
    )
    if len(raw_train) != boundary.train_case_count:
        raise ValueError("E9 pinned train row count changed")
    all_companies = {
        finqa_company_id(item["filename"])
        for item in raw_train
        if isinstance(item, dict) and isinstance(item.get("filename"), str)
    }
    if len(all_companies) != boundary.train_company_count:
        raise ValueError("E9 pinned train company count changed")
    eligible = select_eligible_train_cases_v1(
        raw_train,
        heldout_companies=heldout_companies,
        heldout_questions=heldout_questions,
        protocol=protocol,
    )
    case_count_by_company = Counter(
        finqa_company_id(case.filename) for case in eligible
    )
    assignment = assign_company_folds_v1(
        case_count_by_company,
        fold_count=len(protocol.folds),
        seed=protocol.fold_seed,
    )
    for frozen_fold in protocol.folds:
        companies = tuple(
            company
            for company, fold_index in assignment.items()
            if fold_index == frozen_fold.fold_index
        )
        case_count = sum(case_count_by_company[company] for company in companies)
        if (
            case_count != frozen_fold.case_count
            or len(companies) != frozen_fold.company_count
            or strings_sha256(companies) != frozen_fold.company_ids_sha256
        ):
            raise ValueError("E9 company fold no longer matches frozen protocol")

    guard = RetrievedContentGuard()
    prepared = []
    private_rows = []
    failures = []
    for index, case in enumerate(eligible, start=1):
        try:
            item = prepare_training_case_v1(case, guard=guard)
            prepared.append(item)
            private_rows.append(
                {
                    "case_id": case.id,
                    "company_id": item.company_id,
                    "descriptor_count": item.descriptor_count,
                    "fold_index": assignment[item.company_id],
                    "normalized_empty_table_cell_count": (
                        item.normalized_empty_table_cell_count
                    ),
                    "role_count": len(item.role_groups),
                    "source_candidate_count": item.source_candidate_count,
                    "status": "PREPARED",
                }
            )
        except Exception as error:
            code = _failure_code(error)
            failures.append(code)
            private_rows.append(
                {
                    "case_id": case.id,
                    "company_id": finqa_company_id(case.filename),
                    "failure_code": code,
                    "fold_index": assignment[finqa_company_id(case.filename)],
                    "status": "PREPARATION_FAILED",
                }
            )
        if index % 250 == 0:
            print(f"prepared {index}/{len(eligible)}", flush=True)
    if not prepared:
        raise ValueError("E9 training preparation produced no cases")

    cv = grouped_cross_validate_v1(
        prepared,
        company_folds=assignment,
        fold_count=len(protocol.folds),
        l2_penalty=protocol.model.l2_penalty,
    )
    artifact = build_final_artifact_v1(
        prepared,
        protocol=protocol,
        protocol_sha256=protocol_sha256,
    )
    role_count = sum(len(case.role_groups) for case in prepared)
    labelable_case_count = sum(bool(case.role_groups) for case in prepared)
    feature_label_leakage = bool(
        set(FEATURE_NAMES).intersection(protocol.model.prohibited_features)
    )
    preparation_success_rate = len(prepared) / len(eligible)
    labelable_case_rate = labelable_case_count / len(eligible)
    checks = {
        "company_disjoint_source": not {
            case.company_id for case in prepared
        }.intersection(heldout_companies),
        "eligible_cohort_identity": len(eligible) == boundary.eligible_case_count,
        "fold_identity": True,
        "preparation_success_rate_at_least_0_95": preparation_success_rate >= 0.95,
        "labelable_case_rate_at_least_0_90": labelable_case_rate >= 0.90,
        "oof_descriptor_recall_delta_at_4": (
            cv.learned_delta_at_4
            >= protocol.progress_gates.min_oof_descriptor_recall_delta_at_4
        ),
        "oof_fold_descriptor_recall_stddev": (
            cv.learned_fold_recall_stddev
            <= protocol.progress_gates.max_oof_fold_descriptor_recall_stddev
        ),
        "zero_feature_label_leakage": not feature_label_leakage,
        "zero_model_calls": True,
        "champion_fallback_contract_present": True,
        "serving_route_disabled": protocol.challenger_serving_status == "DISABLED",
        "internal_validation_not_run": protocol.internal_validation_status
        == "NOT_RUN",
        "frozen_test_untouched": protocol.frozen_test_status == "UNTOUCHED",
    }
    cv_payload = {
        "artifact_sha256": artifact.artifact_sha256,
        "case_preparation_failure_count": len(failures),
        "case_preparation_failure_reasons": dict(sorted(Counter(failures).items())),
        "case_preparation_success_count": len(prepared),
        "case_preparation_success_rate": preparation_success_rate,
        "challenger_serving_status": protocol.challenger_serving_status,
        "claim": "TRAIN_ONLY_COMPANY_GROUPED_CROSS_VALIDATION",
        "company_disjoint_from_disclosed_development": True,
        "cross_validation": {
            "e8_descriptor_recall_at_4": cv.e8_descriptor_recall_at_4,
            "folds": [item.__dict__ for item in cv.folds],
            "learned_delta_at_4": cv.learned_delta_at_4,
            "learned_descriptor_recall_at_4": (
                cv.learned_descriptor_recall_at_4
            ),
            "learned_fold_recall_stddev": cv.learned_fold_recall_stddev,
        },
        "decision": (
            "E9_CV_CHALLENGER_ELIGIBLE_FOR_ONE_DEVELOPMENT_RUN"
            if all(checks.values())
            else "E9_CV_GATE_FAILED"
        ),
        "eligible_case_count": len(eligible),
        "eligible_case_ids_sha256": boundary.eligible_case_ids_sha256,
        "feature_count": len(FEATURE_NAMES),
        "fold_algorithm": protocol.fold_algorithm,
        "frozen_test_status": protocol.frozen_test_status,
        "gate_checks": checks,
        "implementation_sha256": {
            relative: _sha256(REPOSITORY_ROOT / relative)
            for relative in IMPLEMENTATION_FILES
        },
        "internal_validation_status": protocol.internal_validation_status,
        "labelable_case_count": labelable_case_count,
        "labelable_case_rate": labelable_case_rate,
        "model_call_count": 0,
        "normalized_empty_table_cell_count": sum(
            case.normalized_empty_table_cell_count for case in prepared
        ),
        "non_claims": [
            "not answer accuracy",
            "not end-to-end retrieval quality",
            "not a held-out or confirmatory result",
            "not authorization to consume internal validation or frozen test",
            "not authorization to activate the challenger in serving",
        ],
        "positive_training_example_count": artifact.positive_example_count,
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "role_group_count": role_count,
        "schema_version": "finqa_learned_descriptor_cv_public_v1",
        "training_example_count": artifact.training_example_count,
        "training_split_sha256": boundary.train_split_sha256,
    }
    artifact_bytes = _canonical_bytes(artifact.model_dump(mode="json")) + b"\n"
    cv_bytes = _canonical_bytes(cv_payload) + b"\n"
    private_dir = args.private_output.resolve()
    details_bytes = b"".join(
        _canonical_bytes(row) + b"\n" for row in private_rows
    )
    private_manifest = {
        "artifact_file_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "cv_public_file_sha256": hashlib.sha256(cv_bytes).hexdigest(),
        "details_sha256": hashlib.sha256(details_bytes).hexdigest(),
        "private_case_count": len(private_rows),
        "protocol_sha256": protocol_sha256,
        "run_id": private_dir.name,
    }
    _write_once(args.artifact_output, artifact_bytes)
    _write_once(args.cv_output, cv_bytes)
    _write_once(private_dir / "details.jsonl", details_bytes)
    _write_once(
        private_dir / "manifest.json",
        _canonical_bytes(private_manifest) + b"\n",
    )
    print(json.dumps(cv_payload, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
