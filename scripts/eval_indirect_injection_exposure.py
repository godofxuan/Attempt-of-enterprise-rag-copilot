from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from pydantic import ValidationError

from app.evaluation.indirect_injection_exposure import (
    COUNTERFACTUAL_DEPTHS,
    ExposureEvidenceError,
    REPLAY_IMPLEMENTATION_DEPENDENCIES,
    analyze_exposure,
    load_exposure_inputs,
)
from app.evaluation.indirect_injection_exposure_writer import (
    ExposureRunManifest,
    publish_exposure_run,
)


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SECURITY_DATA_ROOT = BASE_DIR / "data" / "v2" / "security"
DEFAULT_OUTPUT_ROOT = BASE_DIR / "exposure_runs"
DEFAULT_EXPECTED_SOURCE_MANIFEST_SHA256 = (
    "3fe51ea7e404d7d1c09711b14f422b92b2474df7148e4f15df1e949081f5586e"
)
GUARD_RULESET_PATH = "app/security/retrieved_content.py"
EXPOSURE_EVALUATOR_PATH = "app/evaluation/indirect_injection_exposure.py"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate and publish immutable R2-S3 exposure evidence."
    )
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument(
        "--security-data-root",
        type=Path,
        default=DEFAULT_SECURITY_DATA_ROOT,
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--expected-source-manifest-sha256",
        default=DEFAULT_EXPECTED_SOURCE_MANIFEST_SHA256,
    )
    parser.add_argument(
        "--created-at-utc",
        help="Deterministic UTC timestamp override for tests.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        created_at = _created_at_utc(args.created_at_utc)
        inputs = load_exposure_inputs(
            args.source_run,
            security_data_root=args.security_data_root,
            expected_manifest_sha256=args.expected_source_manifest_sha256,
        )
        result = analyze_exposure(inputs)
        guard_path = BASE_DIR / GUARD_RULESET_PATH
        evaluator_path = BASE_DIR / EXPOSURE_EVALUATOR_PATH
        manifest = ExposureRunManifest(
            schema_version="indirect_injection_exposure_run_manifest_v2",
            producer="enterprise_agentic_rag_v2",
            run_id=args.run_id,
            created_at_utc=created_at,
            source=result.source,
            guard_ruleset_path=GUARD_RULESET_PATH,
            guard_ruleset_sha256=_sha256(guard_path),
            evaluator_path=EXPOSURE_EVALUATOR_PATH,
            evaluator_sha256=_sha256(evaluator_path),
            replay_dependencies=REPLAY_IMPLEMENTATION_DEPENDENCIES,
            unit_evidence_sha256=result.unit_evidence_sha256,
            verification_inputs_sha256=(
                result.verification_inputs_sha256
            ),
            counterfactual_depths=COUNTERFACTUAL_DEPTHS,
            decision=result.decision,
            case_count=36,
            attack_case_count=24,
            benign_case_count=12,
            attack_unit_count=28,
            benign_unit_count=32,
            unguarded_path_findings=result.unguarded_path_findings,
            artifacts={},
            limitations=result.limitations,
        )
        output = publish_exposure_run(
            args.out_dir,
            manifest=manifest,
            result=result,
            commands=_commands(args),
            test_output=_test_output(result),
            forbidden_texts=_forbidden_fixture_texts(inputs.bundle),
        )
    except OSError as exc:
        _write_json(
            sys.stderr,
            {
                "error_type": type(exc).__name__,
                "message": str(exc),
                "status": "OUTPUT_ERROR",
            },
        )
        return 1
    except (
        ExposureEvidenceError,
        ValidationError,
        ValueError,
    ) as exc:
        _write_json(
            sys.stderr,
            {
                "decision": "INVALID_EVIDENCE",
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
        )
        return 2

    _write_json(
        sys.stdout,
        {
            "decision": result.decision,
            "output_dir": output.as_posix(),
            "run_id": manifest.run_id,
            "source_run_id": result.source.run_id,
            "status": "PUBLISHED",
        },
    )
    return 0


def _created_at_utc(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("created_at_utc must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("created_at_utc must be timezone-aware UTC")
    return parsed


def _forbidden_fixture_texts(bundle) -> tuple[str, ...]:
    values: set[str] = set()
    for case in bundle.dataset.cases:
        values.add(case.question)
        if case.document_canary:
            values.add(case.document_canary)
        values.add(case.trace_canary)
    for fixture in bundle.fixture_manifest.cases:
        values.update(fixture.fact_texts.values())
        for candidate in fixture.candidates:
            values.update((candidate.matched_text, candidate.context_text))
            if candidate.document_title:
                values.add(candidate.document_title)
            values.add(candidate.source_path)
            values.update(candidate.section_path)
            values.add(candidate.version)
        for item in fixture.open_results:
            values.update((item.content, item.source_path))
    return tuple(sorted(value for value in values if value))


def _commands(args: argparse.Namespace) -> str:
    parts = (
        "python",
        "-m",
        "scripts.eval_indirect_injection_exposure",
        "--source-run",
        _safe_display_path(args.source_run),
        "--security-data-root",
        _safe_display_path(args.security_data_root),
        "--out-dir",
        _safe_display_path(args.out_dir),
        "--run-id",
        args.run_id,
        "--expected-source-manifest-sha256",
        args.expected_source_manifest_sha256,
    )
    suffix = (
        ("--created-at-utc", args.created_at_utc)
        if args.created_at_utc is not None
        else ()
    )
    return " ".join((*parts, *suffix)) + "\n"


def _safe_display_path(value: Path) -> str:
    resolved = value.resolve()
    try:
        return resolved.relative_to(BASE_DIR).as_posix()
    except ValueError:
        return f"<external>/{resolved.name}"


def _test_output(result) -> str:
    return (
        "source_run_verified=true\n"
        f"source_run_id={result.source.run_id}\n"
        f"source_manifest_sha256={result.source.manifest_sha256}\n"
        f"attack_unit_count={result.summary.attack_unit_count}\n"
        f"decision={result.decision}\n"
    )


def _write_json(stream, payload: dict[str, object]) -> None:
    stream.write(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
