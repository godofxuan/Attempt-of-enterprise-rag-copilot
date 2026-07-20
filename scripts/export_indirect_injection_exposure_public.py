from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from app.evaluation.indirect_injection_dataset import load_security_bundle
from app.evaluation.indirect_injection_exposure_public import (
    export_exposure_public_evidence,
)


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SECURITY_DATA_ROOT = BASE_DIR / "data" / "v2" / "security"
DEFAULT_OUTPUT_ROOT = BASE_DIR / "data" / "v2" / "public"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export content-free R2-S3 exposure evidence."
    )
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--package-name", default="r2_s3_exposure")
    parser.add_argument("--expected-source-run-id", required=True)
    parser.add_argument(
        "--expected-source-manifest-sha256",
        required=True,
    )
    parser.add_argument(
        "--security-data-root",
        type=Path,
        default=DEFAULT_SECURITY_DATA_ROOT,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        bundle = load_security_bundle(args.security_data_root, "dev")
        package = export_exposure_public_evidence(
            args.source_run,
            args.output_root,
            package_name=args.package_name,
            expected_source_manifest_sha256=(
                args.expected_source_manifest_sha256
            ),
            expected_source_run_id=args.expected_source_run_id,
            forbidden_texts=_forbidden_fixture_texts(bundle),
        )
    except FileExistsError as exc:
        _write_json(
            sys.stderr,
            {
                "error_type": type(exc).__name__,
                "message": str(exc),
                "status": "OUTPUT_ERROR",
            },
        )
        return 1
    except (FileNotFoundError, OSError, ValueError) as exc:
        _write_json(
            sys.stderr,
            {
                "error_type": type(exc).__name__,
                "message": str(exc),
                "status": "EXPORT_FAILED",
            },
        )
        return 2
    _write_json(
        sys.stdout,
        {
            "package": package.as_posix(),
            "package_name": args.package_name,
            "source_run_id": args.expected_source_run_id,
            "status": "EXPORTED",
        },
    )
    return 0


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


if __name__ == "__main__":
    raise SystemExit(main())

