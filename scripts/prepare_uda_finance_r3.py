from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from app.external_datasets.uda_finance import extract_selected_pdfs, load_uda_finance_rows
from app.external_datasets.uda_finance_r3 import (
    R3_PREPARED_ROOT,
    R3_PRIVATE_ROOT,
    R3_PROTOCOL_PATH,
    R3_SOURCE_ROOT,
    load_uda_finance_r3_protocol,
    prepare_uda_finance_r3,
    verify_r3_protocol_selection,
    verify_uda_finance_r3_preparation,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare the frozen UDA FinHybrid R3 cohort.")
    parser.add_argument("--qa-path", type=Path, required=True)
    parser.add_argument("--archive-path", type=Path)
    parser.add_argument("--pdf-root", type=Path, default=R3_PRIVATE_ROOT / "selected_pdfs")
    parser.add_argument("--source-root", type=Path, default=R3_SOURCE_ROOT)
    parser.add_argument("--prepared-root", type=Path, default=R3_PREPARED_ROOT)
    parser.add_argument("--protocol", type=Path, default=R3_PROTOCOL_PATH)
    parser.add_argument("--verify-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verify_only:
        manifest = verify_uda_finance_r3_preparation(
            source_root=args.source_root,
            prepared_root=args.prepared_root,
        )
        payload = {"action": "verify", "status": "PASSED", **manifest.model_dump(mode="json")}
    else:
        protocol, _ = load_uda_finance_r3_protocol(args.protocol)
        rows = load_uda_finance_rows(args.qa_path)
        selections, _ = verify_r3_protocol_selection(protocol, rows)
        wanted = sorted({item.doc_name for item in selections})
        pdf_root = args.pdf_root.resolve()
        missing = [name for name in wanted if not (pdf_root / f"{name}.pdf").is_file()]
        if missing:
            if args.archive_path is None:
                raise FileNotFoundError("R3 selected PDFs are missing; provide --archive-path")
            if pdf_root.exists() and any(pdf_root.iterdir()):
                raise FileExistsError("R3 selected PDF directory is partial; refusing mixed extraction")
            extract_selected_pdfs(args.archive_path, pdf_root, wanted)
        manifest = prepare_uda_finance_r3(
            qa_path=args.qa_path,
            pdf_root=pdf_root,
            source_root=args.source_root,
            prepared_root=args.prepared_root,
            protocol_path=args.protocol,
        )
        verified = verify_uda_finance_r3_preparation(
            source_root=args.source_root,
            prepared_root=args.prepared_root,
        )
        if manifest != verified:
            raise AssertionError("R3 preparation changed during verification")
        payload = {"action": "prepare", "status": "PASSED", **manifest.model_dump(mode="json")}
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
