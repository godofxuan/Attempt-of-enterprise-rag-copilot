from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import time
from pathlib import Path

MODEL_ID = "BAAI/bge-reranker-v2-m3"
MODEL_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rerank frozen WixQA dense article candidates with BGE v2-m3."
    )
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cuda:1")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--depths", default="10,20,50")
    parser.add_argument(
        "--candidate-unit",
        choices=("article", "chunk"),
        default="article",
        help="Rerank deduplicated article representatives or raw dense chunks.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.batch_size <= 128:
        raise SystemExit("batch-size must be between 1 and 128")
    if not 8 <= args.max_length <= 8192:
        raise SystemExit("max-length must be between 8 and 8192")
    depths = tuple(sorted({int(item) for item in args.depths.split(",")}))
    if not depths or min(depths) < 5:
        raise SystemExit("reranker depths must be unique integers of at least 5")
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"reranker output already exists: {output}")

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    candidate_path = args.candidates.resolve()
    candidate_bytes = candidate_path.read_bytes()
    candidate_payload = json.loads(candidate_bytes)
    if candidate_payload.get("schema_version") != "wixqa_dense_candidates_v1":
        raise ValueError("unsupported WixQA candidate schema")
    if candidate_payload.get("case_count") != 200:
        raise ValueError("WixQA reranker requires the fixed 200 cases")
    depth_field = "article_depth" if args.candidate_unit == "article" else "chunk_depth"
    if candidate_payload.get(depth_field, 0) < max(depths):
        raise ValueError(f"WixQA candidate artifact does not cover {args.candidate_unit} depth")

    model_path = args.model_path.resolve()
    required = {
        "config.json",
        "model.safetensors",
        "tokenizer.json",
        "tokenizer_config.json",
    }
    missing = sorted(name for name in required if not (model_path / name).is_file())
    if missing:
        raise FileNotFoundError(f"reranker snapshot is incomplete: {missing}")

    if not args.device.startswith("cuda") or not torch.cuda.is_available():
        raise RuntimeError("this experiment requires the requested local CUDA device")
    device = torch.device(args.device)
    torch.cuda.set_device(device)
    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)

    load_started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_path,
        local_files_only=True,
        dtype=torch.float16,
    ).to(device)
    model.eval()
    model_load_ms = (time.perf_counter() - load_started) * 1000.0

    metrics: dict[int, list[dict[str, float | None]]] = {depth: [] for depth in depths}
    latencies: dict[int, list[float]] = {depth: [] for depth in depths}
    details: list[dict[str, object]] = []
    cases = candidate_payload["cases"]
    for ordinal, case in enumerate(cases, start=1):
        candidates = (
            case["candidates"] if args.candidate_unit == "article" else case["chunk_candidates"]
        )
        gold = set(case["gold_article_ids"])
        dense_ids = [item["article_id"] for item in case["candidates"]]
        case_detail: dict[str, object] = {
            "question_id": case["question_id"],
            "dense_top_5": dense_ids[:5],
            "reranker": {},
        }
        for depth in depths:
            subset = candidates[:depth]
            pairs = [(case["question"], item["text"]) for item in subset]
            started = time.perf_counter()
            scores = _score_pairs(
                pairs=pairs,
                tokenizer=tokenizer,
                model=model,
                torch=torch,
                device=device,
                batch_size=args.batch_size,
                max_length=args.max_length,
            )
            latencies[depth].append((time.perf_counter() - started) * 1000.0)
            order = sorted(range(depth), key=lambda index: (-scores[index], index))
            ranked_candidates = _dedupe_ranked_candidates([subset[index] for index in order])
            ranked_ids = [item["article_id"] for item in ranked_candidates]
            metrics[depth].append(_score_ranking(gold, ranked_ids))
            case_detail["reranker"][str(depth)] = {
                "top_5": ranked_ids[:5],
                "top_5_chunk_ids": [item["chunk_id"] for item in ranked_candidates[:5]],
                "returned_article_count": min(5, len(ranked_ids)),
            }
        details.append(case_detail)
        if ordinal in {1, len(cases)} or ordinal % 10 == 0:
            print(f"reranked {ordinal}/{len(cases)}", flush=True)

    dense_case_metrics = [
        _score_ranking(
            set(case["gold_article_ids"]),
            [item["article_id"] for item in case["candidates"]],
        )
        for case in cases
    ]
    dense_summary = _summarize(dense_case_metrics)
    arms: dict[str, object] = {"dense": dense_summary}
    for depth in depths:
        summary = _summarize(metrics[depth])
        deltas = [
            float(candidate["recall_at_5"]) - float(dense["recall_at_5"])
            for candidate, dense in zip(metrics[depth], dense_case_metrics, strict=True)
        ]
        arm_name = f"reranker_{args.candidate_unit}_top_{depth}"
        arms[arm_name] = {
            **summary,
            "recall_at_5_delta": (
                summary["article_recall_at_5"] - dense_summary["article_recall_at_5"]
            ),
            "recall_gain_case_count": sum(value > 0 for value in deltas),
            "recall_regression_case_count": sum(value < 0 for value in deltas),
            "reranker_latency_ms": _latency_summary(latencies[depth]),
            "pairs_per_query": depth,
        }
        if args.candidate_unit == "chunk":
            unique_counts = [
                len(
                    _unique_article_ids(
                        [item["article_id"] for item in case["chunk_candidates"][:depth]]
                    )
                )
                for case in cases
            ]
            arms[arm_name]["pre_rerank_unique_articles"] = _count_summary(unique_counts)
            arms[arm_name]["returned_articles_at_5"] = _count_summary(
                [min(5, value) for value in unique_counts]
            )
            capacity_key = f"raw_chunk_article_recall_at_{depth}"
            arms[arm_name]["candidate_pool_article_recall"] = candidate_payload[
                "raw_chunk_candidate_metrics"
            ].get(capacity_key)

    payload = {
        "schema_version": "wixqa_bge_reranker_eval_v1",
        "candidate_artifact": str(candidate_path),
        "candidate_artifact_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
        "case_count": len(cases),
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "model_path": str(model_path),
        "model_safetensors_sha256": _sha256_file(model_path / "model.safetensors"),
        "dtype": "float16",
        "device": args.device,
        "batch_size": args.batch_size,
        "max_length": args.max_length,
        "candidate_unit": args.candidate_unit,
        "model_load_ms": model_load_ms,
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(device),
        "python": platform.python_version(),
        "arms": arms,
        "details": details,
        "claim_boundary": {
            "dataset": "consumed public-label WixQA ExpertWritten regression",
            "answer_quality": "NOT_RUN",
            "runtime_integration": "OFFLINE_EVALUATION_ONLY",
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    output.write_bytes(content)
    print(json.dumps({"output": str(output), "arms": arms}, indent=2))
    return 0


def _score_pairs(*, pairs, tokenizer, model, torch, device, batch_size, max_length):
    scores: list[float] = []
    with torch.inference_mode():
        for start in range(0, len(pairs), batch_size):
            inputs = tokenizer(
                pairs[start : start + batch_size],
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            ).to(device)
            logits = model(**inputs, return_dict=True).logits.view(-1).float()
            scores.extend(float(item) for item in logits.cpu().tolist())
    if len(scores) != len(pairs) or any(not math.isfinite(item) for item in scores):
        raise ValueError("reranker returned invalid scores")
    return scores


def _score_ranking(gold: set[str], ranked_ids: list[str]) -> dict[str, float | None]:
    top = ranked_ids[:5]
    first = next((rank for rank, item in enumerate(top, start=1) if item in gold), None)
    dcg = sum(1.0 / math.log2(rank + 1) for rank, item in enumerate(top, start=1) if item in gold)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(5, len(gold)) + 1))
    return {
        "hit_at_1": float(bool(top and top[0] in gold)),
        "recall_at_5": len(gold.intersection(top)) / len(gold),
        "mrr_at_5": 0.0 if first is None else 1.0 / first,
        "ndcg_at_5": dcg / ideal,
        "complete_at_5": float(gold <= set(top)) if len(gold) > 1 else None,
    }


