from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

import requests

from app.external_datasets.enterprise_rag_bench import (
    DEFAULT_ENTERPRISE_RAG_BENCH_ROOT,
    ENTERPRISE_RAG_BENCH_DATASET_REVISION,
)


FILES = {
    "questions": ("data/questions/test.parquet", 408_737),
    "documents": ("data/documents/test.parquet", 1_409_893_131),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download pinned official EnterpriseRAG-Bench parquet files."
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ENTERPRISE_RAG_BENCH_ROOT)
    parser.add_argument("--include-documents", action="store_true")
    parser.add_argument("--confirm-full-corpus", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.include_documents and not args.confirm_full_corpus:
        raise SystemExit("full corpus requires --confirm-full-corpus")
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    selected = ["questions", *( ["documents"] if args.include_documents else [])]
    if args.include_documents:
        required = FILES["documents"][1] * 4
        free = shutil.disk_usage(root).free
        if free < required:
            raise SystemExit(
                f"insufficient free space for bounded full-corpus staging: {free} < {required}"
            )
    results = []
    for name in selected:
        relative, expected_bytes = FILES[name]
        target = root / name / "test.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        results.append(
            _download_verified(relative, target, expected_bytes=expected_bytes)
        )
    print(json.dumps({"files": results}, indent=2, sort_keys=True))
    return 0


def _download_verified(relative: str, target: Path, *, expected_bytes: int) -> dict:
    if target.is_file() and target.stat().st_size == expected_bytes:
        return _evidence(target, action="already_present_verified")
    partial = target.with_suffix(target.suffix + ".partial")
    existing = partial.stat().st_size if partial.is_file() else 0
    headers = {"Range": f"bytes={existing}-"} if existing else {}
    url = (
        "https://huggingface.co/datasets/onyx-dot-app/EnterpriseRAG-Bench/resolve/"
        f"{ENTERPRISE_RAG_BENCH_DATASET_REVISION}/{relative}?download=true"
    )
    with requests.get(url, headers=headers, stream=True, timeout=(30, 300)) as response:
        if existing and response.status_code != 206:
            existing = 0
        response.raise_for_status()
        mode = "ab" if existing and response.status_code == 206 else "wb"
        with partial.open(mode) as handle:
            for block in response.iter_content(chunk_size=4 * 1024 * 1024):
                if block:
                    handle.write(block)
                    handle.flush()
    if partial.stat().st_size != expected_bytes:
        raise ValueError(
            f"download size mismatch for {relative}: {partial.stat().st_size} != {expected_bytes}"
        )
    os.replace(partial, target)
    return _evidence(target, action="downloaded_verified")


def _evidence(path: Path, *, action: str) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return {
        "action": action,
        "byte_count": path.stat().st_size,
        "path": str(path),
        "sha256": digest.hexdigest(),
    }


if __name__ == "__main__":
    raise SystemExit(main())

