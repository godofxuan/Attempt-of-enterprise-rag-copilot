from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Sequence

from app.agent.runner_v2 import V2AgentRunner
from app.agent.tools_v2 import V2ToolRegistry
from app.config import get_settings
from app.domain.agent import AgentBudget
from app.domain.queries import UserContext
from app.evaluation.wixqa_multidoc_attribution import (
    FrozenMultiDocCase,
    validate_frozen_case,
)
from app.evaluation.wixqa_multidoc_candidate import (
    CandidateArm,
    MultiDocCandidateCase,
    SelectiveExtractiveResponseBuilder,
    decompose_query,
    evaluate_combined_gate,
    fuse_query_rankings,
    score_candidate_case,
    summarize_candidate_arm,
)
from app.external_datasets.wixqa import (
    load_wixqa_articles,
    load_wixqa_questions,
    validate_wixqa_references,
    verify_wixqa_source,
)
from app.external_datasets.wixqa_agent_eval import WixQARankedNavigator
from app.external_datasets.wixqa_retrieval import (
    canonical_json_bytes,
    load_wixqa_flat_index,
    reciprocal_rank_fusion,
)
from app.runtime.ollama_embeddings import OllamaEmbeddingClient


CANDIDATE_BASE_REVISION = "ece1de15438d9a6d403390a11cdb55fd8957debe"
PROTECTED_PRODUCTION_PATHS = (
    "app/agent/query_analysis.py",
    "app/agent/controller_v2.py",
    "app/agent/evidence_ledger.py",
    "app/agent/runner_v2.py",
    "app/agent/tools_v2.py",
    "app/security/retrieved_content.py",
    "app/security/retrieved_admission.py",
    "app/retriever.py",
)
ARMS: tuple[CandidateArm, ...] = (
    "current",
    "decompose_only",
    "select_only",
    "combined",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the frozen four-arm WixQA multi-document development candidate."
        )
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(".private/external/wixqa/source"),
    )
    parser.add_argument(
        "--index-root",
        type=Path,
        default=Path(".private/external/wixqa/indexes"),
    )
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        default=Path("data_manifests/WIXQA_MANIFEST.json"),
    )
    parser.add_argument(
        "--frozen-protocol",
        type=Path,
        default=Path(
            "docs/final_evidence_closure/evidence/"
            "answer_citation_60_protocol_v1.json"
        ),
    )
    parser.add_argument(
        "--attribution-aggregate",
        type=Path,
        default=Path("docs/multidoc_attribution/evidence/aggregate_v1.json"),
    )
    parser.add_argument(
        "--candidate-protocol",
        type=Path,
        default=Path(
            "docs/multidoc_candidate/00_LONG_TERM_PLAN_AND_PROTOCOL.md"
        ),
    )
    parser.add_argument(
        "--private-output-root",
        type=Path,
        default=Path(".private/external/wixqa/multidoc_candidate_runs"),
    )
    parser.add_argument(
        "--public-output-dir",
        type=Path,
        default=Path("docs/multidoc_candidate/evidence"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.perf_counter()
    code_revision = _git_revision()
    _require_clean_candidate_code()
    verify_wixqa_source(args.source_root, args.dataset_manifest)
    articles = load_wixqa_articles(args.source_root)
    questions = load_wixqa_questions("expertwritten", args.source_root)
    validate_wixqa_references(articles, questions)
    articles_by_id = {item.source_native_id: item for item in articles}
    questions_by_id = {item.question_id: item for item in questions}

    frozen_protocol_bytes = args.frozen_protocol.read_bytes()
    frozen_payload = json.loads(frozen_protocol_bytes)
    frozen_cases = [
        FrozenMultiDocCase.from_protocol_record(item)
        for item in frozen_payload["cases"]
        if item["case_type"] == "multi_document"
    ]
    if len(frozen_cases) != 20:
        raise ValueError("frozen protocol must contain exactly 20 multi-doc cases")
    for frozen in frozen_cases:
        question = questions_by_id.get(frozen.question_id)
        if question is None:
            raise ValueError("frozen question ID does not resolve")
        validate_frozen_case(frozen, question, set(articles_by_id))

    attribution_bytes = args.attribution_aggregate.read_bytes()
    attribution = json.loads(attribution_bytes)
    if (
        attribution.get("status") != "ATTRIBUTION_COMPLETE_NO_OPTIMIZATION"
        or attribution.get("case_count") != 20
        or attribution.get("current_replay_citation_complete_count") != 0
    ):
        raise ValueError("source attribution evidence no longer matches 0/20 baseline")

    index = load_wixqa_flat_index(args.index_root)
    dataset_manifest_sha256 = _sha256_file(args.dataset_manifest)
    if index.manifest.dataset_manifest_sha256 != dataset_manifest_sha256:
        raise ValueError("WixQA index does not match dataset manifest")
    index_manifest_path = (
        args.index_root.resolve()
        / "versions"
        / index.manifest.run_id
        / "manifest.json"
    )
    index_manifest_sha256 = _sha256_file(index_manifest_path)
    settings = get_settings()
    embedding = OllamaEmbeddingClient.from_settings(
        settings,
        probe_text="WixQA bounded multi-document candidate dimension probe",
        endpoint_context="WixQA bounded multi-document candidate evaluation",
    )
    if (
        embedding.model_identifier != index.manifest.embedding_model
        or embedding.model_sha256 != index.manifest.embedding_model_sha256
    ):
        raise ValueError("query and corpus embedding identities differ")

    user = UserContext(
        user_id="wixqa-multidoc-candidate-evaluator",
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
    arm_cases: dict[CandidateArm, list[MultiDocCandidateCase]] = {
        arm: [] for arm in ARMS
    }
    private_rows: list[dict[str, object]] = []

    for ordinal, frozen in enumerate(frozen_cases, start=1):
        question = questions_by_id[frozen.question_id]
        query_variants = decompose_query(question.question)
        query_rankings: list[list[str]] = []
        query_latencies: list[float] = []
        for query in query_variants:
            ranked, latency_ms = _rank_query(
                query=query,
                index=index,
                embedding=embedding,
            )
            query_rankings.append(ranked)
            query_latencies.append(latency_ms)
        fused_started = time.perf_counter()
        fused_ranking = fuse_query_rankings(
            query_rankings,
            rrf_k=index.manifest.rrf_k,
        )
        fusion_ms = (time.perf_counter() - fused_started) * 1000

        private_arm_rows = {}
        for arm in ARMS:
            decomposed = arm in {"decompose_only", "select_only", "combined"}
            selective = arm in {"select_only", "combined"}
            arm_ranking = (
                fused_ranking
                if arm in {"decompose_only", "combined"}
                else query_rankings[0]
            )
            retrieval_compute_ms = (
                sum(query_latencies) + fusion_ms
                if arm in {"decompose_only", "combined"}
                else sum(query_latencies)
                if arm == "select_only"
                else query_latencies[0]
            )
            builder = SelectiveExtractiveResponseBuilder(
                query_rankings=query_rankings if selective else None,
                max_selected_documents=3,
            )
            navigator = WixQARankedNavigator(
                rank_articles=lambda _query, ranking=arm_ranking: ranking,
                articles=articles,
                chunks=index.chunks,
                index_run_id=index.manifest.run_id,
                manifest_sha256=index_manifest_sha256,
            )
            runner = V2AgentRunner(
                registry=V2ToolRegistry(navigator),
                response_builder=builder,
                budget=budget,
            )
            mechanism_started = time.perf_counter()
            response = runner.run(question.question, user, top_k=5)
            mechanism_ms = (time.perf_counter() - mechanism_started) * 1000
            case = score_candidate_case(
                question_id_sha256=_sha256_text(question.question_id),
                arm=arm,
                gold_document_ids=frozen.gold_support_article_ids,
                retrieved_document_ids=arm_ranking[:5],
                admitted_document_ids=builder.admitted_document_ids,
                cited_document_ids=[source.doc_id for source in response.sources],
                response_mode=response.mode,
                trace=response.trace,
                query_variant_count=(len(query_variants) if decomposed else 1),
                embedding_calls=(len(query_variants) if decomposed else 1),
                retrieval_compute_ms=retrieval_compute_ms,
                mechanism_ms=mechanism_ms,
            )
            arm_cases[arm].append(case)
            private_arm_rows[arm] = {
                "response_answer": response.answer,
                "case": case.model_dump(mode="json"),
            }
        private_rows.append(
            {
                "question_id": question.question_id,
                "question": question.question,
                "query_variants": query_variants,
                "query_latency_ms": query_latencies,
                "arms": private_arm_rows,
            }
        )
        print(f"evaluated {ordinal}/20", flush=True)

    summaries = {
        arm: summarize_candidate_arm(arm_cases[arm], arm=arm)
        for arm in ARMS
    }
    changed_protected_paths = _changed_protected_paths()
    gate = evaluate_combined_gate(
        arm_cases["current"],
        arm_cases["combined"],
        guard_enabled=True,
        acl_enabled=True,
        production_paths_unchanged=not changed_protected_paths,
    )
    transitions = _paired_transitions(
        arm_cases["current"],
        arm_cases["combined"],
    )

    private_root = args.private_output_root.resolve() / args.run_id
    public_root = args.public_output_dir.resolve()
    private_root.mkdir(parents=True, exist_ok=False)
    public_root.mkdir(parents=True, exist_ok=True)
    private_bytes = canonical_json_bytes(
        {
            "schema_version": "wixqa_multidoc_candidate_private_v1",
            "run_id": args.run_id,
            "rows": private_rows,
        }
    )
    (private_root / "private_details.json").write_bytes(private_bytes)

    case_payload = {
        "schema_version": "wixqa_multidoc_candidate_cases_v1",
        "run_id": args.run_id,
        "case_count": len(frozen_cases),
        "arms": {
            arm: [item.model_dump(mode="json") for item in arm_cases[arm]]
            for arm in ARMS
        },
        "paired_transitions": transitions,
    }
    case_bytes = canonical_json_bytes(case_payload)
    (public_root / "case_matrix_v1.json").write_bytes(case_bytes)

    protocol = {
        "schema_version": "wixqa_multidoc_candidate_protocol_v1",
        "run_id": args.run_id,
        "code_revision": code_revision,
        "candidate_base_revision": CANDIDATE_BASE_REVISION,
        "mode": "RETROSPECTIVE_DEVELOPMENT_ONLY_CONSUMED",
        "dataset": "WixQA ExpertWritten test",
        "case_count": len(frozen_cases),
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "frozen_60_protocol_sha256": _sha256_bytes(frozen_protocol_bytes),
        "source_attribution_sha256": _sha256_bytes(attribution_bytes),
        "candidate_protocol_sha256": _sha256_file(args.candidate_protocol),
        "index_run_id": index.manifest.run_id,
        "index_manifest_sha256": index_manifest_sha256,
        "embedding_model": embedding.model_identifier,
        "embedding_model_sha256": embedding.model_sha256,
        "retriever": "BM25 + BGE-M3 dense + RRF",
        "arms": list(ARMS),
        "query_decomposition": {
            "deterministic": True,
            "maximum_variants": 3,
            "gold_or_answer_access": False,
        },
        "response_selection": {
            "maximum_documents": 3,
            "post_guard_only": True,
        },
        "guard_enabled": True,
        "acl_enabled": True,
        "protected_production_paths": list(PROTECTED_PRODUCTION_PATHS),
        "changed_protected_paths": changed_protected_paths,
        "normal_serving_behavior_changed": False,
        "generation_model_status": "NOT_USED_EXTRACTIVE_ABLATION",
        "command": (
            "python -m scripts.eval_wixqa_multidoc_candidate "
            f"--run-id {args.run_id}"
        ),
        "public_private_boundary": {
            "public": "question hashes, document IDs, counts, metrics, gates",
            "private": "question/query/answer text and per-query timings",
        },
    }
    protocol_bytes = canonical_json_bytes(protocol)
    (public_root / "protocol_v1.json").write_bytes(protocol_bytes)

    aggregate = {
        "schema_version": "wixqa_multidoc_candidate_aggregate_v1",
        "run_id": args.run_id,
        "status": "CANDIDATE_DEVELOPMENT_COMPLETE",
        "decision": gate.decision,
        "case_count": len(frozen_cases),
        "arm_summaries": {
            arm: summaries[arm].model_dump(mode="json") for arm in ARMS
        },
        "combined_vs_current_gate": gate.model_dump(mode="json"),
        "paired_transitions": transitions,
        "code_revision": code_revision,
        "runtime_ms": round((time.perf_counter() - started) * 1000, 3),
        "case_matrix_sha256": _sha256_bytes(case_bytes),
        "protocol_sha256": _sha256_bytes(protocol_bytes),
        "private_details_sha256": _sha256_bytes(private_bytes),
        "claim_boundary": {
            "development_only": True,
            "consumed_cohort": True,
            "answer_correctness": "NOT_MEASURED",
            "resume_quality_claim_allowed": False,
            "fixed_validation_authorized": gate.decision
            == "DEVELOPMENT_CANDIDATE_HOLD_FOR_FIXED_VALIDATION",
            "serving_change_authorized": False,
        },
    }
    aggregate_bytes = canonical_json_bytes(aggregate)
    (public_root / "aggregate_v1.json").write_bytes(aggregate_bytes)
    print(json.dumps(aggregate, indent=2, sort_keys=True))
    return 0


def _rank_query(*, query: str, index, embedding) -> tuple[list[str], float]:
    started = time.perf_counter()
    bm25 = index.bm25_article_ranking(query, candidate_k=200)
    vector = embedding.embed_batch([query])
    dense = index.dense_article_ranking(vector, candidate_k=200)
    ranking = reciprocal_rank_fusion(
        bm25,
        dense,
        rrf_k=index.manifest.rrf_k,
    )
    return ranking, (time.perf_counter() - started) * 1000


def _paired_transitions(
    baseline: Sequence[MultiDocCandidateCase],
    candidate: Sequence[MultiDocCandidateCase],
) -> dict[str, object]:
    baseline_by_id = {item.question_id_sha256: item for item in baseline}
    candidate_by_id = {item.question_id_sha256: item for item in candidate}
    if set(baseline_by_id) != set(candidate_by_id):
        raise ValueError("paired transition arms contain different case IDs")
    fixes = []
    regressions = []
    unchanged_failures = []
    for case_id in sorted(baseline_by_id):
        before = baseline_by_id[case_id].citation_complete
        after = candidate_by_id[case_id].citation_complete
        if before == 0 and after == 1:
            fixes.append(case_id)
        elif before == 1 and after == 0:
            regressions.append(case_id)
        elif before == 0 and after == 0:
            unchanged_failures.append(case_id)
    return {
        "fix_count": len(fixes),
        "regression_count": len(regressions),
        "unchanged_failure_count": len(unchanged_failures),
        "fixed_case_ids": fixes,
        "regressed_case_ids": regressions,
        "unchanged_failure_case_ids": unchanged_failures,
    }


def _changed_protected_paths() -> list[str]:
    output = subprocess.check_output(
        [
            "git",
            "diff",
            "--name-only",
            f"{CANDIDATE_BASE_REVISION}..HEAD",
            "--",
            *PROTECTED_PRODUCTION_PATHS,
        ],
        text=True,
    )
    return [line.strip().replace("\\", "/") for line in output.splitlines() if line.strip()]


def _require_clean_candidate_code() -> None:
    paths = (
        "app/evaluation/wixqa_multidoc_candidate.py",
        "scripts/eval_wixqa_multidoc_candidate.py",
        "docs/multidoc_candidate/00_LONG_TERM_PLAN_AND_PROTOCOL.md",
    )
    output = subprocess.check_output(
        ["git", "status", "--short", "--", *paths],
        text=True,
    )
    if output.strip():
        raise RuntimeError("candidate implementation must be committed before evaluation")


def _git_revision() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        text=True,
    ).strip()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
