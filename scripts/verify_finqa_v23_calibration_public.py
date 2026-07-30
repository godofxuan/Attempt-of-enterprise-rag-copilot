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
    load_finqa_split,
)
from app.external_datasets.finqa_typed_retrospective import (
    canonical_json_bytes,
)
from app.external_datasets.finqa_v23_calibration_protocol import (
    load_v23_calibration_protocol,
)
from app.external_datasets.finqa_v23_public import (
    FinQAV23PublicEvidence,
    build_v23_public_evidence,
)
from scripts.publish_finqa_v23_calibration import (
    DEFAULT_E3_PUBLIC,
    DEFAULT_OUTPUT,
    DEFAULT_PROTOCOL,
    DEFAULT_RUN_ROOT,
)
from scripts.verify_finqa_numeric_evidence_public import (
    verify_public_evidence as verify_e3_public_evidence,
)


_EXPECTED_KEYS = set(FinQAV23PublicEvidence.model_fields)
_FORBIDDEN_KEYS = {
    "case_id",
    "case_ids",
    "question",
    "answer",
    "gold_program",
    "gold_program_text",
    "evidence_text",
    "candidate_id",
    "candidate_ids",
    "generated_program_text",
}


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _walk_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key for child in value.values() for key in _walk_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _walk_keys(child)}
    return set()


def verify_public_evidence(
    path: Path,
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    e3_public_path: Path = DEFAULT_E3_PUBLIC,
    dataset_path: Path = DEFAULT_SOURCE_ROOT / "dataset" / "dev.json",
    private_root: Path | None = DEFAULT_RUN_ROOT,
) -> FinQAV23PublicEvidence:
    content = path.resolve().read_bytes()
    payload = json.loads(
        content.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    if not isinstance(payload, dict) or set(payload) != _EXPECTED_KEYS:
        raise ValueError("v2.3 public artifact has invalid keys")
    if content != canonical_json_bytes(payload, newline=True):
        raise ValueError("v2.3 public artifact is not canonical JSON")
    if _walk_keys(payload) & _FORBIDDEN_KEYS:
        raise ValueError("v2.3 public artifact contains private keys")
    evidence = FinQAV23PublicEvidence.model_validate(payload)
    protocol, protocol_sha256 = load_v23_calibration_protocol(protocol_path)
    if (
        evidence.protocol_id != protocol.protocol_id
        or evidence.protocol_sha256 != protocol_sha256
        or evidence.dataset_sha256 != protocol.dataset_sha256
        or evidence.selected_case_ids_sha256
        != protocol.calibration_case_ids_sha256
        or evidence.answer_model.name != protocol.answer_model_name
        or evidence.answer_model.sha256 != protocol.answer_model_sha256
    ):
        raise ValueError("v2.3 public protocol bindings are invalid")

    e3_summary = verify_e3_public_evidence(
        e3_public_path,
        private_root=None,
    )
    if (
        evidence.diagnostics.input_complete_case_count
        != e3_summary.views["v2_closure_post"].complete_case_count
    ):
        raise ValueError("v2.3 public input diagnostic is invalid")

    if private_root is not None:
        cases, _ = load_finqa_split(
            dataset_path,
            expected_sha256=FINQA_DEV_SHA256,
        )
        expected = build_v23_public_evidence(
            run_dir=private_root / evidence.run_id,
            protocol=protocol,
            protocol_sha256=protocol_sha256,
            cases_by_id={case.id: case for case in cases},
            input_complete_case_count=(
                e3_summary.views[
                    "v2_closure_post"
                ].complete_case_count
            ),
        )
        if evidence != expected:
            raise ValueError("v2.3 public artifact does not match private run")
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify redacted FinQA Gate E4 evidence."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--e3-public", type=Path, default=DEFAULT_E3_PUBLIC)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_SOURCE_ROOT / "dataset" / "dev.json",
    )
    parser.add_argument("--private-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--public-only", action="store_true")
    args = parser.parse_args(argv)
    evidence = verify_public_evidence(
        args.input,
        protocol_path=args.protocol,
        e3_public_path=args.e3_public,
        dataset_path=args.dataset,
        private_root=None if args.public_only else args.private_root,
    )
    print(
        f"verified {args.input.resolve()} "
        f"decision={evidence.summary.decision} "
        f"strict={evidence.summary.b1_v23_intervention.execution_accuracy:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
