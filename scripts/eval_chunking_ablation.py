from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from scripts import _bootstrap  # noqa: F401

from rank_bm25 import BM25Okapi

from app.corpus.schemas import EvalCase
from app.domain.documents import ChunkRecord, DocumentParseError, DocumentRecord
from app.ingestion.chunking import ChunkerConfig, chunk_document
from app.ingestion.normalize import ingest_corpus
from app.ingestion.versions import govern_documents
from app.utils import tokenize_for_bm25


MODES = ("fixed", "heading", "parent_child")


def select_scored_cases(cases: list[EvalCase]) -> list[EvalCase]:
    return [
        case
        for case in cases
        if case.answer_mode == "answered" and bool(case.gold_doc_ids)
    ]


def score_retrieved_documents(
    *,
    gold_doc_ids: list[str],
    retrieved_doc_ids: list[str],
    top_k: int,
) -> dict[str, float | list[str]]:
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    if not gold_doc_ids:
        raise ValueError("gold_doc_ids must not be empty")
    seen: set[str] = set()
    ranked = []
    for doc_id in retrieved_doc_ids:
        if doc_id not in seen:
            seen.add(doc_id)
            ranked.append(doc_id)
        if len(ranked) == top_k:
            break
    gold = set(gold_doc_ids)
    recalled = gold.intersection(ranked)
    first_rank = next(
        (rank for rank, doc_id in enumerate(ranked, start=1) if doc_id in gold),
        None,
    )
    missed = [doc_id for doc_id in gold_doc_ids if doc_id not in recalled]
    return {
        "hit_at_k": 1.0 if recalled else 0.0,
        "recall_at_k": len(recalled) / len(gold),
        "reciprocal_rank": 0.0 if first_rank is None else 1.0 / first_rank,
        "full_recall": 1.0 if not missed else 0.0,
        "missed_gold_doc_ids": missed,
    }


def _mean(rows: list[dict[str, Any]], key: str) -> float:
    return sum(float(row[key]) for row in rows) / len(rows) if rows else 0.0


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, int | float]:
    return {
        "case_count": len(rows),
        "hit_at_k": _mean(rows, "hit_at_k"),
        "recall_at_k": _mean(rows, "recall_at_k"),
        "mrr": _mean(rows, "reciprocal_rank"),
        "full_recall_rate": _mean(rows, "full_recall"),
        "failure_count": sum(bool(row["missed_gold_doc_ids"]) for row in rows),
    }


def summarize_by_task(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, int | float]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["task_type"])].append(row)
    return {
        task_type: summarize_rows(task_rows)
        for task_type, task_rows in sorted(grouped.items())
    }


def _visible_to_case(chunk: ChunkRecord, case: EvalCase) -> bool:
    context = case.user_context
    return (
        chunk.tenant_id == context.tenant
        and chunk.region == context.region
        and bool(set(chunk.acl_groups).intersection(context.groups))
    )


def _rank_documents(
    *,
    chunks: list[ChunkRecord],
    bm25: BM25Okapi,
    case: EvalCase,
    top_k: int,
) -> list[dict[str, Any]]:
    scores = bm25.get_scores(tokenize_for_bm25(case.question))
    ranked_indices = sorted(
        range(len(chunks)),
        key=lambda index: (-float(scores[index]), chunks[index].chunk_id),
    )
    seen_docs: set[str] = set()
    ranked_docs: list[dict[str, Any]] = []
    for index in ranked_indices:
        chunk = chunks[index]
        if chunk.doc_id in seen_docs or not _visible_to_case(chunk, case):
            continue
        seen_docs.add(chunk.doc_id)
        ranked_docs.append(
            {
                "rank": len(ranked_docs) + 1,
                "doc_id": chunk.doc_id,
                "chunk_id": chunk.chunk_id,
                "score": float(scores[index]),
                "section_path": chunk.section_path,
                "preview": chunk.text[:160],
            }
        )
        if len(ranked_docs) == top_k:
            break
    return ranked_docs


def evaluate_mode(
    *,
    documents: list[DocumentRecord],
    cases: list[EvalCase],
    config: ChunkerConfig,
    top_k: int,
) -> dict[str, Any]:
    chunks = [
        chunk
        for document in documents
        for chunk in chunk_document(document, config)
    ]
    indexed_chunks = [chunk for chunk in chunks if chunk.indexable]
    if not indexed_chunks:
        raise ValueError(f"chunk mode {config.mode!r} produced no indexable chunks")
    chunk_ids = [chunk.chunk_id for chunk in chunks]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise AssertionError(f"chunk mode {config.mode!r} produced duplicate IDs")
    tokenized = [tokenize_for_bm25(chunk.text) for chunk in indexed_chunks]
    bm25 = BM25Okapi(tokenized)

    rows: list[dict[str, Any]] = []
    for case in cases:
        retrieved = _rank_documents(
            chunks=indexed_chunks,
            bm25=bm25,
            case=case,
            top_k=top_k,
        )
        retrieved_doc_ids = [item["doc_id"] for item in retrieved]
        metrics = score_retrieved_documents(
            gold_doc_ids=case.gold_doc_ids,
            retrieved_doc_ids=retrieved_doc_ids,
            top_k=top_k,
        )
        rows.append(
            {
                "case_id": case.case_id,
                "question": case.question,
                "task_type": case.task_type,
                "gold_doc_ids": case.gold_doc_ids,
                "retrieved_doc_ids": retrieved_doc_ids,
                "retrieved": retrieved,
                **metrics,
            }
        )
    failures = [row for row in rows if row["missed_gold_doc_ids"]]
    return {
        "chunker_config": config.model_dump(mode="json"),
        "chunk_counts": {
            "total": len(chunks),
            "indexable": len(indexed_chunks),
            "parent": sum(chunk.kind == "parent" for chunk in chunks),
            "child": sum(chunk.kind == "child" for chunk in chunks),
            "table": sum(chunk.kind == "table" for chunk in chunks),
        },
        "metrics": summarize_rows(rows),
        "by_task": summarize_by_task(rows),
        "failure_count": len(failures),
        "failures": failures,
        "details": rows,
    }


