from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import random
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import numpy as np

from app.security.retrieved_content import RetrievedContentGuard


MODEL_ID = "BAAI/bge-reranker-v2-m3"
MODEL_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
DEPTHS = (20, 50)
ARM_SPECS = (
    ("A0_DENSE_BASELINE", 0, "baseline"),
    ("A1_RAW20_GUARD_OFF", 20, "shadow"),
    ("A2_RAW20_GUARD_ON", 20, "enforced"),
    ("A3_RAW50_GUARD_OFF", 50, "shadow"),
    ("A4_RAW50_GUARD_ON", 50, "enforced"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen WixQA raw-chunk Guard ON/OFF final ablation."
    )
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-output", type=Path, required=True)
    parser.add_argument("--protocol-git-sha", required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--seed", type=int, default=20260904)
    parser.add_argument("--quality-repeats", type=int, default=2)
    parser.add_argument("--latency-repeats", type=int, default=3)
    parser.add_argument("--replace-public-output", action="store_true")
    return parser


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0}
    ordered = sorted(values)
    return {
        "mean": sum(ordered) / len(ordered),
        "p50": ordered[int(0.50 * (len(ordered) - 1))],
        "p95": ordered[int(0.95 * (len(ordered) - 1))],
    }


def _median_summary(values: list[dict[str, float]]) -> dict[str, float]:
    return {key: statistics.median(row[key] for row in values) for key in ("mean", "p50", "p95")}


def _score_ranking(gold_ids: set[str], ranked_article_ids: list[str]) -> dict[str, float | None]:
    top = ranked_article_ids[:5]
    first = next((rank for rank, article_id in enumerate(top, start=1) if article_id in gold_ids), None)
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, article_id in enumerate(top, start=1)
        if article_id in gold_ids
    )
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(5, len(gold_ids)) + 1))
    return {
        "hit_at_1": float(bool(top and top[0] in gold_ids)),
        "recall_at_5": len(gold_ids.intersection(top)) / len(gold_ids),
        "mrr_at_5": 0.0 if first is None else 1.0 / first,
        "ndcg_at_5": dcg / ideal,
        "complete_at_5": float(gold_ids.issubset(top)) if len(gold_ids) > 1 else None,
    }


def _metric_summary(rows: list[dict[str, float | None]]) -> dict[str, float | int]:
    multi = [float(row["complete_at_5"]) for row in rows if row["complete_at_5"] is not None]
    return {
        "article_hit_at_1": sum(float(row["hit_at_1"]) for row in rows) / len(rows),
        "article_recall_at_5": sum(float(row["recall_at_5"]) for row in rows) / len(rows),
        "mrr_at_5": sum(float(row["mrr_at_5"]) for row in rows) / len(rows),
        "ndcg_at_5": sum(float(row["ndcg_at_5"]) for row in rows) / len(rows),
        "multi_article_complete_count": int(sum(multi)),
        "multi_article_case_count": len(multi),
        "multi_article_completeness_at_5": 0.0 if not multi else sum(multi) / len(multi),
    }


