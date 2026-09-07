"""Frozen 200-question retrieval replay through serving components, no answers."""

import argparse
import hashlib
import json
import math
import platform
import time
from pathlib import Path

import numpy as np

from app.agent.tools_v2 import V2ToolRegistry
from app.config import get_settings
from app.domain.agent import AgentAction, BudgetState
from app.domain.queries import SearchRequest, UserContext
from app.domain.retrieved_security import GuardedSearchResult
from app.evaluation.wixqa_serving_snapshot import adapt_wixqa_snapshot
from app.external_datasets.wixqa_retrieval import load_wixqa_flat_index
from app.retrieval.local_cross_encoder import LocalCrossEncoder
from app.retrieval.pipeline import HybridRetrievalPipeline
from app.runtime.ollama_embeddings import OllamaEmbeddingClient
from app.security.reranking_admission import RerankingContentAdmission
from app.security.retrieved_admission import RetrievedContentAdmission
from scripts.measure_wixqa_raw_chunk_online_latency import _git_state


def metrics(gold, ranked):
    gold = set(gold)
    top = list(dict.fromkeys(ranked))[:5]
    positions = [i for i, item in enumerate(top, 1) if item in gold]
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(gold), 5) + 1))
    return {
        "macro_article_recall_at_5": len(gold.intersection(top)) / len(gold),
        "hit_at_1": int(bool(top and top[0] in gold)),
        "hit_at_5": int(bool(positions)),
        "mrr_at_5": 1 / positions[0] if positions else 0,
        "ndcg_at_5": sum(1 / math.log2(i + 1) for i in positions) / ideal,
        "all_gold_at_5": int(gold.issubset(top)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("run directory exists; do not overwrite evidence")
    protocol_bytes = args.protocol.read_bytes()
    protocol = json.loads(protocol_bytes)
    candidate_bytes = args.candidates.read_bytes()
    if hashlib.sha256(candidate_bytes).hexdigest() != protocol["candidate_artifact_sha256"]:
        raise ValueError("candidate artifact differs from protocol")
    source = json.loads(candidate_bytes)
    if (
        len(source["cases"]) != 200
        or source["question_ids_sha256"] != protocol["question_ids_sha256"]
    ):
        raise ValueError("frozen question identity differs")
    active = json.loads((args.index_root / "active.json").read_bytes())
    if active["manifest_sha256"] != protocol["index_manifest_sha256"]:
        raise ValueError("index differs from frozen protocol")
    identity = _git_state()
    index = load_wixqa_flat_index(args.index_root)
    snapshot = adapt_wixqa_snapshot(index, args.index_root / "versions" / active["run_id"])
    assert snapshot.faiss_index is index.faiss_index and snapshot.bm25 is index.bm25
    assert [(c.chunk_id, c.text) for c in snapshot.chunks] == [
        (c.chunk_id, c.text) for c in index.chunks
    ]
    client = OllamaEmbeddingClient.from_settings(get_settings())
    if client.model_sha256 != protocol["embedding_sha256"]:
        raise ValueError("embedding digest differs from protocol")
    import torch

    torch.manual_seed(protocol["seed"])
    scorer = LocalCrossEncoder(args.model_path, device="cuda")
    started = time.perf_counter()
    scorer.warmup()
    warmup_ms = (time.perf_counter() - started) * 1000
    args.output.mkdir(parents=True)
    manifest = {
        "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
        "protocol": protocol,
        "source_identity": identity,
        "python": platform.python_version(),
        "torch": torch.__version__,
        "gpu": torch.cuda.get_device_name(),
        "warmup_ms": warmup_ms,
        "index_equivalence": "same FAISS/BM25 objects; exact ordered chunk IDs and text",
        "adapter_manifest_sha256": snapshot.version.manifest_sha256,
        "status": "RUNNING",
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    user = UserContext(
        user_id="benchmark", tenant_id="wixqa-benchmark", region="global", groups=["benchmark"]
    )
    rows = []
    profiles = protocol["profiles"]
    with (args.output / "rows.jsonl").open("x", encoding="utf-8") as handle:
        for ordinal, case in enumerate(source["cases"]):
            embed_started = time.perf_counter()
            vector = client.embed_text(case["question"])
            embedding_ms = (time.perf_counter() - embed_started) * 1000
            pipeline = HybridRetrievalPipeline(snapshot, embed_text=lambda _: vector)

            class Navigator:
                def search_ranked(self, request):
                    return pipeline.ranked_candidates_for_guard(request)

            for profile in profiles[ordinal % 4 :] + profiles[: ordinal % 4]:
                admission = (
                    RerankingContentAdmission(search_scorer=scorer)
                    if profile.startswith("safe_dense_raw")
                    else RetrievedContentAdmission()
                )
                registry = V2ToolRegistry(
                    Navigator(), admission=admission, retrieval_profile=profile
                )
                action = AgentAction(
                    sequence=1,
                    tool="search",
                    purpose="frozen retrieval replay",
                    aspect="answer",
                    search_request=SearchRequest(
                        user=user,
                        query=case["question"],
                        purpose="frozen retrieval replay",
                        top_k=5,
                        candidate_k=200,
                        mode="hybrid",
                        include_parent=False,
                    ),
                )
                start = time.perf_counter()
                result = registry.run(action, BudgetState())
                latency_ms = (time.perf_counter() - start) * 1000
                hits = result.result.hits if isinstance(result.result, GuardedSearchResult) else ()
                ranked = [item.hit.doc_id for item in hits]
                row = {
                    "question_id": case["question_id"],
                    "profile": profile,
                    "latency_ms_excluding_shared_embedding": latency_ms,
                    "shared_embedding_ms": embedding_ms,
                    "metrics": metrics(case["gold_article_ids"], ranked),
                    "status": result.status,
                    "article_ids": ranked,
                    "chunk_ids": [item.hit.chunk_id for item in hits],
                    "security": result.security_counters.model_dump(mode="json"),
                    "stage_counts": result.result.stage_counts if hits else {},
                    "failure": result.result.code if result.status == "error" else None,
                }
                rows.append(row)
                handle.write(json.dumps(row) + "\n")
                handle.flush()
            print(f"completed {ordinal + 1}/200", flush=True)
    if _git_state() != identity:
        raise RuntimeError("source identity changed during run; reject result")
    summary = {}
    for profile in profiles:
        arm = [row for row in rows if row["profile"] == profile]
        latencies = [row["latency_ms_excluding_shared_embedding"] for row in arm]
        summary[profile] = {
            "case_count": len(arm),
            "failures": sum(row["status"] != "ok" for row in arm),
            **{
                key: sum(row["metrics"][key] for row in arm) / len(arm) for key in arm[0]["metrics"]
            },
            "retrieval_latency_p50_ms": float(np.percentile(latencies, 50)),
            "retrieval_latency_p95_ms": float(np.percentile(latencies, 95)),
        }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    manifest["status"] = "COMPLETE"
    manifest["rows_sha256"] = hashlib.sha256((args.output / "rows.jsonl").read_bytes()).hexdigest()
    (args.output / "completion.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
