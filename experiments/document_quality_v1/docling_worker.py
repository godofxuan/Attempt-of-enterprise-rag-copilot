"""Optional PDF experiment worker; never imported by the production registry.

One file, pinned local artifacts, Windows job memory cap, no Python socket egress.
The outer launcher enforces wall time. This is not a container/OS network sandbox.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import time
from pathlib import Path


def verify_models(root: Path):
    lock = root / "MODEL_LOCK.json"
    data = json.loads(lock.read_text(encoding="utf-8"))
    if not data.get("files"):
        raise ValueError("model_lock_empty")
    for item in data["files"]:
        path = (root / item["path"]).resolve()
        path.relative_to(root.resolve())
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("model_hash_mismatch")
    return hashlib.sha256(lock.read_bytes()).hexdigest()


def adapt_document(document):
    from app.domain.documents import ParsedSection, ParsedTable, ParseResult, SourceLocator

    sections, tables, text = [], [], []
    for item, _ in document.iterate_items():
        if not getattr(item, "prov", None):
            if getattr(item, "text", ""):
                raise ValueError("docling_item_missing_provenance")
            continue
        pages = sorted({p.page_no for p in item.prov})
        locator = SourceLocator(kind="page", start=pages[0], end=pages[-1], label=item.self_ref)
        if hasattr(item, "data") and hasattr(item.data, "table_cells"):
            data = item.data
            if any(c.row_span != 1 or c.col_span != 1 or c.row_section for c in data.table_cells):
                raise ValueError("docling_merged_cells_require_review")
            if len(pages) != 1:
                raise ValueError("docling_multi_page_table_requires_review")
            grid = data.grid
            if (
                len(grid) < 2
                or not grid[0]
                or not all(c.column_header and c.text.strip() for c in grid[0])
            ):
                raise ValueError("docling_header_not_explicit")
            if any(c.column_header for row in grid[1:] for c in row):
                raise ValueError("docling_multiple_header_rows_require_review")
            headers = [c.text for c in grid[0]]
            rows = [[c.text for c in row] for row in grid[1:]]
            table = ParsedTable(
                table_id=f"table-{len(tables) + 1}",
                headers=headers,
                rows=rows,
                locator=locator,
                caption=item.caption_text(document) or None,
            )
            tables.append(table)
            text.append("\n".join([" | ".join(headers), *(" | ".join(row) for row in rows)]))
        elif getattr(item, "text", "").strip():
            # Footer/header removal is restricted to explicit layout labels. Raw JSON is retained.
            if str(item.label.value) in {"page_header", "page_footer"}:
                continue
            value = item.text
            sections.append(
                ParsedSection(
                    heading="PDF content",
                    level=0,
                    path=[document.name],
                    text=value,
                    locator=locator,
                )
            )
            text.append(value)
    return ParseResult(
        text="\n\n".join(text),
        sections=sections,
        tables=tables,
        source_location=document.name,
        parser_name="docling-pdf-experiment",
        parser_version="2.126.0-dq1",
        parse_warnings=[],
    )


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--input", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--models", type=Path, required=True)
    args = cli.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    report = {"status": "STARTED"}
    try:
        report["model_lock_sha256"] = verify_models(args.models)
        if os.name != "nt":
            raise RuntimeError("memory_cap_not_implemented_on_this_platform")
        import win32api
        import win32job

        job = win32job.CreateJobObject(None, None)
        limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        limits["BasicLimitInformation"]["LimitFlags"] = (
            win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY | win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        limits["ProcessMemoryLimit"] = 8 * 1024**3
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        win32job.AssignProcessToJobObject(job, win32api.GetCurrentProcess())
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["DOCLING_ARTIFACTS_PATH"] = str(args.models.resolve())

        def no_connect(*args, **kwargs):
            raise RuntimeError("docling_worker_egress_blocked")

        socket.socket.connect = no_connect
        socket.socket.connect_ex = no_connect
        from pypdf import PdfReader

        reader = PdfReader(args.input)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 30:
            raise ValueError("pdf_page_or_encryption_budget")
        for page in reader.pages:
            if float(page.mediabox.width) * float(page.mediabox.height) * 9 > 20_000_000:
                raise ValueError("pdf_render_pixel_budget")
        from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        options = PdfPipelineOptions(
            artifacts_path=args.models.resolve(),
            document_timeout=120,
            enable_remote_services=False,
            allow_external_plugins=False,
            ocr_options=RapidOcrOptions(backend="torch", lang=["en"]),
            accelerator_options=AcceleratorOptions(device=AcceleratorDevice.CPU, num_threads=2),
            ocr_batch_size=1,
            layout_batch_size=1,
            table_batch_size=1,
        )
        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )
        converter.initialize_pipeline(InputFormat.PDF)
        (args.output / "READY.json").write_text(
            json.dumps({"init_ms": (time.perf_counter() - started) * 1000}), encoding="utf-8"
        )
        converted = converter.convert(args.input, max_num_pages=30, max_file_size=20 * 1024**2)
        (args.output / "raw_docling.json").write_text(
            converted.document.model_dump_json(indent=2), encoding="utf-8"
        )
        if str(converted.status.value) != "success" or converted.errors:
            raise ValueError("docling_partial_conversion")
        adapted = adapt_document(converted.document)
        report.update(status="PARSED", result=adapted.model_dump(mode="json"))
        report["peak_memory_bytes"] = win32job.QueryInformationJobObject(
            job, win32job.JobObjectExtendedLimitInformation
        )["PeakProcessMemoryUsed"]
    except Exception as exc:
        report.update(status="BLOCKED_OR_REJECTED", error=repr(exc))
    report["elapsed_ms"] = (time.perf_counter() - started) * 1000
    (args.output / "RESULT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
