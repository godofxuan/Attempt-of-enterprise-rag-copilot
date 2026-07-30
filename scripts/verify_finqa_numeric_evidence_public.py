try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
from pathlib import Path

from app.external_datasets.finqa_numeric_evidence_audit import (
    FinQANumericEvidenceAuditSummary,
)
from app.external_datasets.finqa_numeric_evidence_protocol import (
    load_numeric_evidence_protocol,
)
from app.external_datasets.finqa_numeric_evidence_protocol_erratum import (
    FinQANumericEvidenceProtocolErratum,
)
from app.external_datasets.finqa_typed_retrospective import (
    canonical_json_bytes,
)
from scripts.audit_finqa_numeric_evidence import (
    DEFAULT_ERRATUM,
    DEFAULT_OUT_ROOT,
    DEFAULT_PROTOCOL,
    DEFAULT_PUBLIC_OUTPUT,
)


_EXPECTED_KEYS = {
    "schema_version",
    "claim_label",
    "run_id",
    "protocol_id",
    "protocol_sha256",
    "erratum_id",
    "erratum_sha256",
    "source_run_id",
    "private_manifest_sha256",
    "private_details_sha256",
    "summary",
    "content_exclusions",
    "limitations",
}
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
            key
            for child in value.values()
            for key in _walk_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _walk_keys(child)}
    return set()


def verify_public_evidence(
    path: Path,
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    erratum_path: Path = DEFAULT_ERRATUM,
    private_root: Path | None = DEFAULT_OUT_ROOT,
) -> FinQANumericEvidenceAuditSummary:
    content = path.resolve().read_bytes()
    payload = json.loads(
        content.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    if not isinstance(payload, dict) or set(payload) != _EXPECTED_KEYS:
        raise ValueError("numeric evidence public artifact has invalid keys")
    if content != canonical_json_bytes(payload, newline=True):
        raise ValueError("numeric evidence public artifact is not canonical JSON")
    if _walk_keys(payload["summary"]) & _FORBIDDEN_KEYS:
        raise ValueError("numeric evidence public summary contains private keys")

    protocol, protocol_sha256 = load_numeric_evidence_protocol(protocol_path)
    erratum_bytes = erratum_path.resolve().read_bytes()
    erratum = FinQANumericEvidenceProtocolErratum.model_validate_json(
        erratum_bytes
    )
    if (
        payload["schema_version"]
        != "finqa_numeric_evidence_calibration_public_v1"
        or payload["claim_label"] != protocol.claim_label
        or payload["protocol_id"] != protocol.protocol_id
        or payload["protocol_sha256"] != protocol_sha256
        or payload["erratum_id"] != erratum.erratum_id
        or payload["erratum_sha256"]
        != hashlib.sha256(erratum_bytes).hexdigest()
    ):
        raise ValueError("numeric evidence public source bindings are invalid")
    summary = FinQANumericEvidenceAuditSummary.model_validate(payload["summary"])
    if (
        summary.decision != "INPUT_GATE_PASSED"
        or summary.internal_validation_status != "NOT_RUN"
        or summary.frozen_test_status != "UNTOUCHED"
        or summary.model_call_count != 0
    ):
        raise ValueError("numeric evidence public claim boundary is invalid")

    if private_root is not None:
        run_dir = private_root.resolve() / str(payload["run_id"])
        if run_dir.exists():
            manifest_bytes = (run_dir / "manifest.json").read_bytes()
            details_bytes = (run_dir / "details.jsonl").read_bytes()
            manifest = json.loads(manifest_bytes)
            if (
                hashlib.sha256(manifest_bytes).hexdigest()
                != payload["private_manifest_sha256"]
                or hashlib.sha256(details_bytes).hexdigest()
                != payload["private_details_sha256"]
                or manifest["summary"] != payload["summary"]
            ):
                raise ValueError("numeric evidence private bindings are invalid")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the redacted Gate E3 public evidence artifact."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_PUBLIC_OUTPUT)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--erratum", type=Path, default=DEFAULT_ERRATUM)
    parser.add_argument("--private-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--public-only", action="store_true")
    args = parser.parse_args(argv)
    summary = verify_public_evidence(
        args.input,
        protocol_path=args.protocol,
        erratum_path=args.erratum,
        private_root=None if args.public_only else args.private_root,
    )
    print(
        f"verified {args.input.resolve()} "
        f"decision={summary.decision} cases={summary.case_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
