from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

from app.agent.runner_v2 import ExtractiveResponseBuilder, V2AgentRunner
from app.agent.tools_v2 import V2ToolRegistry
from app.config import get_settings
from app.domain.agent import AgentBudget
from app.domain.queries import UserContext
from app.external_datasets.wixqa import (
    DEFAULT_WIXQA_MANIFEST,
    DEFAULT_WIXQA_ROOT,
    load_wixqa_articles,
    load_wixqa_questions,
    verify_wixqa_source,
)
from app.external_datasets.wixqa_agent_eval import WixQARankedNavigator
from app.external_datasets.wixqa_multidoc_fast_track import (
    score_arm_case,
    summarize_arm,
)
from app.external_datasets.wixqa_retrieval import (
    load_wixqa_flat_index,
    reciprocal_rank_fusion,
)
from app.runtime.ollama_embeddings import OllamaEmbeddingClient
from scripts.build_wixqa_multidoc_dev_cohort import build_cohort


DEFAULT_COHORT = Path(
    "docs/rapid_upgrade/evidence/MULTIDOC_DEV_COHORT.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the retrospective WixQA multi-document A/B/C mechanism ablation."
        )
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_WIXQA_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_WIXQA_MANIFEST)
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument(
        "--index-root",
        type=Path,
        default=Path(".private/external/wixqa/indexes"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(".private/external/wixqa/multidoc_fast_track_runs"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    verify_wixqa_source(args.source_root, args.manifest)
    cohort_bytes = args.cohort.read_bytes()
    cohort = json.loads(cohort_bytes)
    expected_cohort = build_cohort(
        source_root=args.source_root,
        manifest_path=args.manifest,
    )
    if cohort != expected_cohort:
        raise ValueError("multi-document cohort does not match canonical source")
    if cohort["consumption"] != (
        "RETROSPECTIVE_DEVELOPMENT_ONLY_ALREADY_OBSERVED"
    ):
        raise ValueError("fast track only accepts the retrospective dev contract")

    articles = load_wixqa_articles(args.source_root)
    questions_by_id = {
        item.question_id: item
        for item in load_wixqa_questions("simulated", args.source_root)
    }
    questions = [
        questions_by_id[item["question_id"]] for item in cohort["records"]
    ]
    index = load_wixqa_flat_index(args.index_root)
    dataset_manifest_sha256 = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    if index.manifest.dataset_manifest_sha256 != dataset_manifest_sha256:
        raise ValueError("WixQA index does not match dataset manifest")
    index_manifest_path = (
        args.index_root.resolve()
        / "versions"
        / index.manifest.run_id
        / "manifest.json"
    )
    index_manifest_sha256 = hashlib.sha256(index_manifest_path.read_bytes()).hexdigest()
    settings = get_settings()
    client = OllamaEmbeddingClient.from_settings(
        settings,
        probe_text="WixQA multi-document fast-track dimension probe",
        endpoint_context="WixQA multi-document fast-track evaluation",
    )
    if (
        client.model_identifier != index.manifest.embedding_model
        or client.model_sha256 != index.manifest.embedding_model_sha256
    ):
        raise ValueError("query and corpus embedding identities differ")

    ranking_cache: dict[str, tuple[list[str], float]] = {}

    def rank(query: str) -> list[str]:
        cached = ranking_cache.get(query)
        if cached is not None:
            return cached[0]
        started = time.perf_counter()
        bm25 = index.bm25_article_ranking(query, candidate_k=200)
        vector = client.embed_batch([query])
        dense = index.dense_article_ranking(vector, candidate_k=200)
        ranking = reciprocal_rank_fusion(
            bm25,
            dense,
            rrf_k=index.manifest.rrf_k,
        )
        ranking_cache[query] = (
            ranking,
            (time.perf_counter() - started) * 1000,
        )
        return ranking

    user = UserContext(
        user_id="wixqa-fast-track-evaluator",
        tenant_id="wixqa-public",
        region="global",
        groups=["public"],
        roles=["evaluator"],
    )
    budget = AgentBudget(
        max_search_calls=3,
        max_find_calls=1,
        max_open_calls=2,
        max_steps=4,
        max_context_chars=12_000,
        deadline_ms=15_000,
    )
    arm_cases = {"current_agent": [], "candidate_aggregate": []}
    retrieval_rows: list[dict] = []
    for ordinal, question in enumerate(questions, start=1):
        b2_ranking = rank(question.question)[:5]
        b2_latency_ms = ranking_cache[question.question][1]
        gold = set(question.article_ids)
        retrieval_rows.append(
            {
                "question_id": question.question_id,
                "gold_source_ids": question.article_ids,
                "ranked_source_ids": b2_ranking,
                "recall": len(gold.intersection(b2_ranking)) / len(gold),
                "complete": float(gold <= set(b2_ranking)),
                "latency_ms": b2_latency_ms,
            }
        )
        for arm, max_evidence in (
            ("current_agent", 1),
            ("candidate_aggregate", 5),
        ):
            navigator = WixQARankedNavigator(
                rank_articles=rank,
                articles=articles,
                chunks=index.chunks,
                index_run_id=index.manifest.run_id,
                manifest_sha256=index_manifest_sha256,
            )
            runner = V2AgentRunner(
                registry=V2ToolRegistry(navigator),
                response_builder=ExtractiveResponseBuilder(
                    max_evidence_per_aspect=max_evidence,
                ),
                budget=budget,
            )
            started = time.perf_counter()
            response = runner.run(question.question, user, top_k=5)
            mechanism_ms = (time.perf_counter() - started) * 1000
            cited = [source.doc_id for source in response.sources]
            arm_cases[arm].append(
                score_arm_case(
                    question_id=question.question_id,
                    arm=arm,
                    gold_source_ids=question.article_ids,
                    retrieved_source_ids=navigator.searched_article_ids(),
                    accepted_source_ids=cited,
                    cited_source_ids=cited,
                    trace=response.trace,
                    latency_ms=b2_latency_ms + mechanism_ms,
                )
            )
        if ordinal in {1, len(questions)} or ordinal % 10 == 0:
            print(f"evaluated {ordinal}/{len(questions)}", flush=True)

    summaries = {
        arm: summarize_arm(cases, arm=arm).model_dump(mode="json")
        for arm, cases in arm_cases.items()
    }
    retrieval_latencies = sorted(row["latency_ms"] for row in retrieval_rows)
    baseline = {
        "arm": "b2_single_shot_retrieval",
        "case_count": len(retrieval_rows),
        "article_recall_at_5": _mean(row["recall"] for row in retrieval_rows),
        "multi_document_retrieval_completeness": _mean(
            row["complete"] for row in retrieval_rows
        ),
        "latency_ms_mean": _mean(row["latency_ms"] for row in retrieval_rows),
        "latency_ms_p50": _nearest_rank(retrieval_latencies, 0.50),
        "latency_ms_p95": _nearest_rank(retrieval_latencies, 0.95),
    }
    current = summaries["current_agent"]
    candidate = summaries["candidate_aggregate"]
    deltas = {
        "required_evidence_completeness_pp": 100
        * (
            candidate["required_evidence_completeness"]
            - current["required_evidence_completeness"]
        ),
        "citation_completeness_pp": 100
        * (
            candidate["citation_completeness"]
            - current["citation_completeness"]
        ),
        "retrieval_recall_pp": 100
        * (candidate["retrieval_recall"] - current["retrieval_recall"]),
        "citation_precision_pp": 100
        * (
            (candidate["citation_precision"] or 0)
            - (current["citation_precision"] or 0)
        ),
        "p95_latency_ratio": (
            candidate["latency_ms_p95"] / current["latency_ms_p95"]
            if current["latency_ms_p95"]
            else 0
        ),
    }
    gates = {
        "required_evidence_completeness_gain_at_least_15pp": (
            deltas["required_evidence_completeness_pp"] >= 15
        ),
        "citation_completeness_gain_at_least_15pp": (
            deltas["citation_completeness_pp"] >= 15
        ),
        "retrieval_recall_drop_no_more_than_2pp": (
            deltas["retrieval_recall_pp"] >= -2
        ),
        "p95_latency_no_more_than_1_8x": (
            deltas["p95_latency_ratio"] <= 1.8
        ),
        "tool_error_count_zero": candidate["tool_error_count"] == 0,
        "budget_exhaustion_below_2_percent": (
            candidate["budget_exhaustion_rate"] < 0.02
        ),
    }

    run_dir = args.output_root.resolve() / args.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    details = {
        "retrieval": retrieval_rows,
        "arms": {
            arm: [item.model_dump(mode="json") for item in cases]
            for arm, cases in arm_cases.items()
        },
    }
    detail_bytes = (
        json.dumps(details, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")
    (run_dir / "details.json").write_bytes(detail_bytes)
    payload = {
        "schema_version": "wixqa_multidoc_fast_track_run_v1",
        "run_id": args.run_id,
        "mode": "RETROSPECTIVE_DEVELOPMENT_ONLY_ALREADY_OBSERVED",
        "code_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "cohort_sha256": hashlib.sha256(cohort_bytes).hexdigest(),
        "index_run_id": index.manifest.run_id,
        "index_manifest_sha256": index_manifest_sha256,
        "embedding_model": client.model_identifier,
        "embedding_model_sha256": client.model_sha256,
        "same_retriever_across_arms": True,
        "same_guard_acl_across_agent_arms": True,
        "agent_budget": budget.model_dump(mode="json"),
        "retrieval_baseline": baseline,
        "arm_summaries": summaries,
        "candidate_vs_current": deltas,
        "registered_gates": gates,
        "registered_gate_status": "PASS" if all(gates.values()) else "FAIL",
        "promotion_status": "HOLD_NO_UNCONSUMED_VALIDATION",
        "precision_tradeoff_status": (
            "REVIEW_REQUIRED"
            if deltas["citation_precision_pp"] < -10
            else "ACCEPTABLE"
        ),
        "details_sha256": hashlib.sha256(detail_bytes).hexdigest(),
        "claim_boundary": {
            "answer_correctness": "NOT_MEASURED",
            "development_only": True,
            "resume_quality_claim_allowed": False,
            "generation_model": "NOT_USED_EXTRACTIVE_ABLATION",
            "generation_tokens": 0,
        },
    }
    summary_bytes = (
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    (run_dir / "summary.json").write_bytes(summary_bytes)
    print(summary_bytes.decode("utf-8"))
    return 0


def _mean(values) -> float:
    rows = list(values)
    return sum(rows) / len(rows)


def _nearest_rank(values: list[float], fraction: float) -> float:
    import math

    return values[max(0, math.ceil(fraction * len(values)) - 1)]


if __name__ == "__main__":
    raise SystemExit(main())
