from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish aggregate full-corpus EnterpriseRAG-Bench B0 evidence."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--eval-root",
        type=Path,
        default=Path(".private/external/enterprise_rag_bench/eval_runs"),
    )
    parser.add_argument(
        "--index-root",
        type=Path,
        default=Path(".private/external/enterprise_rag_bench/indexes/fts5"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/enterprise_eval/evidence/"
            "enterprise_rag_bench_bm25_public_v1.json"
        ),
    )
    return parser


def build_public_evidence(
    summary: dict[str, Any],
    index_manifest: dict[str, Any],
    *,
    private_summary_sha256: str,
) -> dict[str, Any]:
    if summary.get("mode") != "FORMAL_FULL_CORPUS":
        raise ValueError("only a formal full-corpus run may be published")
    if summary.get("case_count") != 470:
        raise ValueError("formal retrieval case count must be 470")
    if summary.get("source_type_filter_used") is not False:
        raise ValueError("source-type oracle filtering is forbidden")
    if summary.get("answer_labels_used") is not False:
        raise ValueError("B0 retrieval must not use answer labels")
    if index_manifest.get("document_row_count") != 511_962:
        raise ValueError("formal index must contain the full corpus")
    if index_manifest.get("corpus_sha256") != summary.get("corpus_sha256"):
        raise ValueError("index and evaluation corpus hashes differ")
    code_revision = summary.get("code_revision", "")
    if not re.fullmatch(r"[0-9a-f]{40}", code_revision):
        raise ValueError("evaluation code revision is not a full Git SHA")
    return {
        "schema_version": "enterprise_rag_bench_bm25_public_v1",
        "execution_git_sha": code_revision,
        "private_summary_sha256": private_summary_sha256,
        "dataset": {
            "name": "EnterpriseRAG-Bench",
            "revision": summary["dataset_revision"],
            "split": "test",
            "corpus_sha256": summary["corpus_sha256"],
            "document_row_count": index_manifest["document_row_count"],
            "retrieval_case_count": summary["case_count"],
            "consumption": "FIXED_CONSUMED_PUBLIC_LABELS",
        },
        "index": {
            "arm": summary["arm"],
            "run_id": summary["index_run_id"],
            "manifest_sha256": summary["index_manifest_sha256"],
            "artifact_byte_count": index_manifest["artifact"]["byte_count"],
            "artifact_sha256": index_manifest["artifact"]["sha256"],
            "active_build_duration_ms": index_manifest[
                "active_build_duration_ms"
            ],
            "build_peak_rss_bytes": index_manifest["build_peak_rss_bytes"],
            "tokenizer": index_manifest["tokenizer"],
            "title_bm25_weight": index_manifest["title_bm25_weight"],
            "content_bm25_weight": index_manifest["content_bm25_weight"],
            "source_type_filter_used": summary["source_type_filter_used"],
        },
        "protocol_sha256": summary["protocol_sha256"],
        "metrics": {
            "overall": summary["overall"],
            "by_question_type": summary["by_question_type"],
        },
        "claim_boundary": {
            "retrieval_only": True,
            "answer_quality": "NOT_MEASURED",
            "citation_quality": "NOT_MEASURED",
            "refusal_quality": "NOT_MEASURED",
            "agent_value": "NOT_MEASURED",
            "bm25_parameters_tuned_on_this_split": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary_path = args.eval_root / args.run_id / "summary.json"
    summary_bytes = summary_path.read_bytes()
    summary = json.loads(summary_bytes)
    index_manifest_path = (
        args.index_root
        / "versions"
        / summary["index_run_id"]
        / "manifest.json"
    )
    index_manifest = json.loads(index_manifest_path.read_bytes())
    evidence = build_public_evidence(
        summary,
        index_manifest,
        private_summary_sha256=hashlib.sha256(summary_bytes).hexdigest(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
