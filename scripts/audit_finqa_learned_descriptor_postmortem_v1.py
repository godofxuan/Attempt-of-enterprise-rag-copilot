from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

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
    load_learned_descriptor_ranker_artifact_v1,
)
from app.external_datasets.finqa_role_compatibility_audit_v2 import (
    _source_bound_constant_ids,
    build_oracle_semantic_program_v2,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
E8_DETAILS = (
    DEFAULT_PRIVATE_ROOT
    / "retrievable_descriptor_audits/finqa-retrievable-descriptor-e8-v1/details.jsonl"
)
E9_DETAILS = (
    DEFAULT_PRIVATE_ROOT
    / "learned_descriptor_ranker_audits"
    / "finqa-learned-descriptor-ranker-e9-development-v1/details.jsonl"
)
E8_RESULT = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_retrievable_descriptor_public_v1.json"
)
E9_RESULT = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_learned_descriptor_development_public_v1.json"
)
CV_RESULT = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_learned_descriptor_cv_public_v1.json"
)
ARTIFACT = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_learned_descriptor_ranker_artifact_v1.json"
)
OUTPUT = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_learned_descriptor_postmortem_public_v1.json"
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


def _load_rows(path: Path) -> dict[str, dict[str, object]]:
    rows = {
        row["case_id"]: row
        for row in (
            json.loads(line)
            for line in path.resolve().read_text(encoding="utf-8").splitlines()
            if line
        )
    }
    if len(rows) != 60:
        raise ValueError("postmortem source does not contain 60 unique cases")
    return rows


def _transition(source: bool, target: bool) -> str:
    return {
        (True, True): "retained",
        (True, False): "regressed",
        (False, True): "gained",
        (False, False): "missed_both",
    }[(source, target)]


def main() -> int:
    e8_rows = _load_rows(E8_DETAILS)
    e9_rows = _load_rows(E9_DETAILS)
    if set(e8_rows) != set(e9_rows):
        raise ValueError("postmortem paired case identities differ")
    development_cases, _ = load_finqa_split(
        DEFAULT_SOURCE_ROOT / "dataset/dev.json",
        expected_sha256=FINQA_DEV_SHA256,
    )
    cases_by_id = {case.id: case for case in development_cases}
    descriptor_transitions: Counter[str] = Counter()
    candidate_transitions: Counter[str] = Counter()
    complete_case_transitions: Counter[str] = Counter()
    semantic_descriptor_transitions: dict[str, Counter[str]] = {}
    regression_candidate_bins: Counter[str] = Counter()
    descriptor_available_count = 0
    role_count = 0
    for case_id in sorted(e8_rows):
        e8 = e8_rows[case_id]
        e9 = e9_rows[case_id]
        if "descriptor_complete_at_4" in e8:
            complete_case_transitions[
                _transition(
                    bool(e8["descriptor_complete_at_4"]),
                    bool(e9["descriptor_complete_at_4"]),
                )
            ] += 1
        if not e8.get("retention"):
            continue
        case = cases_by_id[case_id]
        oracle = build_oracle_semantic_program_v2(
            question=case.qa.question,
            program=case.qa.program,
            source_bound_constant_ids=_source_bound_constant_ids(case),
        )
        if oracle.skeleton is None:
            raise ValueError("postmortem typed row has no oracle skeleton")
        semantic_by_role = {
            role.role_id: role.semantic_role for role in oracle.skeleton.roles
        }
        e9_by_role = {item["role_id"]: item for item in e9["retention"]}
        for e8_role in e8["retention"]:
            role_count += 1
            e9_role = e9_by_role[e8_role["role_id"]]
            descriptor_available_count += bool(e8_role["oracle_descriptor_ids"])
            descriptor_transition = _transition(
                bool(e8_role["descriptor_hit_at_4"]),
                bool(e9_role["descriptor_hit_at_4"]),
            )
            candidate_transition = _transition(
                bool(e8_role["retained_at_8"]),
                bool(e9_role["retained_at_8"]),
            )
            descriptor_transitions[descriptor_transition] += 1
            candidate_transitions[candidate_transition] += 1
            semantic_role = semantic_by_role[e8_role["role_id"]]
            semantic_descriptor_transitions.setdefault(
                semantic_role, Counter()
            )[descriptor_transition] += 1
            if descriptor_transition == "regressed":
                candidate_count = int(e8["source_candidate_count"])
                bin_name = (
                    "le_16"
                    if candidate_count <= 16
                    else "le_32"
                    if candidate_count <= 32
                    else "le_64"
                    if candidate_count <= 64
                    else "gt_64"
                )
                regression_candidate_bins[bin_name] += 1

    artifact = load_learned_descriptor_ranker_artifact_v1(ARTIFACT)
    coefficient_ranking = sorted(
        zip(artifact.feature_names, artifact.coefficients, strict=True),
        key=lambda item: (-abs(item[1]), item[0]),
    )
    payload = {
        "candidate_recall_at_8_transitions": dict(candidate_transitions),
        "coefficient_ranking_by_absolute_value": [
            {"coefficient": coefficient, "feature": feature}
            for feature, coefficient in coefficient_ranking
        ],
        "complete_case_transitions": dict(complete_case_transitions),
        "decision": "KEEP_E8_CHAMPION_AND_DO_NOT_REUSE_E9_DEVELOPMENT_BUDGET",
        "descriptor_available_role_count": descriptor_available_count,
        "descriptor_recall_at_4_transitions": dict(descriptor_transitions),
        "diagnosis": [
            "train_serving_evidence_distribution_mismatch",
            "pointwise_objective_does_not_directly_optimize_top4_role_recall",
            "unbounded_learned_score_can_override_strong_e8_ordering",
            "correlated_features_produce_non_causal_coefficient_signs",
        ],
        "e9_development_result_sha256": _sha256(E9_RESULT),
        "e9_train_cv_result_sha256": _sha256(CV_RESULT),
        "e9_training_evidence_contract": "finqa_model_input_with_gold_coverage",
        "next_protocol_requirements": [
            "use retrieval-realistic train evidence without forced gold injection",
            "optimize pairwise or listwise top4 ranking on company-grouped folds",
            "bound challenger adjustments around the E8 champion score",
            "add coefficient stability and feature-ablation gates",
            "do not rerun the consumed 60-case development cohort for E9",
            "do not consume internal validation or frozen test",
        ],
        "regressed_role_source_candidate_bins": dict(regression_candidate_bins),
        "role_count": role_count,
        "schema_version": "finqa_learned_descriptor_postmortem_public_v1",
        "semantic_role_descriptor_transitions": {
            role: dict(counts)
            for role, counts in sorted(semantic_descriptor_transitions.items())
        },
        "source_e8_details_sha256": _sha256(E8_DETAILS),
        "source_e8_result_sha256": _sha256(E8_RESULT),
        "source_e9_details_sha256": _sha256(E9_DETAILS),
    }
    content = _canonical_bytes(payload)
    if OUTPUT.exists() and OUTPUT.read_bytes() != content:
        raise ValueError("refusing to overwrite E9 postmortem evidence")
    if not OUTPUT.exists():
        OUTPUT.write_bytes(content)
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