def _load_dev_cases(corpus_dir: Path) -> tuple[Path, list[EvalCase]]:
    eval_path = corpus_dir / "eval" / "dev.json"
    payload = json.loads(eval_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("dev eval file must contain a JSON array")
    return eval_path, [EvalCase.model_validate(item) for item in payload]


def evaluate_ablation(corpus_dir: Path, *, top_k: int = 5) -> dict[str, Any]:
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    corpus_dir = Path(corpus_dir).resolve()
    manifest_path = corpus_dir / "manifest.json"
    eval_path, all_cases = _load_dev_cases(corpus_dir)
    cases = select_scored_cases(all_cases)
    if not cases:
        raise ValueError("dev eval contains no answered cases with gold documents")
    governed = govern_documents(ingest_corpus(corpus_dir))
    canonical_ids = {document.doc_id for document in governed.documents}
    missing_gold = sorted(
        {
            doc_id
            for case in cases
            for doc_id in case.gold_doc_ids
            if doc_id not in canonical_ids
        }
    )
    if missing_gold:
        raise ValueError(f"gold documents are absent after governance: {missing_gold}")

    configs = {
        "fixed": ChunkerConfig(mode="fixed", chunk_size=500, overlap=80),
        "heading": ChunkerConfig(mode="heading", chunk_size=500, overlap=80),
        "parent_child": ChunkerConfig(
            mode="parent_child",
            parent_size=1000,
            child_size=250,
            overlap=80,
        ),
    }
    modes = {
        mode: evaluate_mode(
            documents=governed.documents,
            cases=cases,
            config=configs[mode],
            top_k=top_k,
        )
        for mode in MODES
    }
    return {
        "schema_version": "chunking_ablation_v1",
        "producer": "enterprise_agentic_rag_v2",
        "config": {
            "split": "dev",
            "top_k": top_k,
            "tokenizer": "jieba",
            "ranker": "BM25Okapi",
            "ranking_unit": "unique_document_by_best_visible_chunk",
            "acl_filter": True,
            "corpus_dir": str(corpus_dir),
            "corpus_manifest_sha256": hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            "eval_path": str(eval_path.resolve()),
            "eval_sha256": hashlib.sha256(eval_path.read_bytes()).hexdigest(),
        },
        "source_document_count": governed.source_document_count,
        "canonical_document_count": len(governed.documents),
        "duplicate_count": len(governed.duplicate_aliases),
        "input_case_count": len(all_cases),
        "scored_case_count": len(cases),
        "excluded_case_count": len(all_cases) - len(cases),
        "modes": modes,
    }


def _summary_payload(result: dict[str, Any]) -> dict[str, Any]:
    payload = {key: value for key, value in result.items() if key != "modes"}
    payload["modes"] = {
        mode: {
            key: value
            for key, value in mode_result.items()
            if key not in {"details", "failures"}
        }
        for mode, mode_result in result["modes"].items()
    }
    return payload


def _details_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": result["schema_version"],
        "producer": result["producer"],
        "config": result["config"],
        "modes": {
            mode: {
                "failures": mode_result["failures"],
                "details": mode_result["details"],
            }
            for mode, mode_result in result["modes"].items()
        },
    }


def _json_bytes(payload: dict[str, Any]) -> bytes:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return text.encode("utf-8")


def write_ablation_results(
    output_dir: Path,
    result: dict[str, Any],
) -> dict[str, Path]:
    output_dir = Path(output_dir)
    resolved = output_dir.resolve()
    if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
        raise PermissionError(f"refusing unsafe output directory: {resolved}")
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.staging-",
            dir=output_dir.parent,
        )
    )
    try:
        (stage / "summary.json").write_bytes(_json_bytes(_summary_payload(result)))
        (stage / "details.json").write_bytes(_json_bytes(_details_payload(result)))
        stage.rename(output_dir)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {
        "summary": output_dir / "summary.json",
        "details": output_dir / "details.json",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare v2 chunking modes with deterministic BM25 on dev.",
    )
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="New run directory for summary.json and details.json.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        result = evaluate_ablation(args.input_dir, top_k=args.top_k)
        if args.output_dir is None:
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        paths = write_ablation_results(args.output_dir, result)
        summary = _summary_payload(result)
        summary.update(
            {
                "written": True,
                "output_dir": str(Path(args.output_dir).resolve()),
                "summary_path": str(paths["summary"].resolve()),
                "details_path": str(paths["details"].resolve()),
            }
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except DocumentParseError as exc:
        print(
            "error: " + json.dumps(exc.to_dict(), ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
