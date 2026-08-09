from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from scripts.qualify_enterprise_dense_capacity import _windows_memory_snapshot


DEFAULT_OUTPUT = Path(
    "docs/rapid_upgrade/evidence/ENTERPRISE_DENSE_CAPACITY_PUBLIC.json"
)


def build_public_evidence(run: dict, *, private_summary_sha256: str) -> dict:
    if run.get("quality_labels_used") is not False:
        raise ValueError("capacity evidence must not consume quality labels")
    checkpoints = run.get("checkpoints", [])
    if [item.get("chunk_count") for item in checkpoints] != [1_000, 10_000, 50_000]:
        raise ValueError("capacity evidence requires exact 1k/10k/50k checkpoints")
    decision = run.get("capacity_decision", {})
    if decision.get("decision") != "FULL_DENSE_NO_GO":
        raise ValueError("this publication contract expects the measured no-go")
    hardware = dict(run["hardware"])
    augmentation = None
    if not hardware.get("ram_total_bytes"):
        total, available = _windows_memory_snapshot()
        if total:
            hardware["ram_total_bytes"] = total
            hardware["ram_available_bytes_at_publication"] = available
            hardware.pop("ram_available_bytes_at_end", None)
            augmentation = "Windows GlobalMemoryStatusEx at publication"
    return {
        "schema_version": "enterprise_dense_capacity_public_v1",
        "execution_git_sha": run["execution_git_sha"],
        "private_summary_sha256": private_summary_sha256,
        "dataset_revision": run["dataset_revision"],
        "documents_sha256": run["documents_sha256"],
        "documents_byte_count": run["documents_byte_count"],
        "selection": run["selection"],
        "chunking": {
            "chunk_size_characters": run["chunk_size_characters"],
            "overlap_characters": run["overlap_characters"],
        },
        "batch_size": run["batch_size"],
        "embedding": {
            "model_identifier": run["model_identifier"],
            "model_sha256": run["model_sha256"],
            "dimension": run["embedding_dimension"],
            "dtype": run["dtype"],
        },
        "vector_stream_sha256": run["vector_stream_sha256"],
        "checkpoints": checkpoints,
        "capacity_decision": decision,
        "hardware": hardware,
        "hardware_augmentation": augmentation,
        "claim_boundary": {
            "quality_labels_used": False,
            "persistent_dense_index_built": False,
            "retrieval_quality_measured": False,
            "production_throughput_claim_allowed": False,
            "resume_quality_claim_allowed": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish aggregate Enterprise Dense capacity evidence."
    )
    parser.add_argument("--run-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary_bytes = args.run_summary.read_bytes()
    payload = build_public_evidence(
        json.loads(summary_bytes),
        private_summary_sha256=hashlib.sha256(summary_bytes).hexdigest(),
    )
    output = args.output.resolve()
    if shutil.disk_usage(output.parent if output.parent.exists() else Path.cwd()).free < 1_000_000:
        raise ValueError("insufficient disk space for public evidence")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
