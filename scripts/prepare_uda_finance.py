from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from app.external_datasets.uda_finance import (
    DEFAULT_PREPARED_ROOT,
    DEFAULT_PROTOCOL_PATH,
    DEFAULT_SOURCE_ROOT,
    extract_selected_pdfs,
    load_uda_finance_protocol,
    load_uda_finance_rows,
    prepare_uda_finance,
    select_uda_finance_cases,
    verify_uda_finance_preparation,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare the pinned UDA FinHybrid company-disjoint corpus."
    )
    parser.add_argument("--qa-path", type=Path, required=True)
    parser.add_argument("--pdf-root", type=Path, required=True)
    parser.add_argument("--archive-path", type=Path)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--prepared-root", type=Path, default=DEFAULT_PREPARED_ROOT)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL_PATH)
    parser.add_argument("--verify-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verify_only:
        manifest = verify_uda_finance_preparation(
            source_root=args.source_root,
            prepared_root=args.prepared_root,
        )
        payload = {"action": "verify", "status": "PASSED", **manifest.model_dump(mode="json")}
    else:
        protocol, _ = load_uda_finance_protocol(args.protocol)
        rows = load_uda_finance_rows(args.qa_path)
        selections = select_uda_finance_cases(
            rows,
            seed=protocol.selection_seed,
            minimum_questions_per_document=protocol.minimum_questions_per_document,
            dev_company_count=protocol.dev_company_count,
            test_company_count=protocol.test_company_count,
            cases_per_document=protocol.cases_per_document,
        )
        if args.archive_path is not None:
            extract_selected_pdfs(
                args.archive_path,
                args.pdf_root,
                sorted({item.doc_name for item in selections}),
            )
        manifest = prepare_uda_finance(
            qa_path=args.qa_path,
            pdf_root=args.pdf_root,
            source_root=args.source_root,
            prepared_root=args.prepared_root,
            protocol_path=args.protocol,
        )
        payload = {"action": "prepare", "status": "PASSED", **manifest.model_dump(mode="json")}
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
