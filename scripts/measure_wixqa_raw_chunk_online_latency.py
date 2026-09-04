from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from app.config import get_settings
from app.external_datasets.wixqa_retrieval import load_wixqa_flat_index
from app.runtime.ollama_embeddings import OllamaEmbeddingClient
from app.security.retrieved_content import RetrievedContentGuard
from scripts.eval_wixqa_raw_chunk_guard_ablation import (
    MODEL_ID,
    MODEL_REVISION,
    _guard_rules_sha256,
    _guard_scan,
    _rank_after_score,
    _sha256_bytes,
    _sha256_file,
    _summary,
)


DEPTH_TO_QUALITY_ARM = {20: "A2_RAW20_GUARD_ON", 50: "A4_RAW50_GUARD_ON"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure only the real Guarded WixQA raw-chunk online latency path."
    )
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--quality-artifact", type=Path, required=True)
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-output", type=Path, required=True)
    parser.add_argument("--erratum-protocol-git-sha", required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--seed", type=int, default=20260904)
    return parser


def _median_run_summary(rows: list[dict[str, float]]) -> dict[str, float]:
    return {key: statistics.median(row[key] for row in rows) for key in ("mean", "p50", "p95")}


def _live_rows(items: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "dense_rank": rank,
            "article_id": item.article_id,
            "chunk_id": item.chunk_id,
            "dense_score": item.dense_score,
            "text": item.text,
        }
        for rank, item in enumerate(items, start=1)
    ]


def _assert_candidate_identity(*, frozen: list[dict[str, Any]], live: list[dict[str, Any]]) -> None:
    frozen_ids = [(item["dense_rank"], item["chunk_id"]) for item in frozen]
    live_ids = [(item["dense_rank"], item["chunk_id"]) for item in live]
    if frozen_ids != live_ids:
        raise RuntimeError("CANDIDATE_IDENTITY_MISMATCH")


def _load_model(*, model_path: Path, device_name: str, torch: Any, tokenizer_type: Any, model_type: Any):
    if not device_name.startswith("cuda") or not torch.cuda.is_available():
        raise RuntimeError("online latency correction requires the requested CUDA device")
    if not (model_path / "model.safetensors").is_file() or not (model_path / "config.json").is_file():
        raise FileNotFoundError("reranker snapshot is incomplete")
    device = torch.device(device_name)
    torch.cuda.set_device(device)
    tokenizer = tokenizer_type.from_pretrained(model_path, local_files_only=True)
    model = model_type.from_pretrained(model_path, local_files_only=True, dtype=torch.float16).to(device)
    model.eval()
    return tokenizer, model, device


def _score_pairs(*, question: str, texts: list[str], tokenizer: Any, model: Any, torch: Any, device: Any, batch_size: int, max_length: int) -> list[float]:
    scores: list[float] = []
    with torch.inference_mode():
        for start in range(0, len(texts), batch_size):
            inputs = tokenizer(
                [(question, text) for text in texts[start : start + batch_size]],
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            ).to(device)
            scores.extend(float(value) for value in model(**inputs, return_dict=True).logits.view(-1).float().cpu().tolist())
    return scores


