from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from app.external_datasets.finqa import DEFAULT_PRIVATE_ROOT, DEFAULT_SOURCE_ROOT
from app.external_datasets.finqa_learned_ranker_protocol_v1 import (
    load_learned_ranker_protocol_v1,
)
from app.external_datasets.finqa_learned_ranker_training_v1 import (
    assign_company_folds_v1,
    finqa_company_id,
    load_strict_json_array,
    normalized_question,
    select_eligible_train_cases_v1,
    strings_sha256,
)
from app.external_datasets.finqa_pairwise_residual_ranker_v1 import (
    PAIRWISE_FEATURE_NAMES,
)
from app.external_datasets.finqa_pairwise_residual_training_v1 import (
    prepare_pairwise_training_case_v1,
    top_retrieved_unit_ids_v1,
)
from app.external_datasets.finqa_topk_ranker_protocol_v1 import (
    load_topk_ranker_protocol_v1,
)
from app.external_datasets.finqa_topk_ranker_training_v1 import (
    build_final_topk_artifact_v1,
    nested_company_cross_validate_v1,
)
from app.security.retrieved_content import RetrievedContentGuard


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/external_datasets/evidence/finqa_topk_ranker_protocol_v1.json"
E9_PROTOCOL = ROOT / "docs/external_datasets/evidence/finqa_learned_ranker_protocol_v1.json"
E10_CV = ROOT / "docs/external_datasets/evidence/finqa_pairwise_residual_cv_public_v1.json"
SOURCE_FILES = {
    "source_e10_protocol_sha256": ROOT
    / "docs/external_datasets/evidence/finqa_pairwise_residual_protocol_v1.json",
    "source_e10_cv_sha256": E10_CV,
    "source_e10_artifact_file_sha256": ROOT
    / "docs/external_datasets/evidence/finqa_pairwise_residual_ranker_artifact_v1.json",
    "source_e10_postmortem_sha256": ROOT
    / "docs/external_datasets/evidence/finqa_pairwise_residual_postmortem_public_v1.json",
    "source_e10_erratum_sha256": ROOT
    / "docs/external_datasets/evidence/finqa_pairwise_residual_protocol_erratum_v1.json",
}
E5_DETAILS = (
    DEFAULT_PRIVATE_ROOT
    / "semantic_planning_calibration_runs/finqa-semantic-planning-calibration-v1/details.jsonl"
)
ARTIFACT_OUTPUT = (
    ROOT / "docs/external_datasets/evidence/finqa_topk_ranker_artifact_v1.json"
)
CV_OUTPUT = ROOT / "docs/external_datasets/evidence/finqa_topk_nested_cv_public_v1.json"
PRIVATE_OUTPUT = (
    DEFAULT_PRIVATE_ROOT / "topk_ranker_runs/finqa-top4-boundary-e11-v1"
)
IMPLEMENTATION_FILES = (
    "app/external_datasets/finqa_topk_ranker_protocol_v1.py",
    "app/external_datasets/finqa_topk_ranker_v1.py",
    "app/external_datasets/finqa_topk_ranker_training_v1.py",
    "scripts/train_finqa_topk_ranker_v1.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.resolve().read_bytes()).hexdigest()


def _canonical(payload: object) -> bytes:
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
            raise ValueError(f"refusing to overwrite E11 evidence: {path.name}")
        return
    path.write_bytes(content)


def _failure_code(error: Exception) -> str:
    return f"{type(error).__name__}:{str(error).splitlines()[0].strip()}"[:240]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Train the E11 nested-CV Top-4 boundary ranker."
    )
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument(
        "--train", type=Path, default=DEFAULT_SOURCE_ROOT / "dataset/train.json"
    )
    parser.add_argument(
        "--dev", type=Path, default=DEFAULT_SOURCE_ROOT / "dataset/dev.json"
    )
    parser.add_argument("--artifact-output", type=Path, default=ARTIFACT_OUTPUT)
    parser.add_argument("--cv-output", type=Path, default=CV_OUTPUT)
    parser.add_argument("--private-output", type=Path, default=PRIVATE_OUTPUT)
    args = parser.parse_args()

    protocol, protocol_sha256 = load_topk_ranker_protocol_v1(args.protocol)
    e9_protocol, _ = load_learned_ranker_protocol_v1(E9_PROTOCOL)
    for field, path in SOURCE_FILES.items():
        if _sha256(path) != getattr(protocol, field):
            raise ValueError(f"E11 source binding failed: {field}")
    e10_cv = json.loads(E10_CV.read_text(encoding="utf-8"))
    if e10_cv["decision"] != "E10_CV_GATE_FAILED_INTERNAL_VALIDATION_PROHIBITED":
        raise ValueError("E11 requires the frozen E10 negative decision")

    raw_train = load_strict_json_array(
        args.train,
        expected_sha256=protocol.training_boundary.train_split_sha256,
    )
    dev = json.loads(args.dev.resolve().read_text(encoding="utf-8"))
    disclosed_ids = {
        json.loads(line)["case_id"]
        for line in E5_DETAILS.read_text(encoding="utf-8").splitlines()
        if line
    }
    dev_by_id = {item["id"]: item for item in dev}
    heldout_companies = {
        finqa_company_id(dev_by_id[case_id]["filename"])
        for case_id in disclosed_ids
    }
    heldout_questions = {
        normalized_question(dev_by_id[case_id]["qa"]["question"])
        for case_id in disclosed_ids
    }
    eligible = select_eligible_train_cases_v1(
        raw_train,
        heldout_companies=heldout_companies,
        heldout_questions=heldout_questions,
        protocol=e9_protocol,
    )
    boundary = protocol.training_boundary
    if (
        len(eligible) != boundary.eligible_case_count
        or strings_sha256([case.id for case in eligible])
        != boundary.eligible_case_ids_sha256
    ):
        raise ValueError("E11 eligible train boundary changed")

    selections = []
    for case in eligible:
        unit_ids = top_retrieved_unit_ids_v1(
            case.text_retrieved_all,
            case.table_retrieved_all,
            limit=boundary.max_selected_units_per_case,
        )
        selections.append({"case_id": case.id, "unit_ids": list(unit_ids)})
    selections.sort(key=lambda item: item["case_id"])
    if hashlib.sha256(_canonical(selections)).hexdigest() != (
        boundary.retrieval_selection_sha256
    ):
        raise ValueError("E11 retrieval-realistic input boundary changed")

    company_counts = Counter(finqa_company_id(case.filename) for case in eligible)
    assignment = assign_company_folds_v1(
        company_counts,
        fold_count=len(protocol.folds),
        seed=e9_protocol.fold_seed,
    )
    for frozen_fold in protocol.folds:
        companies = tuple(
            company
            for company, fold_index in assignment.items()
            if fold_index == frozen_fold.fold_index
        )
        if (
            sum(company_counts[company] for company in companies)
            != frozen_fold.case_count
            or len(companies) != frozen_fold.company_count
            or strings_sha256(companies) != frozen_fold.company_ids_sha256
        ):
            raise ValueError("E11 company fold changed")

    guard = RetrievedContentGuard()
    prepared = []
    failures = []
    private_rows = []
    for index, case in enumerate(eligible, start=1):
        company = finqa_company_id(case.filename)
        try:
            item = prepare_pairwise_training_case_v1(
                case,
                guard=guard,
                selected_unit_limit=boundary.max_selected_units_per_case,
            )
            prepared.append(item)
            private_rows.append(
                {
                    "case_id": case.id,
                    "company_id": company,
                    "descriptor_count": item.descriptor_count,
                    "fold_index": assignment[company],
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
                    "company_id": company,
                    "failure_code": code,
                    "fold_index": assignment[company],
                    "status": "PREPARATION_FAILED",
                }
            )
        if index % 250 == 0:
            print(f"prepared {index}/{len(eligible)}", flush=True)

    nested = nested_company_cross_validate_v1(
        prepared,
        company_folds=assignment,
        protocol=protocol,
    )
    artifact = build_final_topk_artifact_v1(
        prepared,
        protocol=protocol,
        protocol_sha256=protocol_sha256,
        final_config_id=nested.final_config_id,
    )
    labelable_case_count = sum(bool(case.role_groups) for case in prepared)
    preparation_rate = len(prepared) / len(eligible)
    labelable_rate = labelable_case_count / len(eligible)
    gates = protocol.cv_gates
    e10_e8_recall = e10_cv["cross_validation"]["e8_descriptor_recall_at_4"]
    checks = {
        "preparation_success_rate": preparation_rate
        >= gates.min_preparation_success_rate,
        "labelable_case_rate": labelable_rate >= gates.min_labelable_case_rate,
        "outer_oof_descriptor_recall_delta_at_4": (
            nested.challenger_delta_at_4
            >= gates.min_outer_oof_descriptor_recall_delta_at_4
        ),
        "outer_fold_descriptor_recall_stddev": (
            nested.challenger_fold_recall_stddev
            <= gates.max_outer_fold_descriptor_recall_stddev
        ),
        "no_regressed_outer_fold": all(
            fold.delta_at_4 >= 0 for fold in nested.outer_folds
        ),
        "outer_fold_coefficient_cosine_similarity": (
            nested.min_outer_fold_coefficient_cosine_similarity
            >= gates.min_outer_fold_coefficient_cosine_similarity
        ),
        "nested_company_disjoint_selection": all(
            len(selection.candidate_metrics)
            == len(protocol.model.candidate_configs)
            for selection in nested.outer_selections
        ),
        "e8_reproduction_matches_e10": abs(
            nested.e8_descriptor_recall_at_4 - e10_e8_recall
        )
        <= 1e-15,
        "zero_feature_label_leakage": not set(PAIRWISE_FEATURE_NAMES).intersection(
            protocol.model.prohibited_features
        ),
        "bounded_residual": max(
            item.max_e8_score_adjustment
            for item in protocol.model.candidate_configs
        )
        <= 8.0,
        "zero_model_calls": True,
        "e9_development_not_rerun": protocol.e9_development_status
        == "CONSUMED_NO_RERUN",
        "internal_validation_not_run": protocol.internal_validation.status
        == "NOT_RUN",
        "frozen_test_untouched": protocol.frozen_test_status == "UNTOUCHED",
        "serving_route_disabled": protocol.challenger_serving_status == "DISABLED",
    }
    cv_payload = {
        "artifact_sha256": artifact.artifact_sha256,
        "case_preparation_failure_count": len(failures),
        "case_preparation_failure_reasons": dict(sorted(Counter(failures).items())),
        "case_preparation_success_count": len(prepared),
        "case_preparation_success_rate": preparation_rate,
        "claim": "TRAIN_DEVELOPMENT_NESTED_COMPANY_CV_NOT_INDEPENDENT_CONFIRMATION",
        "decision": (
            "E11_OUTER_CV_AUTHORIZED_FOR_SINGLE_INTERNAL_VALIDATION"
            if all(checks.values())
            else "E11_OUTER_CV_GATE_FAILED_INTERNAL_VALIDATION_PROHIBITED"
        ),
        "eligible_case_count": len(eligible),
        "feature_count": len(PAIRWISE_FEATURE_NAMES),
        "final_config_id": nested.final_config_id,
        "frozen_test_status": protocol.frozen_test_status,
        "gate_checks": checks,
        "implementation_sha256": {
            relative: _sha256(ROOT / relative)
            for relative in IMPLEMENTATION_FILES
        },
        "internal_validation_status": protocol.internal_validation.status,
        "labelable_case_count": labelable_case_count,
        "labelable_case_rate": labelable_rate,
        "model_call_count": 0,
        "nested_cross_validation": {
            "challenger_delta_at_4": nested.challenger_delta_at_4,
            "challenger_descriptor_recall_at_4": (
                nested.challenger_descriptor_recall_at_4
            ),
            "challenger_fold_recall_stddev": (
                nested.challenger_fold_recall_stddev
            ),
            "e8_descriptor_recall_at_4": nested.e8_descriptor_recall_at_4,
            "gained": nested.gained,
            "min_outer_fold_coefficient_cosine_similarity": (
                nested.min_outer_fold_coefficient_cosine_similarity
            ),
            "missed_both": nested.missed_both,
            "outer_folds": [asdict(item) for item in nested.outer_folds],
            "outer_selections": [
                asdict(item) for item in nested.outer_selections
            ],
            "regressed": nested.regressed,
            "retained": nested.retained,
            "selected_config_counts": nested.selected_config_counts,
        },
        "prior_train_oof_reuse": boundary.prior_train_oof_reuse,
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "retrieval_selection_sha256": boundary.retrieval_selection_sha256,
        "role_group_count": artifact.training_group_count,
        "schema_version": "finqa_topk_nested_cv_public_v1",
        "training_pair_stats": {
            "effective_pair_weight": artifact.effective_pair_weight,
            "miss_group_count": artifact.miss_group_count,
            "pair_count": artifact.training_pair_count,
            "preservation_group_count": artifact.preservation_group_count,
            "redundant_hit_group_count": artifact.redundant_hit_group_count,
        },
    }
    artifact_bytes = _canonical(artifact.model_dump(mode="json")) + b"\n"
    cv_bytes = _canonical(cv_payload) + b"\n"
    details_bytes = b"".join(_canonical(row) + b"\n" for row in private_rows)
    private_dir = args.private_output.resolve()
    manifest = {
        "artifact_file_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "cv_file_sha256": hashlib.sha256(cv_bytes).hexdigest(),
        "details_sha256": hashlib.sha256(details_bytes).hexdigest(),
        "protocol_sha256": protocol_sha256,
        "run_id": private_dir.name,
    }
    _write_once(args.artifact_output, artifact_bytes)
    _write_once(args.cv_output, cv_bytes)
    _write_once(private_dir / "details.jsonl", details_bytes)
    _write_once(private_dir / "manifest.json", _canonical(manifest) + b"\n")
    print(json.dumps(cv_payload, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
