from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Sequence

from app.config import get_settings
from app.domain.agent import AgentBudget
from app.domain.queries import UserContext
from app.domain.retrieved_security import GuardedSearchResult
from app.evaluation.wixqa_multidoc_attribution import (
    FirstLossStage,
    FrozenMultiDocCase,
    MultiDocAttributionCase,
    RecordingWixQANavigator,
    STAGE_SEQUENCE,
    all_gold_recalled,
    gold_coverage,
    run_recorded_agent,
    validate_frozen_case,
)
from app.external_datasets.wixqa import (
    load_wixqa_articles,
    load_wixqa_questions,
    validate_wixqa_references,
    verify_wixqa_source,
)
from app.external_datasets.wixqa_retrieval import (
    canonical_json_bytes,
    load_wixqa_flat_index,
    reciprocal_rank_fusion,
)
from app.runtime.ollama_embeddings import OllamaEmbeddingClient


SCHEMA_VERSION = "wixqa_multidoc_attribution_v1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose the first evidence-loss stage for the frozen WixQA "
            "ExpertWritten multi-document cohort."
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
        "--source-details",
        type=Path,
        default=Path(
            ".private/external/wixqa/agent_eval_runs/"
            "wixqa-agent-expertwritten-v1-07b156e/details.jsonl"
        ),
    )
    parser.add_argument(
        "--private-output-root",
        type=Path,
        default=Path(".private/external/wixqa/multidoc_attribution_runs"),
    )
    parser.add_argument(
        "--public-output-dir",
        type=Path,
        default=Path("docs/multidoc_attribution/evidence"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.perf_counter()
    code_revision = _git_revision()
    verify_wixqa_source(args.source_root, args.dataset_manifest)
    articles = load_wixqa_articles(args.source_root)
    questions = load_wixqa_questions("expertwritten", args.source_root)
    validate_wixqa_references(articles, questions)
    articles_by_id = {item.source_native_id: item for item in articles}
    questions_by_id = {item.question_id: item for item in questions}

    protocol_bytes = args.frozen_protocol.read_bytes()
    protocol_payload = json.loads(protocol_bytes)
    frozen_cases = [
        FrozenMultiDocCase.from_protocol_record(item)
        for item in protocol_payload["cases"]
        if item["case_type"] == "multi_document"
    ]
    if len(frozen_cases) != 20:
        raise ValueError("frozen protocol must contain exactly 20 multi-doc cases")
    for frozen in frozen_cases:
        question = questions_by_id.get(frozen.question_id)
        if question is None:
            raise ValueError("frozen question ID does not resolve")
        validate_frozen_case(frozen, question, set(articles_by_id))

    source_detail_bytes = args.source_details.read_bytes()
    source_details = {
        item["question_id"]: item
        for item in (
            json.loads(line)
            for line in source_detail_bytes.decode("utf-8").splitlines()
            if line.strip()
        )
    }
    selected_source_rows = [source_details[item.question_id] for item in frozen_cases]
    if len(selected_source_rows) != 20 or any(
        float(item["citation_complete"]) != 0.0
        for item in selected_source_rows
    ):
        raise ValueError("source 20-case result no longer matches frozen 0/20 fact")

    index = load_wixqa_flat_index(args.index_root)
    index_manifest_path = (
        args.index_root.resolve()
        / "versions"
        / index.manifest.run_id
        / "manifest.json"
    )
    settings = get_settings()
    embedding = OllamaEmbeddingClient.from_settings(
        settings,
        probe_text="WixQA multi-document attribution dimension probe",
        endpoint_context="WixQA multi-document attribution",
    )
    if (
        embedding.model_identifier != index.manifest.embedding_model
        or embedding.model_sha256 != index.manifest.embedding_model_sha256
    ):
        raise ValueError("query and corpus embedding identities differ")

    ranking_cache: dict[str, list[str]] = {}

    def rank(query: str) -> list[str]:
        cached = ranking_cache.get(query)
        if cached is not None:
            return cached
        bm25 = index.bm25_article_ranking(query, candidate_k=200)
        vector = embedding.embed_batch([query])
        dense = index.dense_article_ranking(vector, candidate_k=200)
        ranked = reciprocal_rank_fusion(
            bm25,
            dense,
            rrf_k=index.manifest.rrf_k,
        )
        ranking_cache[query] = ranked
        return ranked

    user = UserContext(
        user_id="wixqa-multidoc-attribution",
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
    index_manifest_sha256 = _sha256_file(index_manifest_path)
    cases: list[MultiDocAttributionCase] = []
    private_rows: list[dict[str, object]] = []
    retrieval_oracle_rows: list[dict[str, object]] = []

    for ordinal, frozen in enumerate(frozen_cases, start=1):
        question = questions_by_id[frozen.question_id]
        baseline_ranking = rank(question.question)
        navigator = RecordingWixQANavigator(
            rank_articles=rank,
            articles=articles,
            chunks=index.chunks,
            index_run_id=index.manifest.run_id,
            manifest_sha256=index_manifest_sha256,
        )
        response, capture = run_recorded_agent(
            question=question.question,
            user=user,
            navigator=navigator,
            budget=budget,
            top_k=5,
        )
        case = _build_case(
            frozen=frozen,
            baseline_ranking=baseline_ranking,
            response=response,
            capture=capture,
            navigator=navigator,
        )
        cases.append(case)
        private_rows.append(
            {
                "case_id": case.case_id,
                "question": question.question,
                "controller_search_queries": [
                    decision.action.search_request.query
                    for decision in capture.decisions
                    if decision.action.search_request is not None
                ],
                "attribution": case.model_dump(mode="json"),
            }
        )

        gold = list(frozen.gold_support_article_ids)

        def oracle_rank(query: str, *, gold_ids=gold) -> list[str]:
            return list(dict.fromkeys([*gold_ids, *rank(query)]))

        oracle_navigator = RecordingWixQANavigator(
            rank_articles=oracle_rank,
            articles=articles,
            chunks=index.chunks,
            index_run_id=index.manifest.run_id,
            manifest_sha256=index_manifest_sha256,
        )
        oracle_response, oracle_capture = run_recorded_agent(
            question=question.question,
            user=user,
            navigator=oracle_navigator,
            budget=budget,
            top_k=5,
        )
        oracle_post_guard = _post_guard_document_ids(oracle_capture)
        oracle_final = [source.doc_id for source in oracle_response.sources]
        retrieval_oracle_rows.append(
            {
                "case_id": case.case_id,
                "all_gold_post_guard": all_gold_recalled(
                    gold, oracle_post_guard
                ),
                "all_gold_final": all_gold_recalled(gold, oracle_final),
                "post_guard_gold_coverage": gold_coverage(
                    gold, oracle_post_guard
                ),
                "final_gold_coverage": gold_coverage(gold, oracle_final),
                "response_selected_document_ids": (
                    oracle_capture.response_selected_document_ids
                ),
            }
        )
        print(f"diagnosed {ordinal}/20", flush=True)

    private_root = args.private_output_root.resolve() / args.run_id
    public_root = args.public_output_dir.resolve()
    private_root.mkdir(parents=True, exist_ok=False)
    public_root.mkdir(parents=True, exist_ok=True)

    case_payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": args.run_id,
        "case_count": len(cases),
        "cases": [item.model_dump(mode="json") for item in cases],
    }
    case_bytes = canonical_json_bytes(case_payload)
    (public_root / "case_matrix_v1.json").write_bytes(case_bytes)
    (private_root / "private_details.json").write_bytes(
        canonical_json_bytes(
            {
                "schema_version": "wixqa_multidoc_attribution_private_v1",
                "run_id": args.run_id,
                "rows": private_rows,
            }
        )
    )

    aggregate = _aggregate(
        cases=cases,
        source_rows=selected_source_rows,
        oracle_rows=retrieval_oracle_rows,
    )
    protocol = {
        "schema_version": "wixqa_multidoc_attribution_protocol_v1",
        "run_id": args.run_id,
        "mode": "RETROSPECTIVE_DEVELOPMENT_ONLY_CONSUMED",
        "code_revision": code_revision,
        "dataset": "WixQA ExpertWritten test",
        "case_count": 20,
        "source_60_protocol_sha256": _sha256_bytes(protocol_bytes),
        "source_details_sha256": _sha256_bytes(source_detail_bytes),
        "dataset_manifest_sha256": _sha256_file(args.dataset_manifest),
        "index_run_id": index.manifest.run_id,
        "index_manifest_sha256": index_manifest_sha256,
        "embedding_model": embedding.model_identifier,
        "embedding_model_sha256": embedding.model_sha256,
        "stage_sequence": list(STAGE_SEQUENCE),
        "first_loss_definition": (
            "First incomplete stage in candidate-pool-to-final order. "
            "Top-20 availability is evaluated before top-5 serving selection."
        ),
        "normal_serving_behavior_changed": False,
        "generation_model_status": "NOT_USED_SOURCE_RUN_EXTRACTIVE",
        "gold_prompt_oracle_status": (
            "NOT_APPLICABLE_SOURCE_RUN_EXTRACTIVE"
        ),
        "public_private_boundary": {
            "public": "IDs, hashes, counts, stage coverage, attribution",
            "private": "question text and controller search query text",
        },
        "command": (
            "python -m scripts.diagnose_wixqa_multidoc_failure "
            f"--run-id {args.run_id}"
        ),
    }
    protocol_bytes_out = canonical_json_bytes(protocol)
    (public_root / "protocol_v1.json").write_bytes(protocol_bytes_out)
    aggregate.update(
        {
            "code_revision": code_revision,
            "run_id": args.run_id,
            "runtime_ms": round((time.perf_counter() - started) * 1000, 3),
            "case_matrix_sha256": _sha256_bytes(case_bytes),
            "protocol_sha256": _sha256_bytes(protocol_bytes_out),
            "private_details_sha256": _sha256_file(
                private_root / "private_details.json"
            ),
        }
    )
    aggregate_bytes = canonical_json_bytes(aggregate)
    (public_root / "aggregate_v1.json").write_bytes(aggregate_bytes)
    (private_root / "oracle_rows.json").write_bytes(
        canonical_json_bytes(
            {
                "schema_version": "wixqa_multidoc_oracle_private_v1",
                "rows": retrieval_oracle_rows,
            }
        )
    )
    print(json.dumps(aggregate, indent=2, sort_keys=True))
    return 0 if aggregate["status"] == "ATTRIBUTION_COMPLETE_NO_OPTIMIZATION" else 1


def _build_case(
    *,
    frozen: FrozenMultiDocCase,
    baseline_ranking: Sequence[str],
    response,
    capture,
    navigator: RecordingWixQANavigator,
) -> MultiDocAttributionCase:
    if capture.analysis is None or capture.final_state is None:
        raise RuntimeError("diagnostic capture is incomplete")
    raw_top5 = _raw_controller_top5(navigator, capture)
    post_guard = _post_guard_document_ids(capture)
    final_state = capture.final_state
    ledger = final_state.ledger
    if ledger is None:
        raise RuntimeError("diagnostic run did not build a ledger")
    ledger_docs = _unique(
        item.doc_id for item in ledger.items if item.relation == "supports"
    )
    selected = list(capture.response_selected_document_ids)
    final_docs = _unique(source.doc_id for source in response.sources)
    coverages = {
        "retrieval_top20": gold_coverage(
            frozen.gold_support_article_ids, baseline_ranking[:20]
        ),
        "retrieval_top5": gold_coverage(
            frozen.gold_support_article_ids, baseline_ranking[:5]
        ),
        "controller_search": gold_coverage(
            frozen.gold_support_article_ids, raw_top5
        ),
        "post_acl": gold_coverage(frozen.gold_support_article_ids, raw_top5),
        "post_guard": gold_coverage(
            frozen.gold_support_article_ids, post_guard
        ),
        "ledger": gold_coverage(frozen.gold_support_article_ids, ledger_docs),
        "response_selection": gold_coverage(
            frozen.gold_support_article_ids, selected
        ),
        "post_grounding": gold_coverage(
            frozen.gold_support_article_ids, final_docs
        ),
        "final": gold_coverage(frozen.gold_support_article_ids, final_docs),
    }
    search_decisions = [
        item
        for item in capture.decisions
        if item.action.search_request is not None
    ]
    risk_categories = _unique(
        category
        for execution in capture.executions
        for category in execution.security_counters.risk_categories
    )
    quarantined = sum(
        execution.security_counters.quarantined_count
        for execution in capture.executions
    )
    underspecified = (
        len(frozen.gold_support_article_ids) > 1
        and capture.analysis.required_aspects == ["answer"]
    )
    values = {
        "gold_document_ids": frozen.gold_support_article_ids,
        "retrieval_top20_document_ids": list(baseline_ranking[:20]),
        "retrieval_top5_document_ids": list(baseline_ranking[:5]),
        "controller_retrieved_document_ids": raw_top5,
        "post_acl_document_ids": raw_top5,
        "post_guard_document_ids": post_guard,
        "ledger_document_ids": ledger_docs,
        "response_selected_document_ids": selected,
        "post_grounding_document_ids": final_docs,
        "final_document_ids": final_docs,
    }
    from app.evaluation.wixqa_multidoc_attribution import classify_first_loss

    first_loss = classify_first_loss(**values)
    return MultiDocAttributionCase(
        case_id=frozen.question_id,
        question_id_sha256=_sha256_text(frozen.question_id),
        gold_document_ids=frozen.gold_support_article_ids,
        gold_document_count=len(frozen.gold_support_article_ids),
        retrieval_top5_document_ids=list(baseline_ranking[:5]),
        retrieval_top10_document_ids=list(baseline_ranking[:10]),
        retrieval_top20_document_ids=list(baseline_ranking[:20]),
        controller_retrieved_document_ids=raw_top5,
        post_acl_document_ids=raw_top5,
        pre_guard_document_ids=raw_top5,
        post_guard_document_ids=post_guard,
        intent=capture.analysis.intent,
        required_aspects=capture.analysis.required_aspects,
        controller_search_query_sha256=[
            _sha256_text(item.action.search_request.query)
            for item in search_decisions
        ],
        controller_search_call_count=final_state.budget_state.search_calls,
        controller_find_call_count=final_state.budget_state.find_calls,
        controller_open_call_count=final_state.budget_state.open_calls,
        controller_stop_reason=response.stop_reason or "unknown",
        ledger_supported_aspects=ledger.supported_aspects,
        ledger_document_ids=ledger_docs,
        ledger_coverage=ledger.coverage,
        ledger_recommended_action=ledger.recommended_action,
        prompt_stage_status="NOT_APPLICABLE_SOURCE_RUN_EXTRACTIVE",
        prompt_document_ids=[],
        generation_stage_status="NOT_APPLICABLE_SOURCE_RUN_EXTRACTIVE",
        model_proposed_citation_document_ids=[],
        response_selected_document_ids=selected,
        pre_grounding_citation_document_ids=selected,
        post_grounding_citation_document_ids=final_docs,
        final_source_document_ids=final_docs,
        guard_quarantined_count=quarantined,
        guard_risk_categories=risk_categories,
        coverage_by_stage=coverages,
        first_loss_stage=first_loss,
        query_analysis_underspecified=underspecified,
        ledger_false_completeness=(
            ledger.coverage == 1.0
            and gold_coverage(frozen.gold_support_article_ids, ledger_docs) < 1.0
        ),
        notes=[
            "Source run used deterministic ExtractiveResponseBuilder, not an LLM generator."
        ],
    )


def _aggregate(
    *,
    cases: Sequence[MultiDocAttributionCase],
    source_rows: Sequence[dict[str, object]],
    oracle_rows: Sequence[dict[str, object]],
) -> dict[str, object]:
    distribution = Counter(item.first_loss_stage.value for item in cases)
    unknown_count = distribution[FirstLossStage.UNKNOWN.value]
    all_gold = {}
    for k, field in (
        (5, "retrieval_top5_document_ids"),
        (10, "retrieval_top10_document_ids"),
        (20, "retrieval_top20_document_ids"),
    ):
        coverages = [
            gold_coverage(item.gold_document_ids, getattr(item, field))
            for item in cases
        ]
        all_gold[str(k)] = {
            "all_gold_complete_count": sum(value == 1.0 for value in coverages),
            "partial_count": sum(0.0 < value < 1.0 for value in coverages),
            "zero_count": sum(value == 0.0 for value in coverages),
            "mean_gold_document_recall": sum(coverages) / len(coverages),
        }
    gate_removal_count = sum(
        item.pre_grounding_citation_document_ids
        != item.post_grounding_citation_document_ids
        for item in cases
    )
    status = (
        "ATTRIBUTION_COMPLETE_NO_OPTIMIZATION"
        if len(cases) == 20 and unknown_count <= 2
        else "ATTRIBUTION_BLOCKED"
    )
    return {
        "schema_version": "wixqa_multidoc_attribution_aggregate_v1",
        "status": status,
        "case_count": len(cases),
        "source_observed_citation_complete_count": sum(
            float(item["citation_complete"]) == 1.0 for item in source_rows
        ),
        "current_replay_citation_complete_count": sum(
            item.coverage_by_stage["final"] == 1.0 for item in cases
        ),
        "retrieval_all_gold": all_gold,
        "first_loss_distribution": dict(sorted(distribution.items())),
        "unknown_count": unknown_count,
        "intent_distribution": dict(
            sorted(Counter(item.intent for item in cases).items())
        ),
        "required_aspects_distribution": dict(
            sorted(
                Counter("|".join(item.required_aspects) for item in cases).items()
            )
        ),
        "single_answer_aspect_count": sum(
            item.required_aspects == ["answer"] for item in cases
        ),
        "ledger_false_completeness_count": sum(
            item.ledger_false_completeness for item in cases
        ),
        "guard_filtered_case_count": sum(
            item.first_loss_stage == FirstLossStage.GUARD_FILTERED
            for item in cases
        ),
        "grounding_gate_removal_case_count": gate_removal_count,
        "gold_retrieval_oracle": {
            "diagnostic_only": True,
            "all_gold_post_guard_count": sum(
                bool(item["all_gold_post_guard"]) for item in oracle_rows
            ),
            "all_gold_final_citation_count": sum(
                bool(item["all_gold_final"]) for item in oracle_rows
            ),
        },
        "gold_prompt_oracle": {
            "status": "NOT_APPLICABLE_SOURCE_RUN_EXTRACTIVE",
            "reason": (
                "The source 60-case run used ExtractiveResponseBuilder and made "
                "zero generation-model calls."
            ),
        },
        "grounding_gate_diagnostic": {
            "diagnostic_only": True,
            "pre_to_post_document_set_change_count": gate_removal_count,
        },
        "representation_gap_status": (
            "SUPPORTED_REPRESENTATION_GAP"
            if sum(item.ledger_false_completeness for item in cases) >= 10
            else "NOT_PRIMARY_CAUSE"
        ),
        "claim_boundary": (
            "Retrospective diagnosis on a consumed cohort. No serving behavior "
            "change, no answer-quality improvement, and no resume-quality oracle claim."
        ),
    }


def _raw_controller_top5(navigator, capture) -> list[str]:
    result: list[str] = []
    search_actions = [
        decision.action
        for decision in capture.decisions
        if decision.action.search_request is not None
    ]
    for pool, action in zip(navigator.raw_search_pools, search_actions, strict=True):
        for candidate in pool.candidates[: action.search_request.top_k]:
            if candidate.hit.doc_id not in result:
                result.append(candidate.hit.doc_id)
    return result


def _post_guard_document_ids(capture) -> list[str]:
    return _unique(
        hit.hit.doc_id
        for execution in capture.executions
        if isinstance(execution.result, GuardedSearchResult)
        for hit in execution.result.hits
    )


def _unique(values) -> list[str]:
    return list(dict.fromkeys(values))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def _git_revision() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()


if __name__ == "__main__":
    raise SystemExit(main())
