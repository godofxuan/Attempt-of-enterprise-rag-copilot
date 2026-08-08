from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from app.external_datasets.enterprise_rag_bench import (
    ENTERPRISE_RAG_BENCH_DATASET_REVISION,
)


EXPECTED_CORPUS_SHA256 = (
    "6b0747bf160af9427b12101537d53056ac592ada9831c1a98ae01fa50a8d2a9f"
)
EXPECTED_SOURCE_COUNTS = {
    "confluence": 5189,
    "fireflies": 10173,
    "github": 8052,
    "gmail": 121390,
    "google_drive": 25108,
    "hubspot": 15017,
    "jira": 6120,
    "linear": 35308,
    "slack": 285605,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish aggregate EnterpriseRAG-Bench capacity evidence."
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path(
            ".private/external/enterprise_rag_bench/capacity_profile_v1.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/enterprise_eval/evidence/"
            "enterprise_rag_bench_capacity_public_v1.json"
        ),
    )
    parser.add_argument("--git-sha")
    return parser


def build_public_evidence(
    profile: dict[str, Any], *, execution_git_sha: str, profile_sha256: str
) -> dict[str, Any]:
    _validate_profile(profile)
    if not re.fullmatch(r"[0-9a-f]{40}", execution_git_sha):
        raise ValueError("execution Git SHA must be a full lowercase SHA-1")
    embedding = profile["embedding_capacity"]
    chunking = profile["flat_chunking"]
    bm25 = profile["bm25_sample"]
    return {
        "schema_version": "enterprise_rag_bench_capacity_public_v1",
        "execution_git_sha": execution_git_sha,
        "private_profile_sha256": profile_sha256,
        "dataset": {
            "name": "EnterpriseRAG-Bench",
            "revision": profile["dataset_revision"],
            "official_split": "test",
            "corpus_sha256": profile["documents_sha256"],
            "corpus_byte_count": profile["documents_byte_count"],
            "row_count": profile["document_count"],
            "unique_source_id_count": profile["unique_document_count"],
            "source_counts": profile["source_counts"],
        },
        "protocol": {
            "chunk_size_characters": chunking["chunk_size_characters"],
            "overlap_characters": chunking["overlap_characters"],
            "bm25_sample_selection": bm25["selection"],
            "quality_labels_used": profile["quality_labels_used"],
        },
        "measured_capacity": {
            "flat_chunk_count": chunking["chunk_count"],
            "chunks_per_document": round(chunking["chunks_per_document"], 6),
            "profile_peak_rss_bytes": profile["profile_peak_rss_bytes"],
            "profile_duration_seconds": round(profile["profile_duration_seconds"], 3),
            "one_float32_vector_matrix_bytes": embedding[
                "one_vector_matrix_bytes"
            ],
            "cache_plus_faiss_vector_bytes": embedding[
                "cache_plus_faiss_vector_bytes"
            ],
            "estimated_python_bm25_token_bytes": bm25[
                "estimated_full_token_deep_bytes"
            ],
            "measured_embedding_chunks_per_second": embedding[
                "measured_chunks_per_second"
            ],
            "estimated_embedding_hours": round(
                embedding["estimated_embedding_seconds"] / 3600, 3
            ),
        },
        "data_quality": {
            "empty_title_count": profile["empty_title_count"],
            "empty_content_count": profile["empty_content_count"],
            "reused_source_id_row_count": profile["duplicate_document_id_count"],
            "reused_source_id_group_count": 4,
            "reused_source_ids_have_distinct_records": True,
            "gold_anomaly": (
                "qst_0413 repeats one reused source ID twice; raw annotation is "
                "preserved and set-based metrics use an order-preserving unique view"
            ),
            "record_identity": "source_native_id + raw_record_sha256 prefix",
        },
        "decision": {
            "full_corpus_download": "VERIFIED",
            "full_scale_index": "CAPACITY_BLOCKED",
            "formal_quality_score": "NOT_RUN",
            "reason": (
                "The current all-in-memory BM25 plus dense builder exceeds the "
                "measured local RAM envelope and lacks resumable sharded indexing."
            ),
            "required_before_formal_run": [
                "disk-backed or sharded lexical index",
                "memory-mapped or sharded dense vectors",
                "resumable embedding checkpoints",
                "measured build peak RSS below the local envelope",
            ],
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    profile_bytes = args.profile.read_bytes()
    profile = json.loads(profile_bytes)
    git_sha = args.git_sha or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
    evidence = build_public_evidence(
        profile,
        execution_git_sha=git_sha,
        profile_sha256=hashlib.sha256(profile_bytes).hexdigest(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


def _validate_profile(profile: dict[str, Any]) -> None:
    if profile.get("schema_version") != "enterprise_rag_bench_capacity_profile_v1":
        raise ValueError("unexpected private capacity profile schema")
    if profile.get("dataset_revision") != ENTERPRISE_RAG_BENCH_DATASET_REVISION:
        raise ValueError("dataset revision mismatch")
    if profile.get("documents_sha256") != EXPECTED_CORPUS_SHA256:
        raise ValueError("corpus SHA-256 mismatch")
    if profile.get("document_count") != 511_962:
        raise ValueError("document row count mismatch")
    if profile.get("source_counts") != EXPECTED_SOURCE_COUNTS:
        raise ValueError("source counts mismatch")
    if profile.get("quality_labels_used") is not False:
        raise ValueError("capacity qualification must not consume quality labels")
    if profile.get("profile_peak_rss_bytes", 0) <= 0:
        raise ValueError("profile peak RSS was not measured")


if __name__ == "__main__":
    raise SystemExit(main())