def _summarize(rows: list[dict[str, float | None]]) -> dict[str, float | int]:
    multi = [float(row["complete_at_5"]) for row in rows if row["complete_at_5"] is not None]

    def mean(name: str) -> float:
        return sum(float(row[name]) for row in rows) / len(rows)

    return {
        "article_hit_at_1": mean("hit_at_1"),
        "article_recall_at_5": mean("recall_at_5"),
        "mrr_at_5": mean("mrr_at_5"),
        "ndcg_at_5": mean("ndcg_at_5"),
        "multi_article_completeness_at_5": sum(multi) / len(multi),
        "multi_article_case_count": len(multi),
    }


def _latency_summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "mean": sum(ordered) / len(ordered),
        "p50": ordered[int(0.50 * (len(ordered) - 1))],
        "p95": ordered[int(0.95 * (len(ordered) - 1))],
    }


def _count_summary(values: list[int]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {
        "mean": sum(ordered) / len(ordered),
        "min": ordered[0],
        "p50": ordered[int(0.50 * (len(ordered) - 1))],
        "p95": ordered[int(0.95 * (len(ordered) - 1))],
        "max": ordered[-1],
    }


def _unique_article_ids(article_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(article_ids))


def _dedupe_ranked_candidates(candidates: list[dict]) -> list[dict]:
    rows = []
    seen: set[str] = set()
    for candidate in candidates:
        article_id = candidate["article_id"]
        if article_id in seen:
            continue
        seen.add(article_id)
        rows.append(candidate)
    return rows


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
