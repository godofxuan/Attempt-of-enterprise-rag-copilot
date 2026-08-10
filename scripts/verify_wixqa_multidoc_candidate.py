from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Sequence

from app.evaluation.wixqa_multidoc_candidate import (
    MultiDocCandidateCase,
    derive_failure_analysis,
    evaluate_combined_gate,
    summarize_candidate_arm,
)
from app.external_datasets.wixqa_retrieval import canonical_json_bytes
from scripts.eval_wixqa_multidoc_candidate import (
    ARMS,
    CANDIDATE_BASE_REVISION,
)


EXPECTED_FILES = (
    "aggregate_v1.json",
    "case_matrix_v1.json",
    "failure_analysis_v1.json",
    "protocol_v1.json",
)
FORBIDDEN_PUBLIC_KEYS = {
    "answer",
    "answer_text",
    "controller_search_queries",
    "full_document_content",
    "model_raw_output",
    "prompt",
    "query",
    "query_variants",
    "question",
    "question_text",
    "raw_answer",
    "raw_output",
    "response_answer",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify public WixQA multi-document candidate evidence."
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("docs/multidoc_candidate/evidence"),
    )
    parser.add_argument(
        "--candidate-protocol",
        type=Path,
        default=Path(
            "docs/multidoc_candidate/00_LONG_TERM_PLAN_AND_PROTOCOL.md"
        ),
    )
    parser.add_argument(
        "--frozen-protocol",
        type=Path,
        default=Path(
            "docs/final_evidence_closure/evidence/"
            "answer_citation_60_protocol_v1.json"
        ),
    )
    parser.add_argument("--expected-code-revision")
    return parser


def verify_public_evidence(
    evidence_dir: Path,
    *,
    candidate_protocol_path: Path,
    frozen_protocol_path: Path | None = None,
    expected_code_revision: str | None = None,
) -> dict[str, object]:
    root = evidence_dir.resolve()
    missing = [name for name in EXPECTED_FILES if not (root / name).is_file()]
    if missing:
        raise ValueError(f"missing public evidence files: {missing}")

    aggregate_bytes = (root / "aggregate_v1.json").read_bytes()
    case_bytes = (root / "case_matrix_v1.json").read_bytes()
    protocol_bytes = (root / "protocol_v1.json").read_bytes()
    failure_analysis_bytes = (root / "failure_analysis_v1.json").read_bytes()
    aggregate = json.loads(aggregate_bytes)
    case_payload = json.loads(case_bytes)
    protocol = json.loads(protocol_bytes)
    published_failure_analysis = json.loads(failure_analysis_bytes)
    for name, payload, source_bytes in (
        ("aggregate", aggregate, aggregate_bytes),
        ("case_matrix", case_payload, case_bytes),
        ("protocol", protocol, protocol_bytes),
        (
            "failure_analysis",
            published_failure_analysis,
            failure_analysis_bytes,
        ),
    ):
        forbidden = sorted(_find_forbidden_keys(payload))
        if forbidden:
            raise ValueError(f"{name} exposes forbidden public keys: {forbidden}")
        if canonical_json_bytes(payload) != source_bytes:
            raise ValueError(f"{name} is not canonical JSON")

    if case_payload.get("schema_version") != "wixqa_multidoc_candidate_cases_v1":
        raise ValueError("case matrix schema version mismatch")
    raw_arms = case_payload.get("arms", {})
    if set(raw_arms) != set(ARMS):
        raise ValueError("case matrix arms do not match the frozen arm set")
    arm_cases = {
        arm: [MultiDocCandidateCase.model_validate(item) for item in raw_arms[arm]]
        for arm in ARMS
    }
    if case_payload.get("case_count") != 20:
        raise ValueError("case matrix must declare exactly 20 cases")
    expected_ids: set[str] | None = None
    for arm, cases in arm_cases.items():
        ids = [item.question_id_sha256 for item in cases]
        if len(cases) != 20 or len(ids) != len(set(ids)):
            raise ValueError(f"arm {arm} must contain 20 unique cases")
        if expected_ids is None:
            expected_ids = set(ids)
        elif set(ids) != expected_ids:
            raise ValueError("all arms must contain the same paired case IDs")

    recomputed_summaries = {
        arm: summarize_candidate_arm(arm_cases[arm], arm=arm).model_dump(
            mode="json"
        )
        for arm in ARMS
    }
    if aggregate.get("arm_summaries") != recomputed_summaries:
        raise ValueError("arm summaries do not recompute from case rows")
    gate = evaluate_combined_gate(
        arm_cases["current"],
        arm_cases["combined"],
        guard_enabled=protocol.get("guard_enabled") is True,
        acl_enabled=protocol.get("acl_enabled") is True,
        production_paths_unchanged=not protocol.get("changed_protected_paths"),
    )
    if aggregate.get("combined_vs_current_gate") != gate.model_dump(mode="json"):
        raise ValueError("combined gate does not recompute from paired cases")
    transitions = _paired_transitions(
        arm_cases["current"],
        arm_cases["combined"],
    )
    if (
        aggregate.get("paired_transitions") != transitions
        or case_payload.get("paired_transitions") != transitions
    ):
        raise ValueError("paired transitions do not recompute from case rows")

    frozen_path = frozen_protocol_path or Path(
        "docs/final_evidence_closure/evidence/answer_citation_60_protocol_v1.json"
    )
    frozen_bytes = frozen_path.resolve().read_bytes()
    if protocol.get("frozen_60_protocol_sha256") != _sha256(frozen_bytes):
        raise ValueError("frozen 60-case protocol hash mismatch")
    frozen = json.loads(frozen_bytes)
    gold_by_id = {
        _sha256_text(item["question_id"]): item["gold_support_article_ids"]
        for item in frozen.get("cases", [])
        if item.get("case_type") == "multi_document"
    }
    recomputed_failure_analysis = derive_failure_analysis(
        arm_cases["current"],
        arm_cases["combined"],
        gold_documents_by_question_id_sha256=gold_by_id,
    ).model_dump(mode="json")
    if published_failure_analysis != recomputed_failure_analysis:
        raise ValueError("failure analysis does not recompute from frozen evidence")

    run_ids = {
        aggregate.get("run_id"),
        case_payload.get("run_id"),
        protocol.get("run_id"),
    }
    if len(run_ids) != 1 or None in run_ids:
        raise ValueError("run IDs do not match")
    code_revisions = {
        aggregate.get("code_revision"),
        protocol.get("code_revision"),
    }
    if len(code_revisions) != 1 or None in code_revisions:
        raise ValueError("code revisions do not match")
    code_revision = next(iter(code_revisions))
    if not _is_git_revision(code_revision):
        raise ValueError("code revision must be a full Git object ID")
    if expected_code_revision and code_revision != expected_code_revision:
        raise ValueError("code revision does not match the expected revision")

    if aggregate.get("case_matrix_sha256") != _sha256(case_bytes):
        raise ValueError("case matrix hash mismatch")
    if aggregate.get("protocol_sha256") != _sha256(protocol_bytes):
        raise ValueError("protocol hash mismatch")
    if not _is_sha256(aggregate.get("private_details_sha256")):
        raise ValueError("private details hash is missing or malformed")
    if protocol.get("candidate_protocol_sha256") != _sha256(
        candidate_protocol_path.resolve().read_bytes()
    ):
        raise ValueError("frozen candidate protocol hash mismatch")
    if protocol.get("candidate_base_revision") != CANDIDATE_BASE_REVISION:
        raise ValueError("candidate base revision mismatch")
    if protocol.get("mode") != "RETROSPECTIVE_DEVELOPMENT_ONLY_CONSUMED":
        raise ValueError("candidate cohort-consumption mode mismatch")
    if protocol.get("normal_serving_behavior_changed") is not False:
        raise ValueError("protocol must state serving behavior was unchanged")
    if protocol.get("changed_protected_paths") != []:
        raise ValueError("candidate modified a protected production path")
    if protocol.get("generation_model_status") != "NOT_USED_EXTRACTIVE_ABLATION":
        raise ValueError("generation-model claim boundary mismatch")
    if aggregate.get("status") != "CANDIDATE_DEVELOPMENT_COMPLETE":
        raise ValueError("candidate run did not complete")
    if aggregate.get("decision") != "DEVELOPMENT_CANDIDATE_REJECTED":
        raise ValueError("checked-in candidate decision must remain rejected")
    claim_boundary = aggregate.get("claim_boundary", {})
    if any(
        claim_boundary.get(key) is not False
        for key in (
            "fixed_validation_authorized",
            "resume_quality_claim_allowed",
            "serving_change_authorized",
        )
    ):
        raise ValueError("rejected candidate cannot authorize promotion claims")

    return {
        "status": "VERIFIED_REJECTED_CANDIDATE",
        "run_id": next(iter(run_ids)),
        "code_revision": code_revision,
        "case_count": 20,
        "decision": gate.decision,
        "case_matrix_sha256": _sha256(case_bytes),
        "protocol_sha256": _sha256(protocol_bytes),
        "failure_analysis_sha256": _sha256(failure_analysis_bytes),
        "aggregate_sha256": _sha256(aggregate_bytes),
    }


