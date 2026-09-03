from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import time
from pathlib import Path

from app.agent.tools_v2 import V2ToolRegistry
from app.config import get_settings
from app.domain.agent import AgentBudget
from app.domain.queries import UserContext
from app.domain.retrieved_security import GuardedSearchResult
from app.evaluation.adaptive_retrieval_recoverability import (
    RecoverabilityAssessment,
    RecoverabilityProposal,
    build_assessor_messages,
    build_assessor_request_fingerprints,
    classify_recovery,
    parse_assessor_response,
    validate_query_addendum,
)
from app.evaluation.wixqa_multidoc_attribution import (
    FrozenMultiDocCase,
    RecordingWixQANavigator,
    run_recorded_agent,
    validate_frozen_case,
)
from app.external_datasets.wixqa import (
    load_wixqa_articles,
    load_wixqa_questions,
    verify_wixqa_source,
)
from app.external_datasets.wixqa_retrieval import (
    canonical_json_bytes,
    load_wixqa_flat_index,
    reciprocal_rank_fusion,
)
from app.ollama_chat import chat_with_ollama
from app.runtime.ollama_embeddings import OllamaEmbeddingClient


SCHEMA_VERSION = "adaptive_retrieval_recoverability_v2"
ASSESSOR_TEMPERATURE = 0.0
ASSESSOR_THINK = False
ASSESSOR_MAX_OUTPUT_TOKENS = 160
ASSESSOR_TIMEOUT_SECONDS = 30.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Development-only, one-retry recoverability diagnostic for V2 Agent "
            "retrieval. This command does not change serving behavior."
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
        "--private-output-root",
        type=Path,
        default=Path(".private/adaptive_retrieval/recoverability_runs"),
    )
    parser.add_argument(
        "--public-output-dir",
        type=Path,
        default=Path(".private/adaptive_retrieval/recoverability_public"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.perf_counter()
    settings = get_settings()
    git_provenance = _git_provenance()
    baseline_revision = git_provenance["git_sha"]
    critical_file_sha256 = _critical_file_sha256()
    model_identity = _ollama_model_identity(settings.evidence_model)
    runtime_identity = _runtime_identity()
    verify_wixqa_source(args.source_root, args.dataset_manifest)
    protocol_bytes = args.frozen_protocol.read_bytes()
    protocol = json.loads(protocol_bytes)
    frozen_cases = [
        FrozenMultiDocCase.from_protocol_record(item)
        for item in protocol["cases"]
        if item["case_type"] == "multi_document"
    ]
    if len(frozen_cases) != 20:
        raise ValueError("recoverability diagnostic requires the frozen 20-case cohort")
    articles = load_wixqa_articles(args.source_root)
    questions = load_wixqa_questions("expertwritten", args.source_root)
    questions_by_id = {item.question_id: item for item in questions}
    articles_by_id = {item.source_native_id: item for item in articles}
    for frozen in frozen_cases:
        question = questions_by_id.get(frozen.question_id)
        if question is None:
            raise ValueError("frozen question ID does not resolve")
        validate_frozen_case(frozen, question, set(articles_by_id))

    index = load_wixqa_flat_index(args.index_root)
    index_manifest_path = (
        args.index_root.resolve() / "versions" / index.manifest.run_id / "manifest.json"
    )
    embedding = OllamaEmbeddingClient.from_settings(
        settings,
        probe_text="Adaptive retrieval recoverability dimension probe",
        endpoint_context="Adaptive retrieval recoverability",
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
        result = reciprocal_rank_fusion(bm25, dense, rrf_k=index.manifest.rrf_k)
        ranking_cache[query] = result
        return result

    user = UserContext(
        user_id="adaptive-retrieval-evaluator",
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
    rows: list[dict[str, object]] = []
    private_rows: list[dict[str, object]] = []
    for ordinal, frozen in enumerate(frozen_cases, start=1):
        question = questions_by_id[frozen.question_id]
        baseline_ranking = rank(question.question)
        baseline_ids = baseline_ranking[:5]
        gold_ids = frozen.gold_support_article_ids
        baseline_recall = _gold_recall(gold_ids, baseline_ids)
        row: dict[str, object] = {
            "question_id": frozen.question_id,
            "question_id_sha256": _sha256_text(frozen.question_id),
            "baseline_gold_recall": baseline_recall,
            "baseline_failed": baseline_recall < 1.0,
            "assessment_status": "skipped",
            "retry_attemptable": False,
            "retry_improved": False,
            "retry_fully_recovered": False,
            "retry_no_change": False,
            "retry_worse": False,
            "validator_rejected": False,
        }
        private_row: dict[str, object] = {
            "question_id": frozen.question_id,
            "question": question.question,
            "gold_document_ids": gold_ids,
            "baseline_document_ids": baseline_ids,
            "public_row": row,
        }
        if baseline_recall < 1.0:
            navigator = RecordingWixQANavigator(
                rank_articles=rank,
                articles=articles,
                chunks=index.chunks,
                index_run_id=index.manifest.run_id,
                manifest_sha256=_sha256_file(index_manifest_path),
            )
            _, capture = run_recorded_agent(
                question=question.question,
                user=user,
                navigator=navigator,
                budget=budget,
                top_k=5,
            )
            if capture.analysis is None:
                raise RuntimeError("baseline capture did not record query analysis")
            evidence = _admitted_evidence(capture.executions, articles_by_id)
            assessment, raw_response, latency_ms, fingerprints = _assess(
                original_question=question.question,
                retrieval_query=question.question,
                intent=capture.analysis.intent,
                required_aspects=capture.analysis.required_aspects,
                evidence=evidence,
                model=settings.evidence_model,
                model_digest=model_identity["full_model_digest"],
                seed=_assessor_seed(frozen.question_id),
            )
            row["assessment_status"] = assessment.status
            row["assessment_latency_ms"] = latency_ms
            row["assessor_input_messages_sha256"] = fingerprints[
                "input_messages_sha256"
            ]
            row["assessor_request_sha256"] = fingerprints["request_sha256"]
            row["assessor_schema_sha256"] = fingerprints["schema_sha256"]
            row["assessor_seed"] = _assessor_seed(frozen.question_id)
            row["proposal_sha256"] = assessment.proposal_sha256
            row["raw_output_sha256"] = (
                _sha256_text(raw_response) if raw_response is not None else None
            )
            private_row["admitted_evidence"] = evidence
            private_row["raw_assessor_response"] = raw_response
            private_row["assessment"] = assessment.model_dump(mode="json")
            if assessment.status == "ok" and assessment.proposal is not None:
                proposal = assessment.proposal
                row["reason_code"] = proposal.reason_code
                row["missing_aspect_count"] = len(proposal.missing_aspects)
                if proposal.reason_code == "evidence_conflict":
                    row["rewrite_status"] = "rejected"
                    row["rejection_reason"] = "evidence_conflict_not_retryable"
                    row["validator_rejected"] = True
                elif proposal.verdict == "insufficient":
                    validation = validate_query_addendum(
                        original_query=question.question,
                        addendum=proposal.query_addendum,
                        attempted_queries=[question.question],
                    )
                    row["rewrite_status"] = (
                        "accepted" if validation.accepted else "rejected"
                    )
                    row["rejection_reason"] = validation.rejection_reason
                    private_row["addendum_validation"] = validation.model_dump(
                        mode="json"
                    )
                    if not validation.accepted:
                        row["validator_rejected"] = True
                    else:
                        row["retry_attemptable"] = True
                        retry_ids = rank(validation.query)[:5]
                        retry_recall = _gold_recall(gold_ids, retry_ids)
                        union_ids = list(dict.fromkeys([*baseline_ids, *retry_ids]))
                        union_recall = _gold_recall(gold_ids, union_ids)
                        recovery = classify_recovery(
                            baseline_gold_recall=baseline_recall,
                            retry_gold_recall=retry_recall,
                            union_gold_recall=union_recall,
                        )
                        row.update(recovery)
                        row["retry_gold_recall"] = retry_recall
                        row["union_gold_recall"] = union_recall
                        row["retry_query_sha256"] = _sha256_text(validation.query)
                        private_row["retry_query"] = validation.query
                        private_row["retry_document_ids"] = retry_ids
                        private_row["union_document_ids"] = union_ids
                else:
                    row["rewrite_status"] = "not_proposed"
        rows.append(row)
        private_rows.append(private_row)
        print(f"evaluated {ordinal}/{len(frozen_cases)}", flush=True)

    summary = _summarize(rows)
    summary.update(
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": args.run_id,
            "mode": "RETROSPECTIVE_DEVELOPMENT_ONLY_CONSUMED",
            **git_provenance,
            "baseline_revision": baseline_revision,
            "normal_serving_behavior_changed": False,
            "dataset": "WixQA ExpertWritten frozen 20-case multi-document cohort",
            "dataset_manifest_sha256": _sha256_file(args.dataset_manifest),
            "question_ids_sha256": _sha256_bytes(
                canonical_json_bytes([item.question_id for item in frozen_cases])
            ),
            "frozen_protocol_sha256": _sha256_bytes(protocol_bytes),
            "critical_file_sha256": critical_file_sha256,
            "index_run_id": index.manifest.run_id,
            "index_manifest_sha256": _sha256_file(index_manifest_path),
            "embedding_model": embedding.model_identifier,
            "embedding_model_sha256": embedding.model_sha256,
            "assessor_model": model_identity,
            "ollama_runtime": runtime_identity,
            "assessor_prompt_version": "adaptive_retrieval_recoverability_v1",
            "assessor_temperature": ASSESSOR_TEMPERATURE,
            "assessor_seed_policy": "sha256(question_id) first 4 bytes modulo 2147483648",
            "assessor_thinking": ASSESSOR_THINK,
            "assessor_max_output_tokens": ASSESSOR_MAX_OUTPUT_TOKENS,
            "assessor_timeout_seconds": ASSESSOR_TIMEOUT_SECONDS,
            "assessor_generation_options": {
                "temperature": ASSESSOR_TEMPERATURE,
                "think": ASSESSOR_THINK,
                "num_predict": ASSESSOR_MAX_OUTPUT_TOKENS,
                "num_ctx": None,
                "top_k": None,
                "top_p": None,
                "repeat_penalty": None,
            },
            "budget": budget.model_dump(mode="json"),
            "ranking_query_count": len(ranking_cache),
            "go_condition": (
                "retry_fully_recovered >= 3 and "
                "retry_fully_recovered / baseline_failures >= 0.10"
            ),
            "go_condition_met": _go_condition_met(summary),
            "runtime_ms": round((time.perf_counter() - started) * 1000, 3),
            "claim_boundary": (
                "Consumed development-only recoverability diagnostic. It does not "
                "establish a generalization, answer-quality, or production claim."
            ),
            "metric_definitions": {
                "retry_improved": "The union of baseline and retry Top-5 increases gold-document recall.",
                "retry_fully_recovered": "A baseline failure has all gold documents in the union of both searches.",
                "retry_no_change": "The union does not increase gold-document recall.",
                "retry_worse": "Retry-only Top-5 has lower gold-document recall than baseline; union is still measured separately.",
            },
        }
    )
    _write_outputs(args, summary=summary, rows=rows, private_rows=private_rows)
    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


def _assess(
    **kwargs,
) -> tuple[RecoverabilityAssessment, str | None, float, dict[str, str]]:
    model = kwargs.pop("model")
    model_digest = kwargs.pop("model_digest")
    seed = kwargs.pop("seed")
    messages = build_assessor_messages(**kwargs)
    fingerprints = build_assessor_request_fingerprints(
        model_name=model,
        model_digest=model_digest,
        messages=messages,
        schema=RecoverabilityProposal.model_json_schema(),
        seed=seed,
        temperature=ASSESSOR_TEMPERATURE,
        think=ASSESSOR_THINK,
        max_output_tokens=ASSESSOR_MAX_OUTPUT_TOKENS,
        timeout_seconds=ASSESSOR_TIMEOUT_SECONDS,
    )
    started = time.perf_counter()
    try:
        raw = chat_with_ollama(
            model,
            messages,
            response_format="json",
            think=ASSESSOR_THINK,
            timeout_seconds=ASSESSOR_TIMEOUT_SECONDS,
            max_output_tokens=ASSESSOR_MAX_OUTPUT_TOKENS,
            seed=seed,
        )
    except Exception as error:
        status = "timeout" if "timeout" in str(error).casefold() else "model_error"
        return RecoverabilityAssessment(status=status), None, _elapsed_ms(started), fingerprints
    return parse_assessor_response(raw), raw, _elapsed_ms(started), fingerprints


def _admitted_evidence(executions, articles_by_id) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    seen: set[str] = set()
    for execution in executions:
        if not isinstance(execution.result, GuardedSearchResult):
            continue
        for item in execution.result.hits:
            if item.hit.chunk_id in seen:
                continue
            seen.add(item.hit.chunk_id)
            article = articles_by_id[item.hit.doc_id]
            evidence.append(
                {
                    "document_id": item.hit.doc_id,
                    "title": article.title,
                    "text": item.hit.matched_text[:600],
                }
            )
            if len(evidence) == 6:
                return evidence
    return evidence


def _summarize(rows: list[dict[str, object]]) -> dict[str, int]:
    keys = (
        "baseline_failed",
        "retry_attemptable",
        "retry_improved",
        "retry_fully_recovered",
        "retry_no_change",
        "retry_worse",
        "validator_rejected",
    )
    result = {"case_count": len(rows)}
    result["baseline_failures"] = sum(bool(row["baseline_failed"]) for row in rows)
    for key in keys[1:]:
        result[key] = sum(bool(row[key]) for row in rows)
    return result


def _go_condition_met(summary: dict[str, object]) -> bool:
    failures = int(summary["baseline_failures"])
    fully_recovered = int(summary["retry_fully_recovered"])
    return failures > 0 and fully_recovered >= 3 and fully_recovered / failures >= 0.10


def _write_outputs(args, *, summary, rows, private_rows) -> None:
    private_dir = args.private_output_root.resolve() / args.run_id
    public_dir = args.public_output_dir.resolve()
    private_dir.mkdir(parents=True, exist_ok=False)
    public_dir.mkdir(parents=True, exist_ok=True)
    public_cases = [
        {key: value for key, value in row.items() if key != "question_id"}
        for row in rows
    ]
    case_bytes = canonical_json_bytes({"rows": public_cases})
    private_bytes = canonical_json_bytes({"rows": private_rows})
    summary["case_rows_sha256"] = _sha256_bytes(case_bytes)
    summary["private_rows_sha256"] = _sha256_bytes(private_bytes)
    summary["artifact_payload_sha256"] = _sha256_bytes(
        canonical_json_bytes(summary)
    )
    summary_bytes = canonical_json_bytes(summary)
    (public_dir / "recoverability_summary_v2.json").write_bytes(summary_bytes)
    (public_dir / "recoverability_cases_v2.json").write_bytes(case_bytes)
    (private_dir / "private_details_v2.json").write_bytes(private_bytes)


def _gold_recall(gold_ids, observed_ids) -> float:
    return len(set(gold_ids).intersection(observed_ids)) / len(set(gold_ids))


def _git_provenance() -> dict[str, object]:
    return {
        "git_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "git_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        ),
        "branch": subprocess.check_output(
            ["git", "branch", "--show-current"], text=True
        ).strip(),
    }


def _ollama_model_identity(model: str) -> dict[str, str | None]:
    identity = {
        "model_name": model,
        "short_locator": _ollama_model_locator(model),
        "full_model_digest": None,
        "format": None,
        "parameter_size": None,
        "quantization_level": None,
    }
    try:
        modelfile = subprocess.check_output(
            ["ollama", "show", model, "--modelfile"], text=True
        )
        match = re.search(r"sha256-([0-9a-f]{64})", modelfile)
        if match:
            identity["full_model_digest"] = match.group(1)
        verbose = subprocess.check_output(
            ["ollama", "show", model, "--verbose"], text=True
        )
        for field, label in (
            ("format", "architecture"),
            ("parameter_size", "parameters"),
            ("quantization_level", "quantization"),
        ):
            match = re.search(rf"^\s+{label}\s+(.+?)\s*$", verbose, re.MULTILINE)
            if match:
                identity[field] = match.group(1)
    except (OSError, subprocess.CalledProcessError):
        pass
    return identity


def _ollama_model_locator(model: str) -> str | None:
    try:
        lines = subprocess.check_output(["ollama", "list"], text=True).splitlines()
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in lines[1:]:
        fields = line.split()
        if len(fields) >= 2 and fields[0] == model:
            return fields[1]
    return None


def _runtime_identity() -> dict[str, object]:
    try:
        ollama_version = subprocess.check_output(
            ["ollama", "--version"], text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        ollama_version = None
    try:
        gpu_rows = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version",
                "--format=csv,noheader",
            ],
            text=True,
        ).splitlines()
    except (OSError, subprocess.CalledProcessError):
        gpu_rows = []
    return {
        "ollama_version": ollama_version,
        "os": platform.platform(),
        "architecture": platform.machine(),
        "gpu": gpu_rows or None,
    }


def _critical_file_sha256() -> dict[str, str]:
    paths = (
        "scripts/diagnose_adaptive_retrieval_recoverability.py",
        "app/evaluation/adaptive_retrieval_recoverability.py",
        "app/ollama_chat.py",
    )
    return {path: _sha256_file(Path(path)) for path in paths}


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _assessor_seed(question_id: str) -> int:
    """Stable per-case seed; keeps a repeat independent of case order."""
    digest = hashlib.sha256(question_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % 2_147_483_648


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _elapsed_ms(started: float) -> float:
    return round(max(0.0, time.perf_counter() - started) * 1000, 3)


if __name__ == "__main__":
    raise SystemExit(main())
