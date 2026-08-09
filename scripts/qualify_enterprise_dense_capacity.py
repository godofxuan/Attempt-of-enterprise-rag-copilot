from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

from app.config import get_settings
from app.external_datasets.enterprise_dense_capacity import (
    DenseQualificationCheckpoint,
    decide_full_dense_run,
)
from app.external_datasets.enterprise_rag_bench import (
    DEFAULT_ENTERPRISE_RAG_BENCH_ROOT,
    ENTERPRISE_RAG_BENCH_DATASET_REVISION,
    EnterpriseRAGBenchRawDocument,
)
from app.runtime.ollama_embeddings import OllamaEmbeddingClient


CHECKPOINTS = (1_000, 10_000, 50_000)
FULL_CHUNK_COUNT = 1_702_370


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure 1k/10k/50k EnterpriseRAG Dense embedding capacity."
    )
    parser.add_argument(
        "--documents",
        type=Path,
        default=DEFAULT_ENTERPRISE_RAG_BENCH_ROOT / "documents" / "test.parquet",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            ".private/external/enterprise_rag_bench/"
            "dense_capacity_qualification_v1.json"
        ),
    )
    parser.add_argument("--batch-size", type=int, default=32)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "EnterpriseRAG Dense qualification requires the optional "
            "'pyarrow' package"
        ) from exc

    args = build_parser().parse_args(argv)
    if args.batch_size < 1 or args.batch_size > 128:
        raise ValueError("batch size must be between 1 and 128")
    documents = args.documents.resolve()
    expected_bytes = 1_409_893_131
    expected_sha256 = (
        "6b0747bf160af9427b12101537d53056ac592ada9831c1a98ae01fa50a8d2a9f"
    )
    if documents.stat().st_size != expected_bytes:
        raise ValueError("EnterpriseRAG corpus byte count mismatch")
    if _sha256(documents) != expected_sha256:
        raise ValueError("EnterpriseRAG corpus SHA-256 mismatch")

    settings = get_settings()
    client = OllamaEmbeddingClient.from_settings(
        settings,
        probe_text="EnterpriseRAG Dense capacity dimension probe",
        endpoint_context="EnterpriseRAG Dense capacity qualification",
    )
    parquet = pq.ParquetFile(documents)
    if set(parquet.schema_arrow.names) != {
        "doc_id",
        "source_type",
        "title",
        "content",
    }:
        raise ValueError("EnterpriseRAG corpus schema mismatch")

    vector_digest = hashlib.sha256()
    batch: list[str] = []
    embedded = 0
    input_characters = 0
    vector_bytes = 0
    peak_rss = _rss_bytes()
    checkpoints = []
    started = time.perf_counter()

    def flush() -> None:
        nonlocal embedded, input_characters, vector_bytes, peak_rss
        if not batch:
            return
        vectors = client.embed_batch(batch)
        if vectors.shape != (len(batch), client.dimension):
            raise ValueError("embedding batch shape changed")
        raw = vectors.tobytes(order="C")
        vector_digest.update(raw)
        embedded += len(batch)
        input_characters += sum(len(text) for text in batch)
        vector_bytes += len(raw)
        peak_rss = max(peak_rss, _rss_bytes())
        batch.clear()

    checkpoint_index = 0
    for raw in _iter_raw_documents(parquet):
        for text in _flat_chunks(
            raw.normalized_title,
            raw.normalized_text,
            chunk_size=1_800,
            overlap=150,
        ):
            batch.append(text)
            target = CHECKPOINTS[checkpoint_index]
            if len(batch) == args.batch_size or embedded + len(batch) == target:
                flush()
            if embedded == target:
                elapsed = time.perf_counter() - started
                checkpoints.append(
                    DenseQualificationCheckpoint(
                        chunk_count=embedded,
                        elapsed_seconds=elapsed,
                        chunks_per_second=embedded / elapsed,
                        input_characters=input_characters,
                        vector_bytes=vector_bytes,
                        process_peak_rss_bytes=peak_rss,
                        error_count=0,
                    )
                )
                print(
                    f"checkpoint {embedded}: {embedded / elapsed:.3f} chunks/s",
                    flush=True,
                )
                checkpoint_index += 1
                if checkpoint_index == len(CHECKPOINTS):
                    break
        if checkpoint_index == len(CHECKPOINTS):
            break
    if checkpoint_index != len(CHECKPOINTS):
        raise ValueError("corpus ended before all Dense checkpoints")

    disk = shutil.disk_usage(Path.cwd())
    decision = decide_full_dense_run(
        checkpoints,
        full_chunk_count=FULL_CHUNK_COUNT,
        embedding_dimension=client.dimension,
        available_disk_bytes=disk.free,
        sharded_builder_ready=False,
        development_protocol_ready=False,
    )
    payload = {
        "schema_version": "enterprise_dense_capacity_qualification_v1",
        "dataset_revision": ENTERPRISE_RAG_BENCH_DATASET_REVISION,
        "documents_sha256": expected_sha256,
        "documents_byte_count": expected_bytes,
        "quality_labels_used": False,
        "selection": "canonical source order first 50000 flat chunks",
        "chunk_size_characters": 1_800,
        "overlap_characters": 150,
        "batch_size": args.batch_size,
        "model_identifier": client.model_identifier,
        "model_sha256": client.model_sha256,
        "embedding_dimension": client.dimension,
        "dtype": "float32",
        "vector_stream_sha256": vector_digest.hexdigest(),
        "checkpoints": [item.model_dump(mode="json") for item in checkpoints],
        "capacity_decision": decision.model_dump(mode="json"),
        "hardware": _hardware_snapshot(disk.free),
        "execution_git_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "command_scope": (
            "capacity qualification only; no persistent vectors and no quality labels"
        ),
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


def _iter_raw_documents(parquet):
    for record_batch in parquet.iter_batches(batch_size=2_000):
        for payload in record_batch.to_pylist():
            yield EnterpriseRAGBenchRawDocument.model_validate(payload)


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
        process,
        ctypes.byref(counters),
        counters.cb,
    )
    return int(counters.PeakWorkingSetSize) if succeeded else 0


def _hardware_snapshot(free_disk_bytes: int) -> dict:
    try:
        import psutil

        memory = psutil.virtual_memory()
        ram_total = memory.total
        ram_available = memory.available
    except ImportError:
        ram_total, ram_available = _windows_memory_snapshot()
    gpu = "UNAVAILABLE"
    try:
        gpu = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=10,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "ram_total_bytes": ram_total,
        "ram_available_bytes_at_end": ram_available,
        "disk_free_bytes_at_end": free_disk_bytes,
        "gpu": gpu,
    }


def _windows_memory_snapshot() -> tuple[int, int]:
    if os.name != "nt":
        return 0, 0
    import ctypes

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    succeeded = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    if not succeeded:
        return 0, 0
    return int(status.ullTotalPhys), int(status.ullAvailPhys)


if __name__ == "__main__":
    raise SystemExit(main())
