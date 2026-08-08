from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

from app.external_datasets.enterprise_rag_bench import (
    DEFAULT_ENTERPRISE_RAG_BENCH_ROOT,
    load_enterprise_rag_bench_questions,
    question_ids_sha256,
)
from app.external_datasets.enterprise_rag_bench_eval import (
    score_enterprise_rag_bench_ranking,
    summarize_by_question_type,
    summarize_enterprise_rag_bench_retrieval,
)
from app.external_datasets.enterprise_rag_bench_fts import (
    load_enterprise_rag_bench_fts,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate the full-corpus EnterpriseRAG-Bench FTS5 B0 arm."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--questions",
        type=Path,
        default=DEFAULT_ENTERPRISE_RAG_BENCH_ROOT / "questions" / "test.parquet",
    )
    parser.add_argument(
        "--index-root",
        type=Path,
        default=Path(".private/external/enterprise_rag_bench/indexes/fts5"),
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path(
            "docs/enterprise_eval/evidence/"
            "ENTERPRISE_RAG_BENCH_RETRIEVAL_PROTOCOL_V1.json"
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(".private/external/enterprise_rag_bench/eval_runs"),
    )
    parser.add_argument("--max-cases", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol_bytes = args.protocol.read_bytes()
    protocol = json.loads(protocol_bytes)
    questions = [
        item
        for item in load_enterprise_rag_bench_questions(args.questions)
        if item.unique_expected_doc_ids
    ]
    full_question_count = len(questions)
    full_ids_hash = question_ids_sha256(questions)
    if full_question_count != protocol["retrieval_case_count"]:
        raise ValueError("retrieval protocol case count mismatch")
    if full_ids_hash != protocol["retrieval_question_ids_sha256"]:
        raise ValueError("retrieval protocol question ID hash mismatch")
    mode = "FORMAL_FULL_CORPUS"
    if args.max_cases is not None:
        if args.max_cases < 1:
            raise ValueError("max cases must be positive")
        questions = questions[: args.max_cases]
        mode = "PIPELINE_DEBUG"

    details = []
    with load_enterprise_rag_bench_fts(args.index_root) as index:
        for ordinal, question in enumerate(questions, start=1):
            started = time.perf_counter()
            hits = index.search(question.question, top_k=5)
            latency_ms = (time.perf_counter() - started) * 1000
            details.append(
                score_enterprise_rag_bench_ranking(
                    question,
                    ranked_source_ids=[item.source_native_id for item in hits],
                    latency_ms=latency_ms,
                )
            )
            if ordinal in {1, len(questions)} or ordinal % 25 == 0:
                print(f"evaluated {ordinal}/{len(questions)}", flush=True)
        index_manifest = index.manifest

    run_dir = args.output_root.resolve() / args.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    detail_bytes = b"".join(
        (
            json.dumps(
                item.model_dump(mode="json"),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        for item in details
    )
    (run_dir / "details.jsonl").write_bytes(detail_bytes)
    index_manifest_path = (
        args.index_root.resolve()
        / "versions"
        / index_manifest.run_id
        / "manifest.json"
    )
    payload = {
        "schema_version": "enterprise_rag_bench_fts_eval_run_v1",
        "run_id": args.run_id,
        "mode": mode,
        "arm": "bm25_fts5",
        "code_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "dataset_revision": index_manifest.dataset_revision,
        "corpus_sha256": index_manifest.corpus_sha256,
        "index_run_id": index_manifest.run_id,
        "index_manifest_sha256": hashlib.sha256(
            index_manifest_path.read_bytes()
        ).hexdigest(),
        "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
        "case_count": len(questions),
        "full_protocol_case_count": full_question_count,
        "question_ids_sha256": question_ids_sha256(questions),
        "details_sha256": hashlib.sha256(detail_bytes).hexdigest(),
        "source_type_filter_used": False,
        "answer_labels_used": False,
        "overall": summarize_enterprise_rag_bench_retrieval(
            details, group="overall"
        ).model_dump(mode="json"),
        "by_question_type": [
            item.model_dump(mode="json")
            for item in summarize_by_question_type(details)
        ],
    }
    summary_bytes = (
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    (run_dir / "summary.json").write_bytes(summary_bytes)
    print(summary_bytes.decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
