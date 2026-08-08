from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

from app.external_datasets.enterprise_rag_bench import (
    DEFAULT_ENTERPRISE_RAG_BENCH_ROOT,
    ENTERPRISE_RAG_BENCH_DATASET_REVISION,
    EnterpriseRAGBenchRawDocument,
)
from app.utils import tokenize_for_bm25


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stream-profile EnterpriseRAG-Bench capacity without indexing."
    )
    parser.add_argument(
        "--documents",
        type=Path,
        default=DEFAULT_ENTERPRISE_RAG_BENCH_ROOT / "documents" / "test.parquet",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".private/external/enterprise_rag_bench/capacity_profile_v1.json"),
    )
    parser.add_argument("--chunk-size", type=int, default=1800)
    parser.add_argument("--overlap", type=int, default=150)
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument("--sample-modulus", type=int, default=50)
    parser.add_argument("--measured-embedding-chunks-per-second", type=float, default=41.5)
    return parser


def flat_chunk_count(length: int, *, chunk_size: int, overlap: int) -> int:
    if length < 1:
        return 0
    if chunk_size < 1 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("invalid flat chunk configuration")
    if length <= chunk_size:
        return 1
    return 1 + math.ceil((length - chunk_size) / (chunk_size - overlap))


def sample_document(doc_id: str, *, modulus: int) -> bool:
    if modulus < 1:
        raise ValueError("sample modulus must be positive")
    value = int.from_bytes(hashlib.sha256(doc_id.encode("utf-8")).digest()[:8], "big")
    return value % modulus == 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.perf_counter()
    path = args.documents.resolve()
    parquet = pq.ParquetFile(path)
    expected_schema = {"doc_id", "source_type", "title", "content"}
    if set(parquet.schema_arrow.names) != expected_schema:
        raise ValueError("EnterpriseRAG-Bench document schema mismatch")

    source_counts: Counter[str] = Counter()
    content_lengths: list[int] = []
    title_lengths: list[int] = []
    seen: set[str] = set()
    duplicate_count = 0
    empty_title_count = 0
    empty_content_count = 0
    chunk_count = 0
    sampled_documents = 0
    sampled_chunks = 0
    sampled_tokens = 0
    sampled_token_deep_bytes = 0
    peak_rss = _rss_bytes()
    processed = 0

    for batch in parquet.iter_batches(batch_size=args.batch_size):
        for payload in batch.to_pylist():
            raw = EnterpriseRAGBenchRawDocument.model_validate(payload)
            processed += 1
            if raw.doc_id in seen:
                duplicate_count += 1
            else:
                seen.add(raw.doc_id)
            source_counts[raw.source_type] += 1
            title_length = len(raw.title)
            content_length = len(raw.content)
            title_lengths.append(title_length)
            content_lengths.append(content_length)
            empty_title_count += int(not raw.title.strip())
            empty_content_count += int(not raw.content.strip())
            chunks = list(
                _flat_chunks(
                    raw.normalized_title,
                    raw.normalized_text,
                    chunk_size=args.chunk_size,
                    overlap=args.overlap,
                )
            )
            chunk_count += len(chunks)
            if sample_document(raw.doc_id, modulus=args.sample_modulus):
                sampled_documents += 1
                sampled_chunks += len(chunks)
                for text in chunks:
                    tokens = tokenize_for_bm25(text)
                    sampled_tokens += len(tokens)
                    sampled_token_deep_bytes += sys.getsizeof(tokens)
                    sampled_token_deep_bytes += sum(sys.getsizeof(token) for token in tokens)
        peak_rss = max(peak_rss, _rss_bytes())
        if processed % 50_000 < args.batch_size:
            print(f"profiled {processed}/{parquet.metadata.num_rows}", flush=True)

    content_lengths.sort()
    title_lengths.sort()
    vector_bytes = chunk_count * 1024 * 4
    estimated_bm25_deep_bytes = round(
        sampled_token_deep_bytes * chunk_count / sampled_chunks
    )
    payload = {
        "schema_version": "enterprise_rag_bench_capacity_profile_v1",
        "dataset_revision": ENTERPRISE_RAG_BENCH_DATASET_REVISION,
        "documents_sha256": _sha256(path),
        "documents_byte_count": path.stat().st_size,
        "document_count": processed,
        "unique_document_count": len(seen),
        "duplicate_document_id_count": duplicate_count,
        "source_counts": dict(sorted(source_counts.items())),
        "empty_title_count": empty_title_count,
        "empty_content_count": empty_content_count,
        "content_characters_total": sum(content_lengths),
        "content_length_characters": _quantiles(content_lengths),
        "title_length_characters": _quantiles(title_lengths),
        "flat_chunking": {
            "chunk_size_characters": args.chunk_size,
            "overlap_characters": args.overlap,
            "chunk_count": chunk_count,
            "chunks_per_document": chunk_count / processed,
        },
        "bm25_sample": {
            "selection": f"sha256(doc_id)[0:8] modulo {args.sample_modulus} == 0",
            "sampled_documents": sampled_documents,
            "sampled_chunks": sampled_chunks,
            "sampled_tokens": sampled_tokens,
            "sampled_token_deep_bytes": sampled_token_deep_bytes,
            "estimated_full_token_deep_bytes": estimated_bm25_deep_bytes,
        },
        "embedding_capacity": {
            "dimension": 1024,
            "dtype": "float32",
            "one_vector_matrix_bytes": vector_bytes,
            "cache_plus_faiss_vector_bytes": vector_bytes * 2,
            "measured_chunks_per_second": args.measured_embedding_chunks_per_second,
            "estimated_embedding_seconds": chunk_count / args.measured_embedding_chunks_per_second,
        },
        "parquet_row_group_count": parquet.metadata.num_row_groups,
        "profile_peak_rss_bytes": peak_rss,
        "profile_duration_seconds": time.perf_counter() - started,
        "quality_labels_used": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _flat_chunks(
    title: str,
    content: str,
    *,
    chunk_size: int,
    overlap: int,
):
    start = 0
    body = content.strip()
    while start < len(body):
        end = min(start + chunk_size, len(body))
        piece = body[start:end].strip()
        if piece:
            yield f"{title}\n{piece}"
        if end == len(body):
            break
        start = end - overlap


def _quantiles(values: list[int]) -> dict[str, int]:
    if not values:
        raise ValueError("capacity profile has no values")
    return {
        label: values[max(0, math.ceil(fraction * len(values)) - 1)]
        for label, fraction in (
            ("min", 0.0),
            ("p50", 0.50),
            ("p90", 0.90),
            ("p95", 0.95),
            ("p99", 0.99),
            ("max", 1.0),
        )
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _rss_bytes() -> int:
    try:
        import psutil

        memory = psutil.Process(os.getpid()).memory_info()
        return int(getattr(memory, "peak_wset", memory.rss))
    except ImportError:
        if os.name != "nt":
            return 0

    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    get_current_process = ctypes.windll.kernel32.GetCurrentProcess
    get_current_process.argtypes = []
    get_current_process.restype = wintypes.HANDLE
    get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_process_memory_info.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCounters),
        wintypes.DWORD,
    ]
    get_process_memory_info.restype = wintypes.BOOL
    process = get_current_process()
    succeeded = get_process_memory_info(
        process, ctypes.byref(counters), counters.cb
    )
    return int(counters.PeakWorkingSetSize) if succeeded else 0


if __name__ == "__main__":
    raise SystemExit(main())