def _paired_transitions(
    baseline: Sequence[MultiDocCandidateCase],
    candidate: Sequence[MultiDocCandidateCase],
) -> dict[str, object]:
    baseline_by_id = {item.question_id_sha256: item for item in baseline}
    candidate_by_id = {item.question_id_sha256: item for item in candidate}
    if set(baseline_by_id) != set(candidate_by_id):
        raise ValueError("paired transition arms contain different case IDs")
    fixes = []
    regressions = []
    unchanged_failures = []
    for case_id in sorted(baseline_by_id):
        before = baseline_by_id[case_id].citation_complete
        after = candidate_by_id[case_id].citation_complete
        if before == 0 and after == 1:
            fixes.append(case_id)
        elif before == 1 and after == 0:
            regressions.append(case_id)
        elif before == 0 and after == 0:
            unchanged_failures.append(case_id)
    return {
        "fix_count": len(fixes),
        "regression_count": len(regressions),
        "unchanged_failure_count": len(unchanged_failures),
        "fixed_case_ids": fixes,
        "regressed_case_ids": regressions,
        "unchanged_failure_case_ids": unchanged_failures,
    }


def _find_forbidden_keys(
    value: object,
    path: tuple[str, ...] = (),
) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = (*path, key)
            if key in FORBIDDEN_PUBLIC_KEYS:
                found.add(".".join(child_path))
            found.update(_find_forbidden_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.update(_find_forbidden_keys(child, (*path, str(index))))
    return found


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and _is_hex(value)


def _is_git_revision(value: object) -> bool:
    return isinstance(value, str) and len(value) in {40, 64} and _is_hex(value)


def _is_hex(value: str) -> bool:
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = verify_public_evidence(
        args.evidence_dir,
        candidate_protocol_path=args.candidate_protocol,
        frozen_protocol_path=args.frozen_protocol,
        expected_code_revision=args.expected_code_revision,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