def _guard_scan(
    *, candidates: list[dict[str, Any]], guard: RetrievedContentGuard
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    admitted: list[dict[str, Any]] = []
    rule_ids: Counter[str] = Counter()
    quarantined_gold_article_count = 0
    for candidate in candidates:
        decision = guard.scan(str(candidate["text"]))
        if decision.disposition == "ADMIT":
            admitted.append(candidate)
            continue
        rule_ids.update(decision.rule_ids)
        if candidate.get("is_gold_article"):
            quarantined_gold_article_count += 1
    return admitted, {
        "input_chunks": len(candidates),
        "admitted_chunks": len(admitted),
        "quarantined_chunks": len(candidates) - len(admitted),
        "quarantined_gold_article_chunks": quarantined_gold_article_count,
        "rule_id_histogram": dict(sorted(rule_ids.items())),
    }


def _rank_after_score(
    *, candidates: list[dict[str, Any]], scores: list[float]
) -> tuple[list[str], list[str]]:
    if len(candidates) != len(scores):
        raise ValueError("cross-encoder score count differs from admitted candidate count")
    if any(not math.isfinite(score) for score in scores):
        raise ValueError("cross-encoder returned a non-finite score")
    ordered = sorted(
        zip(candidates, scores, strict=True),
        key=lambda row: (-row[1], int(row[0]["dense_rank"]), str(row[0]["chunk_id"])),
    )
    articles: list[str] = []
    chunk_ids: list[str] = []
    seen: set[str] = set()
    for candidate, _score in ordered:
        article_id = str(candidate["article_id"])
        if article_id in seen:
            continue
        seen.add(article_id)
        articles.append(article_id)
        chunk_ids.append(str(candidate["chunk_id"]))
    return articles[:5], chunk_ids[:5]


def _run_rerank_arm(
    *,
    cases: list[dict[str, Any]],
    depth: int,
    guard_mode: str,
    guard: RetrievedContentGuard,
    score_fn: Callable[[str, list[str]], list[float]],
) -> dict[str, Any]:
    metrics: list[dict[str, float | None]] = []
    signatures: dict[str, dict[str, list[str]]] = {}
    timings = {
        "candidate_generation_ms": [],
        "guard_ms": [],
        "shadow_guard_ms": [],
        "reranker_ms": [],
        "dedup_ms": [],
        "total_ms": [],
    }
    aggregate = Counter()
    rule_ids: Counter[str] = Counter()
    affected_questions: set[str] = set()
    gold_affected_questions: set[str] = set()
    short_result_count = 0

    for case in cases:
        question_id = str(case["question_id"])
        gold_ids = set(case["gold_article_ids"])
        subset = [dict(item, is_gold_article=item["article_id"] in gold_ids) for item in case["raw_candidates"][:depth]]
        if len(subset) != depth:
            raise ValueError(f"{question_id} is missing frozen raw candidates for depth {depth}")

        started = time.perf_counter()
        admitted, diagnostic = _guard_scan(candidates=subset, guard=guard)
        guard_elapsed = (time.perf_counter() - started) * 1000.0
        if diagnostic["input_chunks"] != diagnostic["admitted_chunks"] + diagnostic["quarantined_chunks"]:
            raise AssertionError("Guard accounting invariant failed")
        aggregate.update({
            "input_chunks": diagnostic["input_chunks"],
            "admitted_chunks": diagnostic["admitted_chunks"],
            "quarantined_chunks": diagnostic["quarantined_chunks"],
            "quarantined_gold_article_chunks": diagnostic["quarantined_gold_article_chunks"],
        })
        rule_ids.update(diagnostic["rule_id_histogram"])
        if diagnostic["quarantined_chunks"]:
            affected_questions.add(question_id)
        if diagnostic["quarantined_gold_article_chunks"]:
            gold_affected_questions.add(question_id)

        eligible = admitted if guard_mode == "enforced" else subset
        score_started = time.perf_counter()
        scores = score_fn(str(case["question"]), [str(item["text"]) for item in eligible])
        reranker_elapsed = (time.perf_counter() - score_started) * 1000.0
        if guard_mode == "enforced" and len(eligible) != diagnostic["admitted_chunks"]:
            raise AssertionError("Guarded scorer received a quarantined chunk")

        dedup_started = time.perf_counter()
        article_ids, chunk_ids = _rank_after_score(candidates=eligible, scores=scores)
        dedup_elapsed = (time.perf_counter() - dedup_started) * 1000.0
        if len(article_ids) < 5:
            short_result_count += 1
        metrics.append(_score_ranking(gold_ids, article_ids))
        signatures[question_id] = {"article_ids": article_ids, "chunk_ids": chunk_ids}
        candidate_elapsed = float(case["candidate_generation_ms"])
        timings["candidate_generation_ms"].append(candidate_elapsed)
        timings["guard_ms" if guard_mode == "enforced" else "shadow_guard_ms"].append(guard_elapsed)
        timings["reranker_ms"].append(reranker_elapsed)
        timings["dedup_ms"].append(dedup_elapsed)
        timings["total_ms"].append(
            candidate_elapsed
            + (guard_elapsed if guard_mode == "enforced" else 0.0)
            + reranker_elapsed
            + dedup_elapsed
        )

    if guard_mode == "enforced" and aggregate["admitted_chunks"] + aggregate["quarantined_chunks"] != aggregate["input_chunks"]:
        raise AssertionError("aggregate Guard accounting invariant failed")
    return {
        "metrics": _metric_summary(metrics),
        "latency_ms": {key: _summary(value) for key, value in timings.items()},
        "guard": {
            **dict(aggregate),
            "affected_question_count": len(affected_questions),
            "gold_affected_question_count": len(gold_affected_questions),
            "rule_id_histogram": dict(sorted(rule_ids.items())),
            "scored_quarantined_chunks": 0 if guard_mode == "enforced" else None,
            "shadow_only": guard_mode == "shadow",
        },
        "returned_less_than_5_count": short_result_count,
        "signatures": signatures,
    }


def _validate_candidate_parity(cases: list[dict[str, Any]]) -> None:
    for case in cases:
        raw = case["raw_candidates"]
        if len(raw) < 50:
            raise ValueError(f"{case['question_id']} has fewer than 50 raw candidates")
        identifiers = [(item["dense_rank"], item["chunk_id"]) for item in raw]
        if identifiers != sorted(identifiers):
            raise ValueError(f"{case['question_id']} raw candidates are not in stable dense order")
        if len({item["chunk_id"] for item in raw[:50]}) != 50:
            raise ValueError(f"{case['question_id']} raw candidate chunk IDs are not unique")
        if [item["chunk_id"] for item in raw[:20]] != [item["chunk_id"] for item in raw[:50]][:20]:
            raise AssertionError("Top-20 must be the Top-50 prefix")


def _guard_rules_sha256() -> str:
    root = Path(__file__).resolve().parents[1]
    paths = [root / "app" / "security" / "retrieved_content.py", root / "app" / "domain" / "retrieved_security.py"]
    return _sha256_bytes(b"".join(path.read_bytes() for path in paths))


def _load_model(*, model_path: Path, device_name: str, torch: Any, tokenizer_type: Any, model_type: Any):
    if not device_name.startswith("cuda") or not torch.cuda.is_available():
        raise RuntimeError("final reranker ablation requires an available CUDA device")
    required = ("model.safetensors", "config.json")
    missing = [name for name in required if not (model_path / name).is_file()]
    if missing:
        raise FileNotFoundError(f"reranker snapshot is incomplete: {missing}")
    device = torch.device(device_name)
    torch.cuda.set_device(device)
    tokenizer = tokenizer_type.from_pretrained(model_path, local_files_only=True)
    model = model_type.from_pretrained(model_path, local_files_only=True, dtype=torch.float16).to(device)
    model.eval()
    return tokenizer, model, device


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.batch_size != 16 or args.max_length != 512:
        raise SystemExit("the frozen protocol requires --batch-size 16 and --max-length 512")
    if args.quality_repeats < 2 or args.latency_repeats != 3:
        raise SystemExit("the frozen protocol requires at least two quality repeats and exactly three latency repeats")
    if args.output.resolve().exists() or (
        args.public_output.resolve().exists() and not args.replace_public_output
    ):
        raise FileExistsError("final output paths must not already exist")

    candidate_bytes = args.candidates.resolve().read_bytes()
    candidate_payload = json.loads(candidate_bytes)
    if candidate_payload.get("schema_version") != "wixqa_final_raw_candidates_v1":
        raise ValueError("unsupported final raw candidate artifact")
    cases = candidate_payload["cases"]
    if candidate_payload.get("case_count") != 200 or len(cases) != 200:
        raise ValueError("final protocol requires the fixed 200-case ExpertWritten cohort")
    _validate_candidate_parity(cases)

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    load_started = time.perf_counter()
    tokenizer, model, device = _load_model(
        model_path=args.model_path.resolve(),
        device_name=args.device,
        torch=torch,
        tokenizer_type=AutoTokenizer,
        model_type=AutoModelForSequenceClassification,
    )
    model_load_ms = (time.perf_counter() - load_started) * 1000.0

    def score_fn(question: str, texts: list[str]) -> list[float]:
        scores: list[float] = []
        with torch.inference_mode():
            for start in range(0, len(texts), args.batch_size):
                pairs = [(question, text) for text in texts[start : start + args.batch_size]]
                inputs = tokenizer(
                    pairs,
                    padding=True,
                    truncation=True,
                    max_length=args.max_length,
                    return_tensors="pt",
                ).to(device)
                logits = model(**inputs, return_dict=True).logits.view(-1).float()
                scores.extend(float(score) for score in logits.cpu().tolist())
        return scores

    dense_rows = [_score_ranking(set(case["gold_article_ids"]), list(case["dense_article_ids"])) for case in cases]
    dense_latency = [float(case["candidate_generation_ms"]) for case in cases]
    arms: dict[str, dict[str, Any]] = {
        "A0_DENSE_BASELINE": {
            "metrics": _metric_summary(dense_rows),
            "latency_ms": {
                "candidate_generation_ms": _summary(dense_latency),
                "guard_ms": _summary([]),
                "reranker_ms": _summary([]),
                "dedup_ms": _summary([]),
                "total_ms": _summary(dense_latency),
            },
            "guard": None,
            "returned_less_than_5_count": sum(len(case["dense_article_ids"][:5]) < 5 for case in cases),
        }
    }
    private_details: dict[str, list[dict[str, Any]]] = {}
    guard = RetrievedContentGuard()
    for arm_name, depth, mode in ARM_SPECS[1:]:
        runs = [
            _run_rerank_arm(cases=cases, depth=depth, guard_mode=mode, guard=guard, score_fn=score_fn)
            for _ in range(args.latency_repeats)
        ]
        first = runs[0]
        quality_signatures = first["signatures"]
        if any(run["signatures"] != quality_signatures for run in runs[1:args.quality_repeats]):
            raise RuntimeError(f"{arm_name} ranking changed across quality repeats")
        latency_keys = (
            "candidate_generation_ms",
            "guard_ms",
            "shadow_guard_ms",
            "reranker_ms",
            "dedup_ms",
            "total_ms",
        )
        latency = {key: _median_summary([run["latency_ms"][key] for run in runs]) for key in latency_keys}
        arms[arm_name] = {
            "metrics": first["metrics"],
            "latency_ms": latency,
            "latency_run_level": [run["latency_ms"] for run in runs],
            "quality_repeat_identical": True,
            "guard": first["guard"],
            "returned_less_than_5_count": first["returned_less_than_5_count"],
        }
        private_details[arm_name] = [
            {"question_id": question_id, **signature}
            for question_id, signature in sorted(first["signatures"].items())
        ]

    top20 = arms["A2_RAW20_GUARD_ON"]
    top50 = arms["A4_RAW50_GUARD_ON"]
    top50_metrics = top50["metrics"]
    top20_metrics = top20["metrics"]
    gains = [
        float(top50_metrics[key]) - float(top20_metrics[key])
        for key in ("article_recall_at_5", "ndcg_at_5", "mrr_at_5", "multi_article_completeness_at_5")
    ]
    regressions = [
        float(top50_metrics[key]) - float(top20_metrics[key])
        for key in ("article_recall_at_5", "ndcg_at_5", "mrr_at_5")
    ]
    top50_p95 = float(top50["latency_ms"]["total_ms"]["p95"])
    top20_p95 = float(top20["latency_ms"]["total_ms"]["p95"])
    top50_passes = any(value > 0 for value in gains) and all(value >= -0.005 for value in regressions) and top50_p95 <= 650.0 and top50_p95 <= 3.0 * top20_p95
    selected_profile = "GUARDED_RAW_CHUNK_TOP50" if top50_passes else "GUARDED_RAW_CHUNK_TOP20"
    guard_gap = {
        "top20_recall_gap": float(arms["A1_RAW20_GUARD_OFF"]["metrics"]["article_recall_at_5"]) - float(top20_metrics["article_recall_at_5"]),
        "top20_ndcg_gap": float(arms["A1_RAW20_GUARD_OFF"]["metrics"]["ndcg_at_5"]) - float(top20_metrics["ndcg_at_5"]),
        "top50_recall_gap": float(arms["A3_RAW50_GUARD_OFF"]["metrics"]["article_recall_at_5"]) - float(top50_metrics["article_recall_at_5"]),
        "top50_ndcg_gap": float(arms["A3_RAW50_GUARD_OFF"]["metrics"]["ndcg_at_5"]) - float(top50_metrics["ndcg_at_5"]),
    }
    false_positive_review_required = any(value > 0.01 for value in guard_gap.values())

    base = {
        "schema_version": "wixqa_raw_chunk_guard_final_v1",
        "protocol": "docs/wixqa_reranker/RAW_CHUNK_GUARD_FINAL_PROTOCOL.md",
        "protocol_git_sha": args.protocol_git_sha,
        "evaluation_git_sha": __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], text=True, encoding="utf-8").strip(),
        "candidate_artifact_sha256": _sha256_bytes(candidate_bytes),
        "candidate_provenance": {key: candidate_payload[key] for key in (
            "cohort", "consumption", "case_count", "question_ids_sha256", "dataset_manifest_sha256", "index_run_id", "index_manifest_sha256", "index_artifacts", "embedding_model", "embedding_model_sha256", "candidate_k", "candidate_generation_latency_ms"
        )},
        "reranker": {
            "model_id": MODEL_ID,
            "revision": MODEL_REVISION,
            "model_safetensors_sha256": _sha256_file(args.model_path.resolve() / "model.safetensors"),
            "dtype": "float16",
            "batch_size": args.batch_size,
            "max_length": args.max_length,
            "model_load_ms": model_load_ms,
        },
        "environment": {
            "device": args.device,
            "gpu": torch.cuda.get_device_name(device),
            "python": platform.python_version(),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "transformers": __import__("transformers").__version__,
            "seed": args.seed,
        },
        "guard": {"rules_sha256": _guard_rules_sha256(), "order": "full_text_scan_before_cross_encoder", "dense_backfill": False},
        "candidate_parity": {"off20_equals_on20": True, "off50_equals_on50": True, "top20_is_top50_prefix": True},
        "arms": arms,
        "guard_on_off_gap": guard_gap,
        "guard_false_positive_review_required": false_positive_review_required,
        "promotion": {
            "safe_default": "CURRENT_FAST_RETRIEVAL_PATH",
            "optional_gpu_quality_profile": selected_profile,
            "top50_promotion_passed": top50_passes,
            "top50_total_p95_ms": top50_p95,
            "top20_total_p95_ms": top20_p95,
        },
        "claim_boundary": {
            "evaluation": "CONSUMED_RETROSPECTIVE_RETRIEVAL_REPLAY",
            "answer_quality": "NOT_RUN",
            "blind_or_independent_validation": "NOT_RUN",
            "guard_off_runtime_eligible": False,
        },
    }
    private_payload = {**base, "private_rank_signatures": private_details}
    public_bytes = (json.dumps(base, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")
    private_bytes = (json.dumps(private_payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.public_output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_bytes(private_bytes)
    public_path = args.public_output.resolve()
    public_stage = public_path.with_suffix(public_path.suffix + ".tmp")
    public_stage.write_bytes(public_bytes)
    public_stage.replace(public_path)
    print(json.dumps({"output": str(args.output.resolve()), "public_output": str(args.public_output.resolve()), "public_sha256": _sha256_bytes(public_bytes), "promotion": base["promotion"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
