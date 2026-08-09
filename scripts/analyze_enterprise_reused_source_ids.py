from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.external_datasets.enterprise_rag_bench import (
    DEFAULT_ENTERPRISE_RAG_BENCH_ROOT,
    load_enterprise_rag_bench_questions,
)
from app.external_datasets.enterprise_rag_bench_fts import (
    load_enterprise_rag_bench_fts,
)
from app.external_datasets.wixqa import canonical_json_bytes


DEFAULT_DETAILS = Path(
    ".private/external/enterprise_rag_bench/eval_runs/"
    "enterprise-rag-bench-b0-v1-955d86f/details.jsonl"
)
DEFAULT_INDEX_ROOT = Path(
    ".private/external/enterprise_rag_bench/indexes/fts5"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure record-aware sensitivity for reused Enterprise source IDs."
    )
    parser.add_argument(
        "--documents",
        type=Path,
        default=DEFAULT_ENTERPRISE_RAG_BENCH_ROOT / "documents" / "test.parquet",
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=DEFAULT_ENTERPRISE_RAG_BENCH_ROOT / "questions" / "test.parquet",
    )
    parser.add_argument("--details", type=Path, default=DEFAULT_DETAILS)
    parser.add_argument("--index-root", type=Path, default=DEFAULT_INDEX_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def build_sensitivity(
    *,
    reused_groups: dict[str, list[dict[str, Any]]],
    questions,
    details_by_question: dict[str, dict[str, Any]],
    strict_hits_by_question: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    affected = []
    total_reduction = 0.0
    for question in questions:
        expected_counts = Counter(question.expected_doc_ids)
        reused_gold = sorted(set(expected_counts).intersection(reused_groups))
        if not reused_gold:
            continue
        published = details_by_question[question.question_id]
        strict_hits = strict_hits_by_question[question.question_id]
        strict_gold_count = len(question.unique_expected_doc_ids)
        for source_id in reused_gold:
            represented_records = min(
                expected_counts[source_id], len(reused_groups[source_id])
            )
            strict_gold_count += represented_records - 1
        strict_credit = 0
        for source_id in question.unique_expected_doc_ids:
            matching = [
                item for item in strict_hits if item["source_native_id"] == source_id
            ]
            strict_credit += min(
                len({item["record_id"] for item in matching}),
                (
                    min(expected_counts[source_id], len(reused_groups[source_id]))
                    if source_id in reused_groups
                    else 1
                ),
            )
        strict_recall = strict_credit / strict_gold_count
        reduction = float(published["recall_at_5"]) - strict_recall
        total_reduction += reduction
        affected.append(
            {
                "question_id": question.question_id,
                "question_type": question.question_type,
                "reused_gold_ids": reused_gold,
                "official_expected_id_occurrences": {
                    item: expected_counts[item] for item in reused_gold
                },
                "published_unique_gold_count": published["gold_document_count"],
                "record_aware_gold_count": strict_gold_count,
                "retrieved_record_ids": [
                    item["record_id"]
                    for item in strict_hits
                    if item["source_native_id"] in reused_gold
                ],
                "published_recall_at_5": published["recall_at_5"],
                "record_aware_recall_at_5": strict_recall,
                "recall_at_5_reduction": reduction,
            }
        )
    case_count = len(details_by_question)
    published_macro = sum(
        float(item["recall_at_5"]) for item in details_by_question.values()
    ) / case_count
    macro_reduction = total_reduction / case_count
    return {
        "schema_version": "enterprise_reused_source_id_sensitivity_v1",
        "reused_source_id_group_count": len(reused_groups),
        "reused_physical_record_count": sum(
            len(items) for items in reused_groups.values()
        ),
        "reused_groups": reused_groups,
        "retrieval_case_count": case_count,
        "affected_question_count": len(affected),
        "affected_questions": affected,
        "published_macro_recall_at_5": published_macro,
        "record_aware_macro_recall_at_5": published_macro - macro_reduction,
        "macro_recall_at_5_reduction": macro_reduction,
        "macro_recall_at_5_reduction_percentage_points": macro_reduction * 100,
        "interpretation": (
            "Sensitivity only: duplicate official expected-ID occurrences are "
            "treated as the distinct physical records sharing that ID."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    reused_groups = _load_reused_groups(args.documents)
    questions = [
        item
        for item in load_enterprise_rag_bench_questions(args.questions)
        if item.unique_expected_doc_ids
    ]
    details = {
        item["question_id"]: item
        for item in _load_jsonl(args.details)
    }
    affected = [
        item
        for item in questions
        if set(item.unique_expected_doc_ids).intersection(reused_groups)
    ]
    strict_hits: dict[str, list[dict[str, Any]]] = {}
    with load_enterprise_rag_bench_fts(args.index_root) as index:
        for question in affected:
            strict_hits[question.question_id] = [
                item.model_dump(mode="json")
                for item in index.search(question.question, top_k=5)
            ]
        index_run_id = index.manifest.run_id
    payload = build_sensitivity(
        reused_groups=reused_groups,
        questions=questions,
        details_by_question=details,
        strict_hits_by_question=strict_hits,
    )
    payload.update(
        {
            "execution_git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "documents_sha256": _sha256(args.documents),
            "questions_sha256": _sha256(args.questions),
            "private_details_sha256": _sha256(args.details),
            "index_run_id": index_run_id,
            "claim_boundary": {
                "published_metric_replaced": False,
                "record_hash_gold_available": False,
                "sensitivity_not_new_benchmark": True,
            },
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


def _load_reused_groups(path: Path) -> dict[str, list[dict[str, Any]]]:
    import pyarrow.parquet as pq

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_row = 0
    for batch in pq.ParquetFile(path).iter_batches(batch_size=10_000):
        for payload in batch.to_pylist():
            source_row += 1
            groups[payload["doc_id"]].append(
                {
                    "source_row": source_row,
                    "source_type": payload["source_type"],
                    "raw_record_sha256": hashlib.sha256(
                        canonical_json_bytes(payload)
                    ).hexdigest(),
                }
            )
    return {
        source_id: records
        for source_id, records in groups.items()
        if len(records) > 1
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
