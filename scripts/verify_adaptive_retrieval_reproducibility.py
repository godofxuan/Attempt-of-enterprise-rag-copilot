from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from app.external_datasets.wixqa_retrieval import canonical_json_bytes


SCHEMA_VERSION = "adaptive_retrieval_reproducibility_closure_v2"
_PUBLIC_CONFIG_FIELDS = (
    "git_sha",
    "git_dirty",
    "branch",
    "dataset_manifest_sha256",
    "question_ids_sha256",
    "index_manifest_sha256",
    "embedding_model_sha256",
    "assessor_model",
    "ollama_runtime",
    "assessor_generation_options",
    "critical_file_sha256",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare two private adaptive-retrieval diagnostic runs safely."
    )
    parser.add_argument("--first-summary", type=Path, required=True)
    parser.add_argument("--second-summary", type=Path, required=True)
    parser.add_argument("--first-private", type=Path, required=True)
    parser.add_argument("--second-private", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def compare_runs(
    *,
    first_summary: dict[str, Any],
    second_summary: dict[str, Any],
    first_rows: list[dict[str, Any]],
    second_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    first_by_id = _failed_rows_by_question_id(first_rows)
    second_by_id = _failed_rows_by_question_id(second_rows)
    if set(first_by_id) != set(second_by_id):
        raise ValueError("runs do not contain the same baseline-failure question IDs")

    field_counts = {
        field: sum(
            first_by_id[question_id]["public_row"].get(field)
            == second_by_id[question_id]["public_row"].get(field)
            for question_id in first_by_id
        )
        for field in (
            "assessor_input_messages_sha256",
            "assessor_request_sha256",
            "assessor_seed",
            "raw_output_sha256",
            "proposal_sha256",
            "retry_fully_recovered",
        )
    }
    case_count = len(first_by_id)
    provenance_matches = {
        field: first_summary.get(field) == second_summary.get(field)
        for field in _PUBLIC_CONFIG_FIELDS
    }
    repeatability_passed = all(provenance_matches.values()) and all(
        count == case_count for count in field_counts.values()
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "mode": "RETROSPECTIVE_DEVELOPMENT_ONLY_CONSUMED",
        "first_run_id": first_summary.get("run_id"),
        "second_run_id": second_summary.get("run_id"),
        "baseline_failure_case_count": case_count,
        "provenance_matches": provenance_matches,
        "same_input_messages_sha256_count": field_counts[
            "assessor_input_messages_sha256"
        ],
        "same_request_sha256_count": field_counts["assessor_request_sha256"],
        "same_seed_count": field_counts["assessor_seed"],
        "same_raw_output_sha256_count": field_counts["raw_output_sha256"],
        "same_parsed_proposal_sha256_count": field_counts["proposal_sha256"],
        "same_recovery_classification_count": field_counts[
            "retry_fully_recovered"
        ],
        "same_environment_repeatability": "PASS" if repeatability_passed else "FAIL",
        "decision": (
            "REPRODUCIBILITY_CLOSED"
            if repeatability_passed
            else "REPRODUCIBILITY_NOT_CLOSED_ADAPTIVE_EVALUATION_BLOCKED"
        ),
        "claim_boundary": (
            "No raw question, evidence, or model output is published. A FAIL blocks "
            "adaptive-retrieval promotion and causal evaluation; it does not measure "
            "cross-hardware behavior."
        ),
    }
    result["artifact_payload_sha256"] = _sha256_bytes(
        canonical_json_bytes(result)
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    first_summary = _load_json(args.first_summary)
    second_summary = _load_json(args.second_summary)
    first_rows = _load_json(args.first_private)["rows"]
    second_rows = _load_json(args.second_private)["rows"]
    result = compare_runs(
        first_summary=first_summary,
        second_summary=second_summary,
        first_rows=first_rows,
        second_rows=second_rows,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json_bytes(result))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["same_environment_repeatability"] == "PASS" else 1


def _failed_rows_by_question_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for row in rows:
        public_row = row.get("public_row", {})
        if public_row.get("baseline_failed") is True:
            question_id = row.get("question_id")
            if not isinstance(question_id, str) or question_id in result:
                raise ValueError("private rows contain invalid or duplicate question IDs")
            result[question_id] = row
    return result


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
