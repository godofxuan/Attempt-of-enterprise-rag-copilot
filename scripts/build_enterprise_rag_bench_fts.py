from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.external_datasets.enterprise_rag_bench import (
    DEFAULT_ENTERPRISE_RAG_BENCH_ROOT,
)
from app.external_datasets.enterprise_rag_bench_fts import (
    build_enterprise_rag_bench_fts,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a resumable full-corpus EnterpriseRAG-Bench FTS5 index."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--documents",
        type=Path,
        default=DEFAULT_ENTERPRISE_RAG_BENCH_ROOT / "documents" / "test.parquet",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data_manifests/ENTERPRISERAG_MANIFEST.json"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(".private/external/enterprise_rag_bench/indexes/fts5"),
    )
    parser.add_argument("--commit-interval", type=int, default=5000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest_bytes = args.manifest.read_bytes()
    dataset = json.loads(manifest_bytes)
    corpus = dataset["corpus"]
    documents = args.documents.resolve()
    if documents.stat().st_size != corpus["expected_byte_count"]:
        raise ValueError("EnterpriseRAG-Bench corpus byte count mismatch")
    if _sha256(documents) != corpus["sha256"]:
        raise ValueError("EnterpriseRAG-Bench corpus SHA-256 mismatch")
    result = build_enterprise_rag_bench_fts(
        documents_path=documents,
        output_root=args.output_root,
        run_id=args.run_id,
        corpus_sha256=corpus["sha256"],
        dataset_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        expected_document_count=corpus["expected_document_count"],
        commit_interval=args.commit_interval,
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
