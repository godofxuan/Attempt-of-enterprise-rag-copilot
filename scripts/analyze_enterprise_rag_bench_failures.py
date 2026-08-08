from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create deterministic EnterpriseRAG-Bench B0 failure evidence."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--eval-root",
        type=Path,
        default=Path(".private/external/enterprise_rag_bench/eval_runs"),
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=Path("docs/enterprise_eval/ENTERPRISE_FAILURE_TAXONOMY.csv"),
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path(
            "docs/enterprise_eval/evidence/"
            "enterprise_rag_bench_failure_summary_v1.json"
        ),
    )
    return parser


def classify_failure(row: dict[str, Any]) -> str:
    if float(row["recall_at_5"]) == 0.0:
        return "RETRIEVAL_MISS"
    if int(row["gold_document_count"]) > 1 and float(row["recall_at_5"]) < 1.0:
        return "MULTI_DOC_INCOMPLETE"
    if float(row["hit_at_1"]) == 0.0:
        return "WRONG_DOCUMENT"
    return "OK"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_dir = args.eval_root / args.run_id
    summary_bytes = (run_dir / "summary.json").read_bytes()
    summary = json.loads(summary_bytes)
    details_bytes = (run_dir / "details.jsonl").read_bytes()
    if hashlib.sha256(details_bytes).hexdigest() != summary["details_sha256"]:
        raise ValueError("private retrieval details SHA-256 mismatch")
    rows = [json.loads(line) for line in details_bytes.splitlines() if line.strip()]
    if len(rows) != summary["case_count"]:
        raise ValueError("retrieval detail count mismatch")

    fieldnames = [
        "question_id",
        "question_type",
        "gold_document_count",
        "hit_at_1",
        "recall_at_3",
        "recall_at_5",
        "failure_category",
        "latency_ms",
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    overall: Counter[str] = Counter()
    by_type: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        failure = classify_failure(row)
        overall[failure] += 1
        by_type[row["question_type"]][failure] += 1
        writer.writerow(
            {
                "question_id": row["question_id"],
                "question_type": row["question_type"],
                "gold_document_count": row["gold_document_count"],
                "hit_at_1": row["hit_at_1"],
                "recall_at_3": row["recall_at_3"],
                "recall_at_5": row["recall_at_5"],
                "failure_category": failure,
                "latency_ms": row["latency_ms"],
            }
        )
    csv_bytes = stream.getvalue().encode("utf-8")
    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    args.csv_output.write_bytes(csv_bytes)
    payload = {
        "schema_version": "enterprise_rag_bench_failure_summary_v1",
        "analysis_git_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "source_run_id": summary["run_id"],
        "source_execution_git_sha": summary["code_revision"],
        "source_details_sha256": summary["details_sha256"],
        "case_count": len(rows),
        "classification_priority": [
            "RETRIEVAL_MISS",
            "MULTI_DOC_INCOMPLETE",
            "WRONG_DOCUMENT",
            "OK",
        ],
        "overall_counts": dict(sorted(overall.items())),
        "by_question_type": {
            key: dict(sorted(value.items())) for key, value in sorted(by_type.items())
        },
        "taxonomy_csv_sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "not_assessed_by_retrieval_only_run": [
            "CONFLICT_NOT_DETECTED",
            "ANSWER_REASONING_ERROR",
            "UNSUPPORTED_CLAIM",
            "CITATION_ERROR",
            "FALSE_REFUSAL",
            "FAILED_TO_REFUSE",
            "TOOL_BUDGET_EXHAUSTED",
            "PARSER_ERROR",
        ],
    }
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
