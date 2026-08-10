from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.evaluation.wixqa_multidoc_attribution import (
    MultiDocAttributionCase,
    aggregate_attribution_cases,
)


EXPECTED_FILES = (
    "aggregate_v1.json",
    "case_matrix_v1.json",
    "protocol_v1.json",
)
FORBIDDEN_PUBLIC_KEYS = {
    "answer",
    "answer_text",
    "controller_search_queries",
    "full_document_content",
    "model_raw_output",
    "prompt",
    "question",
    "question_text",
    "raw_answer",
    "raw_output",
}
ALLOWED_PUBLIC_KEY_PATHS = {
    ("required_aspects_distribution", "answer"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify public WixQA multi-document attribution evidence."
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("docs/multidoc_attribution/evidence"),
    )
    parser.add_argument("--expected-code-revision")
    return parser


def verify_public_evidence(
    evidence_dir: Path,
    *,
    expected_code_revision: str | None = None,
) -> dict[str, object]:
    root = evidence_dir.resolve()
    missing = [name for name in EXPECTED_FILES if not (root / name).is_file()]
    if missing:
        raise ValueError(f"missing public evidence files: {missing}")

    aggregate_bytes = (root / "aggregate_v1.json").read_bytes()
    case_bytes = (root / "case_matrix_v1.json").read_bytes()
    protocol_bytes = (root / "protocol_v1.json").read_bytes()
    aggregate = json.loads(aggregate_bytes)
    case_payload = json.loads(case_bytes)
    protocol = json.loads(protocol_bytes)

    for name, payload in (
        ("aggregate", aggregate),
        ("case_matrix", case_payload),
        ("protocol", protocol),
    ):
        forbidden = sorted(_find_forbidden_keys(payload))
        if forbidden:
            raise ValueError(f"{name} exposes forbidden public keys: {forbidden}")

    if case_payload.get("schema_version") != "wixqa_multidoc_attribution_v1":
        raise ValueError("case matrix schema version mismatch")
    cases = [
        MultiDocAttributionCase.model_validate(item)
        for item in case_payload.get("cases", [])
    ]
    if len(cases) != 20 or case_payload.get("case_count") != len(cases):
        raise ValueError("case matrix must contain exactly 20 cases")
    case_ids = [item.case_id for item in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case IDs must be unique")

    recomputed = aggregate_attribution_cases(cases)
    mismatches = [
        key for key, expected in recomputed.items() if aggregate.get(key) != expected
    ]
    if mismatches:
        raise ValueError(f"aggregate does not recompute from cases: {mismatches}")

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
    if not _is_sha256(code_revision):
        raise ValueError("code revision must be a full SHA-1 or SHA-256 hex ID")
    if expected_code_revision and code_revision != expected_code_revision:
        raise ValueError("code revision does not match the expected revision")

    if aggregate.get("case_matrix_sha256") != _sha256(case_bytes):
        raise ValueError("case matrix hash mismatch")
    if aggregate.get("protocol_sha256") != _sha256(protocol_bytes):
        raise ValueError("protocol hash mismatch")
    if not _is_exact_sha256(aggregate.get("private_details_sha256")):
        raise ValueError("private details hash is missing or malformed")
    if protocol.get("normal_serving_behavior_changed") is not False:
        raise ValueError("protocol must state that serving behavior was unchanged")
    if protocol.get("mode") != "RETROSPECTIVE_DEVELOPMENT_ONLY_CONSUMED":
        raise ValueError("protocol cohort-consumption mode mismatch")
    if aggregate.get("status") != "ATTRIBUTION_COMPLETE_NO_OPTIMIZATION":
        raise ValueError("attribution completion gate did not pass")

    return {
        "status": "VERIFIED",
        "run_id": next(iter(run_ids)),
        "code_revision": code_revision,
        "case_count": len(cases),
        "unknown_count": aggregate["unknown_count"],
        "case_matrix_sha256": _sha256(case_bytes),
        "protocol_sha256": _sha256(protocol_bytes),
        "aggregate_sha256": _sha256(aggregate_bytes),
    }


def _find_forbidden_keys(
    value: object,
    path: tuple[str, ...] = (),
) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = (*path, key)
            if (
                key in FORBIDDEN_PUBLIC_KEYS
                and child_path not in ALLOWED_PUBLIC_KEY_PATHS
            ):
                found.add(".".join(child_path))
            found.update(_find_forbidden_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.update(_find_forbidden_keys(child, (*path, str(index))))
    return found


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_exact_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and _is_hex(value)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) in {40, 64}
        and _is_hex(value)
    )


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
        expected_code_revision=args.expected_code_revision,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
