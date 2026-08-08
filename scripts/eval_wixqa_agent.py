from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

from app.agent.runner_v2 import V2AgentRunner
from app.agent.tools_v2 import V2ToolRegistry
from app.config import get_settings
from app.domain.agent import AgentBudget
from app.domain.queries import UserContext
from app.external_datasets.wixqa import (
    DEFAULT_WIXQA_ROOT,
    load_wixqa_articles,
    load_wixqa_questions,
    question_ids_sha256,
    validate_wixqa_references,
    verify_wixqa_source,
)
from app.external_datasets.wixqa_agent_eval import (
    WixQARankedNavigator,
    score_wixqa_agent_case,
    summarize_wixqa_agent_cases,
)
from app.external_datasets.wixqa_retrieval import (
    load_wixqa_flat_index,
    reciprocal_rank_fusion,
)
from app.runtime.ollama_embeddings import OllamaEmbeddingClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate current bounded Agent on frozen WixQA RRF rankings."
    )
    parser.add_argument("--cohort", choices=["simulated", "expertwritten"], required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_WIXQA_ROOT)
    parser.add_argument(
        "--index-root",
        type=Path,
        default=Path(".private/external/wixqa/indexes"),
    )
    parser.add_argument(
        "--manifest", type=Path, default=Path("data_manifests/WIXQA_MANIFEST.json")
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path(
            "docs/enterprise_eval/evidence/WIXQA_AGENT_PROTOCOL_V1.json"
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(".private/external/wixqa/agent_eval_runs"),
    )
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--consume-fixed-external", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cohort == "expertwritten" and not args.consume_fixed_external:
        raise SystemExit(
            "ExpertWritten requires --consume-fixed-external after protocol freeze"
        )
    verify_wixqa_source(args.source_root, args.manifest)
    protocol_bytes = args.protocol.read_bytes()
    protocol = json.loads(protocol_bytes)
    cohort_protocol = protocol["cohorts"][args.cohort]
    articles = load_wixqa_articles(args.source_root)
    questions = load_wixqa_questions(args.cohort, args.source_root)
    validate_wixqa_references(articles, questions)
    if len(questions) != cohort_protocol["case_count"]:
        raise ValueError("WixQA Agent protocol case count mismatch")
    if question_ids_sha256(questions) != cohort_protocol["question_ids_sha256"]:
        raise ValueError("WixQA Agent protocol question ID hash mismatch")
    mode = "FIXED_MISSING_ARM"
    if args.max_cases is not None:
        if args.max_cases < 1:
            raise ValueError("max cases must be positive")
        questions = questions[: args.max_cases]
        mode = "PIPELINE_DEBUG"

    index = load_wixqa_flat_index(args.index_root)
    dataset_manifest_sha256 = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    if index.manifest.dataset_manifest_sha256 != dataset_manifest_sha256:
        raise ValueError("WixQA Agent index does not match dataset manifest")
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
        probe_text="WixQA Agent query embedding dimension probe",
        endpoint_context="WixQA Agent evaluation",
    )
    if (
        client.model_identifier != index.manifest.embedding_model
        or client.model_sha256 != index.manifest.embedding_model_sha256
    ):
        raise ValueError("WixQA Agent query and corpus embedding identities differ")

    ranking_cache: dict[str, tuple[list[str], float]] = {}

    def rank(query: str) -> list[str]:
        cached = ranking_cache.get(query)
        if cached is not None:
            return cached[0]
        started = time.perf_counter()
        bm25 = index.bm25_article_ranking(query, candidate_k=200)
        vector = client.embed_batch([query])
        dense = index.dense_article_ranking(vector, candidate_k=200)
        result = reciprocal_rank_fusion(bm25, dense, rrf_k=index.manifest.rrf_k)
        ranking_cache[query] = (result, (time.perf_counter() - started) * 1000)
        return result

    user = UserContext(
        user_id="wixqa-evaluator",
        tenant_id="wixqa-public",
        region="global",
        groups=["public"],
        roles=["evaluator"],
    )
    budget = AgentBudget(
        max_search_calls=3,
        max_find_calls=2,
        max_open_calls=4,
        max_steps=12,
        max_context_chars=12_000,
        deadline_ms=15_000,
    )
    details = []
    for ordinal, question in enumerate(questions, start=1):
        b2_ranking = rank(question.question)
        b2_latency_ms = ranking_cache[question.question][1]
        navigator = WixQARankedNavigator(
            rank_articles=rank,
            articles=articles,
            chunks=index.chunks,
            index_run_id=index.manifest.run_id,
            manifest_sha256=index_manifest_sha256,
        )
        runner = V2AgentRunner(
            registry=V2ToolRegistry(navigator),
            budget=budget,
        )
        agent_started = time.perf_counter()
        response = runner.run(question.question, user, top_k=5)
        agent_mechanism_ms = (time.perf_counter() - agent_started) * 1000
        details.append(
            score_wixqa_agent_case(
                question,
                cohort=args.cohort,
                b2_ranked_article_ids=b2_ranking,
                searched_article_ids=navigator.searched_article_ids(),
                cited_article_ids=[source.doc_id for source in response.sources],
                response_mode=response.mode,
                stop_reason=response.stop_reason,
                trace=response.trace,
                b2_latency_ms=b2_latency_ms,
                agent_latency_ms=b2_latency_ms + agent_mechanism_ms,
            )
        )
        if ordinal in {1, len(questions)} or ordinal % 25 == 0:
            print(f"evaluated {ordinal}/{len(questions)}", flush=True)

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
    summary = summarize_wixqa_agent_cases(details, cohort=args.cohort)
    payload = {
        "schema_version": "wixqa_agent_eval_run_v1",
        "run_id": args.run_id,
        "mode": mode,
        "cohort": args.cohort,
        "code_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "case_count": len(questions),
        "question_ids_sha256": question_ids_sha256(questions),
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "index_run_id": index.manifest.run_id,
        "index_manifest_sha256": index_manifest_sha256,
        "embedding_model": client.model_identifier,
        "embedding_model_sha256": client.model_sha256,
        "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
        "fixed_chunk_candidate_k": 200,
        "agent_budget": budget.model_dump(mode="json"),
        "query_embedding_calls": len(ranking_cache),
        "details_sha256": hashlib.sha256(detail_bytes).hexdigest(),
        "summary": summary.model_dump(mode="json"),
        "claim_boundary": {
            "answer_correctness": "NOT_MEASURED",
            "citation_metrics_use_gold_article_ids": True,
            "agent_search_evidence_is_union_of_top5_per_search_call": True,
        },
    }
    summary_bytes = (
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    (run_dir / "summary.json").write_bytes(summary_bytes)
    print(summary_bytes.decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