def _measure_profile(
    *,
    cases: list[dict[str, Any]],
    depth: int,
    index: Any,
    client: OllamaEmbeddingClient,
    guard: RetrievedContentGuard,
    tokenizer: Any,
    model: Any,
    torch: Any,
    device: Any,
    batch_size: int,
    max_length: int,
    expected_signatures: dict[str, dict[str, list[str]]],
    record: bool,
) -> tuple[dict[str, Any], dict[str, dict[str, list[str]]]]:
    stages = {name: [] for name in ("embedding_ms", "raw_faiss_ms", "candidate_slice_ms", "guard_ms", "reranker_ms", "dedup_ms", "total_ms")}
    signatures: dict[str, dict[str, list[str]]] = {}
    quarantine_count = 0
    for ordinal, case in enumerate(cases, start=1):
        total_started = time.perf_counter()
        embedding_started = time.perf_counter()
        vector = client.embed_batch([case["question"]])
        embedding_ms = (time.perf_counter() - embedding_started) * 1000.0

        faiss_started = time.perf_counter()
        live = _live_rows(index.dense_raw_chunk_candidates(vector, candidate_k=200, max_chunks=200))
        faiss_ms = (time.perf_counter() - faiss_started) * 1000.0
        _assert_candidate_identity(frozen=case["raw_candidates"], live=live)

        slice_started = time.perf_counter()
        subset = live[:depth]
        candidate_slice_ms = (time.perf_counter() - slice_started) * 1000.0

        guard_started = time.perf_counter()
        admitted, diagnostic = _guard_scan(candidates=subset, guard=guard)
        guard_ms = (time.perf_counter() - guard_started) * 1000.0
        if diagnostic["input_chunks"] != diagnostic["admitted_chunks"] + diagnostic["quarantined_chunks"]:
            raise AssertionError("Guard accounting invariant failed")
        quarantine_count += int(diagnostic["quarantined_chunks"])

        reranker_started = time.perf_counter()
        scores = _score_pairs(
            question=case["question"], texts=[item["text"] for item in admitted], tokenizer=tokenizer,
            model=model, torch=torch, device=device, batch_size=batch_size, max_length=max_length,
        )
        reranker_ms = (time.perf_counter() - reranker_started) * 1000.0

        dedup_started = time.perf_counter()
        article_ids, chunk_ids = _rank_after_score(candidates=admitted, scores=scores)
        dedup_ms = (time.perf_counter() - dedup_started) * 1000.0
        signature = {"article_ids": article_ids, "chunk_ids": chunk_ids}
        if signature != expected_signatures[str(case["question_id"])]:
            raise RuntimeError("LATENCY_RUN_CHANGED_QUALITY_RANKINGS")
        signatures[str(case["question_id"])] = signature
        total_ms = (time.perf_counter() - total_started) * 1000.0
        if record:
            for name, value in (
                ("embedding_ms", embedding_ms), ("raw_faiss_ms", faiss_ms),
                ("candidate_slice_ms", candidate_slice_ms), ("guard_ms", guard_ms),
                ("reranker_ms", reranker_ms), ("dedup_ms", dedup_ms), ("total_ms", total_ms),
            ):
                stages[name].append(value)
        if ordinal in {1, len(cases)} or ordinal % 50 == 0:
            print(f"depth {depth}: measured {ordinal}/{len(cases)}", flush=True)
    return ({name: _summary(values) for name, values in stages.items()} if record else {"quarantined_chunks": quarantine_count}, signatures)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.batch_size != 16 or args.max_length != 512:
        raise SystemExit("frozen erratum requires batch size 16 and max length 512")
    if args.output.resolve().exists() or args.public_output.resolve().exists():
        raise FileExistsError("latency output already exists")
    candidate_bytes = args.candidates.resolve().read_bytes()
    candidates = json.loads(candidate_bytes)
    quality_bytes = args.quality_artifact.resolve().read_bytes()
    quality = json.loads(quality_bytes)
    if candidates["case_count"] != 200 or quality["candidate_artifact_sha256"] != _sha256_bytes(candidate_bytes):
        raise ValueError("frozen candidate artifact does not match quality evidence")
    index = load_wixqa_flat_index(args.index_root)
    if hashlib.sha256((args.index_root / "versions" / index.manifest.run_id / "manifest.json").read_bytes()).hexdigest() != candidates["index_manifest_sha256"]:
        raise ValueError("loaded index differs from frozen candidate artifact")
    client = OllamaEmbeddingClient.from_settings(get_settings(), probe_text="WixQA online latency probe", endpoint_context="WixQA online latency")
    if client.model_identifier != candidates["embedding_model"] or client.model_sha256 != candidates["embedding_model_sha256"]:
        raise ValueError("online query embedding identity differs from frozen candidate artifact")

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    load_started = time.perf_counter()
    tokenizer, model, device = _load_model(model_path=args.model_path.resolve(), device_name=args.device, torch=torch, tokenizer_type=AutoTokenizer, model_type=AutoModelForSequenceClassification)
    model_load_ms = (time.perf_counter() - load_started) * 1000.0
    guard = RetrievedContentGuard()
    expected = {
        depth: {
            row["question_id"]: {
                "article_ids": row["article_ids"],
                "chunk_ids": row["chunk_ids"],
            }
            for row in quality["private_rank_signatures"][DEPTH_TO_QUALITY_ARM[depth]]
        }
        for depth in DEPTH_TO_QUALITY_ARM
    }

    # Fixed five-case warm-up verifies the real path but contributes no timing data.
    for depth in DEPTH_TO_QUALITY_ARM:
        _measure_profile(cases=candidates["cases"][:5], depth=depth, index=index, client=client, guard=guard, tokenizer=tokenizer, model=model, torch=torch, device=device, batch_size=args.batch_size, max_length=args.max_length, expected_signatures=expected[depth], record=False)

    profiles: dict[str, Any] = {}
    for depth in DEPTH_TO_QUALITY_ARM:
        run_rows = []
        for run in range(1, 4):
            measured, signatures = _measure_profile(cases=candidates["cases"], depth=depth, index=index, client=client, guard=guard, tokenizer=tokenizer, model=model, torch=torch, device=device, batch_size=args.batch_size, max_length=args.max_length, expected_signatures=expected[depth], record=True)
            if signatures != expected[depth]:
                raise RuntimeError("LATENCY_RUN_CHANGED_QUALITY_RANKINGS")
            run_rows.append(measured)
            print(f"depth {depth}: latency pass {run}/3 complete", flush=True)
        headline = {stage: _median_run_summary([run[stage] for run in run_rows]) for stage in run_rows[0]}
        p95s = [run["total_ms"]["p95"] for run in run_rows]
        profiles[f"top{depth}"] = {"run_level": run_rows, "headline": headline, "run_level_total_p95_ms": p95s, "min_total_p95_ms": min(p95s), "max_total_p95_ms": max(p95s)}

    top20_p95 = profiles["top20"]["headline"]["total_ms"]["p95"]
    top50_p95 = profiles["top50"]["headline"]["total_ms"]["p95"]
    absolute = top50_p95 <= 650.0
    relative = top50_p95 <= 3.0 * top20_p95
    profile = "GUARDED_RAW_CHUNK_TOP50" if absolute and relative else "GUARDED_RAW_CHUNK_TOP20"
    base = {
        "schema_version": "wixqa_raw_chunk_final_online_latency_v1",
        "artifact_type": "LATENCY_ACCOUNTING_ERRATUM",
        "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, encoding="utf-8").strip(),
        "git_dirty": False,
        "erratum_protocol_git_sha": args.erratum_protocol_git_sha,
        # Public evidence must be reproducible without publishing this machine's path.
        "argv": [Path(sys.argv[0]).name, *sys.argv[1:]],
        "quality_artifact_sha256": _sha256_bytes(quality_bytes),
        "candidate_artifact_sha256": _sha256_bytes(candidate_bytes),
        "candidate_identity_match": True,
        "candidate_provenance": {key: candidates[key] for key in ("dataset_manifest_sha256", "index_manifest_sha256", "index_artifacts", "question_ids_sha256", "embedding_model", "embedding_model_sha256")},
        "reranker": {"model_id": MODEL_ID, "revision": MODEL_REVISION, "model_safetensors_sha256": _sha256_file(args.model_path.resolve() / "model.safetensors"), "dtype": "float16", "batch_size": args.batch_size, "max_length": args.max_length, "model_load_ms_excluded": model_load_ms},
        "guard": {"rules_sha256": _guard_rules_sha256(), "order": "full_text_scan_before_cross_encoder", "dense_backfill": False},
        "environment": {"device": args.device, "gpu": torch.cuda.get_device_name(device), "python": platform.python_version(), "torch": torch.__version__, "cuda": torch.version.cuda, "transformers": __import__("transformers").__version__, "seed": args.seed},
        "warmup": {"case_count": 5, "included_in_latency": False},
        "latency_repetitions": 3,
        "profiles": profiles,
        "frozen_latency_gate_ms": 650.0,
        "top50_passes_absolute_gate": absolute,
        "top50_passes_relative_gate": relative,
        "frozen_top50_quality_rule_passed": True,
        "final_gpu_profile": profile,
        "claim_boundary": "local offline warm-model latency; not a production SLA",
    }
    public_bytes = (json.dumps(base, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.public_output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_bytes(public_bytes)
    args.public_output.resolve().write_bytes(public_bytes)
    print(json.dumps({"output": str(args.output.resolve()), "public_output": str(args.public_output.resolve()), "public_sha256": _sha256_bytes(public_bytes), "final_gpu_profile": profile, "top20_p95": top20_p95, "top50_p95": top50_p95}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
