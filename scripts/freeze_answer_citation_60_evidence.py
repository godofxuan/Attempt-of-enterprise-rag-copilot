from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Sequence

from app.external_datasets.wixqa import load_wixqa_questions
from app.external_datasets.wixqa_retrieval import canonical_json_bytes


SCHEMA_VERSION = "wixqa_answer_citation_60_protocol_v1"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, int(len(ordered) * fraction + 0.999999) - 1)
    return ordered[index]


def freeze_evidence(
    *,
    source_root: Path,
    source_run_dir: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    questions = load_wixqa_questions("expertwritten", source_root)
    singles = [item for item in questions if len(item.article_ids) == 1]
    multis = [item for item in questions if len(item.article_ids) > 1]
    ordering = lambda item: (_sha256_text(item.question_id), item.question_id)
    selected = sorted(singles, key=ordering)[:40] + sorted(multis, key=ordering)[:20]
    selected.sort(key=lambda item: item.question_id)
    if len(selected) != 60:
        raise ValueError("WixQA source cannot provide the frozen 40/20 cohort")

    details_path = Path(source_run_dir) / "details.jsonl"
    source_summary_path = Path(source_run_dir) / "summary.json"
    details = {
        row["question_id"]: row
        for row in (
            json.loads(line)
            for line in details_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    rows = [details[item.question_id] for item in selected]
    source_summary = json.loads(source_summary_path.read_text(encoding="utf-8"))
    cases = [
        {
            "answer_sha256": _sha256_text(item.answer),
            "case_type": "single_document"
            if len(item.article_ids) == 1
            else "multi_document",
            "gold_support_article_ids": item.article_ids,
            "question_id": item.question_id,
            "question_sha256": _sha256_text(item.question),
        }
        for item in selected
    ]
    protocol = {
        "answer_gold": (
            "Source answer is hash-bound. Human claim/span annotation is NOT_RUN."
        ),
        "case_count": 60,
        "cases": cases,
        "cohort": "WixQA ExpertWritten deterministic SHA-stratified subset",
        "human_review": {
            "double_review_required_count": 12,
            "status": "NOT_RUN",
        },
        "multi_document_count": 20,
        "selection_rule": (
            "Sort each article-count stratum by SHA256(question_id), then take "
            "40 single-article and 20 multi-article cases."
        ),
        "single_document_count": 40,
        "schema_version": SCHEMA_VERSION,
        "source_dataset": "WixQA ExpertWritten test",
    }
    citation_precisions = [
        float(row["citation_precision"])
        for row in rows
        if row["citation_precision"] is not None
    ]
    multi_rows = [row for row in rows if row["gold_article_count"] > 1]
    evidence = {
        "answer_correctness": "NOT_RUN",
        "answer_fully_correct_rate": None,
        "candidate": {
            "answered_rate": _mean(
                [
                    float(row["response_mode"] in {"answered", "partial"})
                    for row in rows
                ]
            ),
            "citation_precision": _mean(citation_precisions),
            "citation_recall": _mean(
                [float(row["citation_recall"]) for row in rows]
            ),
            "latency_ms_p50": _percentile(
                [float(row["agent_latency_ms"]) for row in rows], 0.5
            ),
            "latency_ms_p95": _percentile(
                [float(row["agent_latency_ms"]) for row in rows], 0.95
            ),
            "multi_document_citation_completeness": _mean(
                [float(row["citation_complete"]) for row in multi_rows]
            ),
            "retrieval_recall_at_5": _mean(
                [float(row["search_evidence_recall"]) for row in rows]
            ),
        },
        "claim_boundary": (
            "Retrospective deterministic subset of an immutable prior run. "
            "No answer text was retained, so this is retrieval/citation evidence, "
            "not answer-quality evidence and not a new current-SHA model run."
        ),
        "control": {
            "latency_ms_p50": _percentile(
                [float(row["b2_latency_ms"]) for row in rows], 0.5
            ),
            "latency_ms_p95": _percentile(
                [float(row["b2_latency_ms"]) for row in rows], 0.95
            ),
            "retrieval_recall_at_5": _mean(
                [float(row["b2_recall_at_5"]) for row in rows]
            ),
        },
        "critical_unsupported_numeric_or_date_count": None,
        "human_review_status": "NOT_RUN",
        "protocol_sha256": hashlib.sha256(
            canonical_json_bytes(protocol)
        ).hexdigest(),
        "schema_version": "wixqa_answer_citation_60_evidence_v1",
        "source_details_sha256": hashlib.sha256(
            details_path.read_bytes()
        ).hexdigest(),
        "source_run_code_revision": source_summary["code_revision"],
        "source_run_id": source_summary["run_id"],
        "status": "PARTIAL_AUTOMATED_ONLY",
        "supported_claim_precision": None,
    }
    return protocol, evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-run-dir", type=Path, required=True)
    parser.add_argument("--protocol-output", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol, evidence = freeze_evidence(
        source_root=args.source_root,
        source_run_dir=args.source_run_dir,
    )
    for path, payload in (
        (args.protocol_output, protocol),
        (args.evidence_output, evidence),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json_bytes(payload))
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
