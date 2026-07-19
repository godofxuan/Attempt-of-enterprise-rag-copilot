from __future__ import annotations

import argparse
from pathlib import Path

from app.evaluation.indirect_injection_dataset import load_security_bundle
from app.evaluation.indirect_injection_public_writer import (
    FORMAL_D7_MANIFEST_SHA256,
    FORMAL_D7_PACKAGE_NAME,
    FORMAL_D7_RUN_ID,
    export_public_evidence,
)


BASE_DIR = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export the frozen D7 run as redacted public evidence."
    )
    parser.add_argument(
        "--source-run",
        type=Path,
        default=BASE_DIR / "security_runs" / FORMAL_D7_RUN_ID,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=BASE_DIR / "data" / "v2" / "public",
    )
    parser.add_argument("--package-name", default=FORMAL_D7_PACKAGE_NAME)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bundle = load_security_bundle(BASE_DIR / "data" / "v2" / "security", "test")
    output = export_public_evidence(
        args.source_run,
        args.output_root,
        package_name=args.package_name,
        expected_source_manifest_sha256=FORMAL_D7_MANIFEST_SHA256,
        expected_source_run_id=FORMAL_D7_RUN_ID,
        forbidden_texts=_forbidden_texts(bundle),
    )
    print(output)
    return 0


def _forbidden_texts(bundle: object) -> tuple[str, ...]:
    values: set[str] = set()
    for case in bundle.dataset.cases:
        values.add(case.question)
        values.add(case.trace_canary)
        if case.document_canary:
            values.add(case.document_canary)
    for fixture in bundle.fixture_manifest.cases:
        values.update(fixture.fact_texts.values())
        for candidate in fixture.candidates:
            values.update((candidate.matched_text, candidate.context_text))
        for opened in fixture.open_results:
            values.add(opened.content)
    return tuple(sorted(values))


if __name__ == "__main__":
    raise SystemExit(main())
