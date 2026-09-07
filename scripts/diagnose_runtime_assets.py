"""Bounded CPU-only diagnostics; never import the application or read QA labels.

Inputs are explicitly selected index records and public exposure evidence. Outputs
contain aggregates and byte hashes, never document text, IDs, or warning messages.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import sys
import time
from collections import Counter
from pathlib import Path

MIB = 1024**2
VECTOR_CAP = 512 * MIB
RESIDENT_MARGIN = 1024 * MIB
ROOT = Path(__file__).resolve().parents[1]
WIX = Path(
    ".private/external/wixqa_final_lf/indexes/versions/wixqa-official-lf-bge-m3-final-67c7e55"
)
FIN = Path(
    ".private/external_datasets/financebench/indexes/versions/financebench-bge-m3-heading-1800-v1"
)
EVIDENCE = (
    "docs/adaptive_retrieval_v3/DATASET_LEDGER.md",
    "docs/adaptive_retrieval_v3/ASSESSOR_RESULTS.md",
    "docs/adaptive_retrieval_v3/FINAL_DECISION.md",
    "docs/adaptive_retrieval_v3/evidence/g1-assessor-run1-e304212-summary.json",
    "docs/external_datasets/uda_finance_protocol.md",
    "docs/r5/ENGINEERING_JOURNAL.md",
    "docs/external_datasets/evidence/finqa_admitted_context_protocol_v1.json",
    "docs/quality/CODEX_HANDOFF.json",
)


def identity(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(MIB), b""):
            digest.update(block)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def memory() -> dict:
    """Use Windows counters without adding a monitoring dependency."""
    if sys.platform != "win32":
        raise RuntimeError("Memory preflight is implemented for this Windows host only")

    class Status(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong)
            for name in (
                "total",
                "available",
                "page_total",
                "page_available",
                "virtual_total",
                "virtual_available",
                "extended",
            )
        ]

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak",
                "rss",
                "pool_peak",
                "pool",
                "nonpool_peak",
                "nonpool",
                "page",
                "page_peak",
            )
        ]

    status = Status()
    status.length = ctypes.sizeof(status)
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    if not kernel.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not psapi.GetProcessMemoryInfo(
        kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return {
        "available_bytes": status.available,
        "total_bytes": status.total,
        "rss_bytes": counters.rss,
        "process_peak_rss_bytes": counters.peak,
    }


def budget(n: int, dimension: int, available: int) -> dict:
    if n <= 0 or dimension != 1024:
        raise ValueError("Positive scale and dimension 1024 required")
    storage = n * dimension * 4
    # Single index allocation plus a <=4 MiB fill buffer. Reserve extra scratch
    # and a conservative second storage allowance against native allocation risk.
    required = 2 * storage + 64 * MIB + RESIDENT_MARGIN
    return {
        "vector_bytes": storage,
        "vector_cap_bytes": VECTOR_CAP,
        "required_available_bytes": required,
        "available_bytes": available,
        "resident_margin_bytes": RESIDENT_MARGIN,
        "allowed": storage + 4 * MIB < VECTOR_CAP and available >= required,
    }


def records(path: Path):
    """Stream JSONL or a JSON array with a bounded single-record buffer."""
    limit = 16 * MIB
    with path.open(encoding="utf-8") as stream:
        if path.suffix == ".jsonl":
            while line := stream.readline(limit + 1):
                if len(line) > limit:
                    raise ValueError("Record exceeds bounded reader limit")
                if line.strip():
                    yield json.loads(line)
            return
        decoder = json.JSONDecoder()
        buffer = ""
        eof = False

        def refill():
            nonlocal buffer, eof
            block = stream.read(65536)
            eof = not block
            buffer += block
            if len(buffer) > limit:
                raise ValueError("Record exceeds bounded reader limit")

        def whitespace():
            nonlocal buffer
            buffer = buffer.lstrip()
            while not buffer and not eof:
                refill()
                buffer = buffer.lstrip()

        whitespace()
        if not buffer.startswith("["):
            raise ValueError("Expected a record array")
        buffer = buffer[1:]
        first = True
        while True:
            whitespace()
            if buffer.startswith("]"):
                buffer = buffer[1:]
                whitespace()
                if buffer:
                    raise ValueError("Trailing JSON data")
                return
            if not first:
                if not buffer.startswith(","):
                    raise ValueError("Missing record separator")
                buffer = buffer[1:]
                whitespace()
            while True:
                try:
                    row, end = decoder.raw_decode(buffer)
                    break
                except json.JSONDecodeError:
                    if eof:
                        raise ValueError("Truncated or invalid record array") from None
                    refill()
            buffer = buffer[end:]
            first = False
            yield row


def coverage(rows, kind: str) -> dict:
    counts = Counter()
    formats = Counter()
    locators = Counter()
    warnings = Counter()
    parsers = Counter()
    # Only known schema enums are emitted; arbitrary metadata is not public text.
    safe_formats = {"pdf", "docx", "txt", "md", "csv", "xlsx", "html", "eml", "jsonl"}
    safe_locators = {"document", "character", "line", "page", "paragraph", "row", "cell"}
    for row in rows:
        counts["records"] += 1
        fmt = str(row.get("format", "unknown")).lower()
        formats[fmt if fmt in safe_formats else "unknown"] += 1
        counts["empty_record_text"] += not bool(str(row.get("text", "")).strip())
        if kind == "documents":
            recorded_pages = set()
            text_pages = set()
            empty_pages = set()
            boundary_lines = Counter()
            if "parse_warnings" not in row:
                counts["warning_field_missing"] += 1
            warning_rows = row.get("parse_warnings", [])
            counts["documents_with_warnings"] += bool(warning_rows)
            counts["warning_records"] += len(warning_rows)
            for warning in warning_rows:
                code = warning.get("code")
                warnings[code if code in {"empty_page", "empty_document"} else "other"] += 1
                locator = warning.get("locator") or {}
                page = locator.get("start")
                if locator.get("kind") == "page" and isinstance(page, int) and page > 0:
                    recorded_pages.add(page)
                    if code == "empty_page":
                        empty_pages.add(page)
            counts["tables"] += len(row.get("tables", []))
            counts["tables_without_headers"] += sum(
                not bool(t.get("headers")) for t in row.get("tables", [])
            )
            parser = str(row.get("parser_name", "unknown"))
            parsers[hashlib.sha256(parser.encode()).hexdigest()] += 1
            sections = row.get("sections", [])
            counts["sections"] += len(sections)
            for section in sections:
                loc = section.get("locator", {}).get("kind", "unknown")
                locators[loc if loc in safe_locators else "unknown"] += 1
                if loc == "page":
                    counts["nonempty_page_sections"] += bool(section.get("text", "").strip())
                    counts["empty_page_sections"] += not bool(section.get("text", "").strip())
                    page = section["locator"].get("start")
                    if isinstance(page, int) and page > 0:
                        recorded_pages.add(page)
                        if section.get("text", "").strip():
                            text_pages.add(page)
                    lines = [
                        line.strip()
                        for line in section.get("text", "").splitlines()
                        if line.strip()
                    ]
                    if lines:
                        for position, line in (("first", lines[0]), ("last", lines[-1])):
                            if len(line) <= 160:
                                boundary_lines[
                                    (position, hashlib.sha256(line.encode()).digest())
                                ] += 1
            counts["recorded_distinct_pages"] += len(recorded_pages)
            counts["recorded_distinct_text_pages"] += len(text_pages)
            counts["recorded_distinct_empty_warning_pages"] += len(empty_pages)
            counts["recorded_page_number_gaps"] += max(recorded_pages, default=0) - len(
                recorded_pages
            )
            repeats = [n for n in boundary_lines.values() if n >= 3]
            counts["documents_with_repeated_boundary_candidates"] += bool(repeats)
            counts["repeated_boundary_candidate_occurrences"] += sum(repeats)
        else:
            loc = row.get("locator", {}).get("kind", "unknown")
            locators[loc if loc in safe_locators else "unknown"] += 1
            counts["table_chunks"] += row.get("kind") == "table"
    return {
        "counts": dict(counts),
        "formats": dict(formats),
        "locators": dict(locators),
        "warning_codes": dict(warnings),
        "parser_name_hash_counts": dict(parsers),
        "coverage_status": "RECORDED_STRUCTURE_ONLY_NOT_ALL_CONTENT_USABLE",
        "unknown": [
            "raw_page_denominator",
            "failed_imports_not_in_index",
            "scan_and_ocr_coverage",
            "table_fact_recovery",
            "confirmed_repeated_headers_footers_loss",
            "cross_chunk_header_retention",
        ],
    }


def full_reference(index, query, visible, k):
    scores, ids = index.search(query, index.ntotal)
    allowed = set(map(int, visible))
    result = []
    # Match the existing dense full-ranking then ACL-filter loop, including ties.
    for ident, score in zip(ids[0].tolist(), scores[0].tolist(), strict=True):
        if ident != -1 and ident in allowed:
            result.append((ident, float(score)))
            if len(result) == k:
                break
    return result


def subset(index, query, visible, k):
    import faiss

    if not len(visible):
        return []
    params = faiss.SearchParameters()
    params.sel = faiss.IDSelectorBatch(visible)
    scores, ids = index.search(query, k, params=params)
    return [(int(i), float(s)) for i, s in zip(ids[0], scores[0], strict=True) if i != -1]


def compare(index, repetitions: int) -> list[dict]:
    import numpy as np

    rng = np.random.default_rng(20260905)
    query = rng.standard_normal((1, index.d), dtype=np.float32)
    query /= np.linalg.norm(query)
    results = []
    for stride in (1, 10, 100):
        visible = np.arange(0, index.ntotal, stride, dtype=np.int64)
        timings = {"full": [], "subset": []}
        mismatches = 0
        max_error = 0.0
        # One warm-up per arm, then counterbalanced timed pairs on a fixed query.
        full_reference(index, query, visible, 20)
        subset(index, query, visible, 20)
        for repetition in range(repetitions):
            outputs = {}
            arms = ("full", "subset") if repetition % 2 == 0 else ("subset", "full")
            for arm in arms:
                start = time.perf_counter()
                outputs[arm] = (full_reference if arm == "full" else subset)(
                    index, query, visible, 20
                )
                timings[arm].append((time.perf_counter() - start) * 1000)
            left, right = outputs["full"], outputs["subset"]
            mismatches += [i for i, _ in left] != [i for i, _ in right]
            if len(left) == len(right):
                max_error = max(
                    max_error,
                    max((abs(a[1] - b[1]) for a, b in zip(left, right, strict=True)), default=0.0),
                )
        results.append(
            {
                "visible_ratio": 1 / stride,
                "visible_count": len(visible),
                "repetitions": repetitions,
                "ordered_id_mismatches": mismatches,
                "max_score_error": max_error,
                "full_result_slots": index.ntotal,
                "subset_result_slots": 20,
                "timings_ms": timings,
                "p95_ms": {k: float(np.percentile(v, 95)) for k, v in timings.items()},
            }
        )
    return results


def capacity(n: int, repetitions: int) -> dict:
    import faiss
    import numpy as np

    before = memory()
    allocation = budget(n, 1024, before["available_bytes"])
    if not allocation["allowed"]:
        return {"status": "BLOCKED_RESOURCE", "budget": allocation}
    index = faiss.IndexFlatIP(1024)
    # Resize once and fill a view: no second full numpy matrix or growth copies.
    index.codes.resize(allocation["vector_bytes"])
    vectors = faiss.rev_swig_ptr(index.get_xb(), n * 1024).reshape(n, 1024)
    rng = np.random.default_rng(20260905)
    for start in range(0, n, 1024):
        block = vectors[start : start + 1024]
        rng.standard_normal(block.shape, dtype=np.float32, out=block)
        block /= np.linalg.norm(block, axis=1, keepdims=True)
    index.ntotal = n
    after = memory()
    rows = compare(index, repetitions)
    return {
        "status": "MEASURED",
        "n": n,
        "dimension": 1024,
        "seed": 20260905,
        "budget": allocation,
        "before": before,
        "after_allocation": after,
        "after_search": memory(),
        "rows": rows,
        "scope": "single_fixed_synthetic_query_microbenchmark_not_service_p95",
    }


def tie_probe() -> dict:
    import faiss
    import numpy as np

    index = faiss.IndexFlatIP(2)
    index.add(np.ones((32, 2), dtype=np.float32))
    query = np.ones((1, 2), dtype=np.float32)
    visible = np.arange(32, dtype=np.int64)
    reference = full_reference(index, query, visible, 20)
    candidate = subset(index, query, visible, 20)
    return {
        "synthetic_only": True,
        "k": 20,
        "full": reference,
        "subset": candidate,
        "ordered_equal": reference == candidate,
        "decision": "REJECTED_AS_DROP_IN" if reference != candidate else "NOT_JUSTIFIED",
    }


def read_index(path: Path):
    import faiss

    # FAISS's Windows narrow-path fopen cannot open the Unicode workspace path.
    with path.open("rb") as stream:
        return faiss.read_index(faiss.PyCallbackIOReader(stream.read))


def production_coverage() -> dict:
    base = ROOT / "data/indexes_v2"
    active_path = base / "active.json"
    active_identity = identity(active_path)
    active = json.loads(active_path.read_text(encoding="utf-8"))
    versions = (base / "versions").resolve()
    version = (versions / active["run_id"]).resolve()
    if not version.is_relative_to(versions) or version == versions:
        raise ValueError("Production version escapes index root")
    manifest_path = version / "manifest.json"
    manifest_identity = identity(manifest_path)
    if manifest_identity["sha256"] != active["manifest_sha256"]:
        raise ValueError("Production manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = {item["path"]: item for item in manifest["artifacts"]}
    result = {
        "mode": "READ_ONLY_COVERAGE_NO_FAISS_SEARCH",
        "coverage": {},
        "input_artifacts": [active_identity, manifest_identity],
        "manifest_counts": {
            key: manifest.get(key)
            for key in (
                "source_document_count",
                "canonical_document_count",
                "duplicate_count",
                "chunk_count",
                "table_chunk_count",
            )
        },
    }
    for name in ("documents.json", "chunks.json"):
        path = version / name
        before = identity(path)
        if before["sha256"] != artifacts[name]["sha256"]:
            raise ValueError("Production record hash mismatch")
        result["coverage"][name] = coverage(records(path), name.removesuffix(".json"))
        if identity(path) != before:
            raise ValueError("Production records changed during coverage")
        result["input_artifacts"].append(before)
    if identity(active_path) != active_identity:
        raise ValueError("Production active pointer changed during coverage")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scale", type=int, choices=(10000, 50000, 100000))
    parser.add_argument("--assets", action="store_true")
    parser.add_argument(
        "--production-coverage",
        action="store_true",
        help="Only hash/count current data/indexes_v2 records; no vector search",
    )
    parser.add_argument("--repetitions", type=int, default=9, choices=range(3, 31))
    args = parser.parse_args()
    if sum((bool(args.scale), args.assets, args.production_coverage)) != 1:
        parser.error("Choose exactly one of --scale, --assets or --production-coverage")
    output = args.output.resolve()
    allowed = (ROOT / ".private/runtime_delivery/diagnostics").resolve()
    if not output.is_relative_to(allowed) or output.drive.lower() != "d:":
        parser.error("Output must remain in D-drive .private/runtime_delivery/diagnostics")
    if output.exists():
        parser.error("Refusing to overwrite an existing result")
    import faiss
    import numpy as np

    faiss.omp_set_num_threads(1)
    result = {
        "schema": "runtime_asset_diagnostics_v1",
        "argv": sys.argv[1:],
        "python": platform.python_version(),
        "numpy": np.__version__,
        "faiss": faiss.__version__,
        "cpu_logical_count": os.cpu_count(),
        "faiss_threads": faiss.omp_get_max_threads(),
        "platform": platform.platform(),
        "llm_calls": 0,
        "gpu_calls": 0,
        "frozen_labels_read": False,
        "script": identity(Path(__file__)),
        "input_artifacts": [],
    }
    if args.scale:
        result["capacity"] = capacity(args.scale, args.repetitions)
    elif args.production_coverage:
        result["production"] = production_coverage()
    else:
        result["coverage"] = {}
        for base, names in ((FIN, ("documents.json", "chunks.json")), (WIX, ("chunks.jsonl",))):
            for name in names:
                path = ROOT / base / name
                result["input_artifacts"].append(identity(path))
                result["coverage"][(base / name).as_posix()] = coverage(
                    records(path), "documents" if name.startswith("documents") else "chunks"
                )
        path = ROOT / WIX / "faiss.index"
        result["input_artifacts"].append(identity(path))
        result["input_artifacts"].append(identity(ROOT / WIX / "manifest.json"))
        preflight = budget(11975, 1024, memory()["available_bytes"])
        if not preflight["allowed"]:
            result["existing_index"] = {"status": "BLOCKED_RESOURCE", "budget": preflight}
        else:
            index = read_index(path)
            if type(index).__name__ != "IndexFlatIP" or index.d != 1024:
                raise ValueError("Expected the existing exact IP index")
            result["existing_index"] = {
                "n": index.ntotal,
                "dimension": index.d,
                "budget": preflight,
                "rows": compare(index, args.repetitions),
            }
        result["public_evidence"] = [identity(ROOT / p) for p in EVIDENCE]
        result["source_semantics"] = identity(ROOT / "app/retrieval/pipeline.py")
        result["parser_source"] = identity(ROOT / "app/ingestion/parsers_pdf.py")
        result["tie_probe"] = tie_probe()
        result["q4"] = {
            "decision": "REJECTED",
            "new_run": False,
            "reason": "historical_default_assessor_negative_no_new_trigger_evidence",
        }
        result["q5"] = {
            "decision": "BLOCKED_INPUT",
            "method": "public_ledger_review_only",
            "verified_unused_compatible_cohorts": 0,
            "not_claimed": "exhaustive_per_question_or_license_audit",
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(identity(output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
