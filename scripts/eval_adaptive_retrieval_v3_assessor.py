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
from app.domain.agent import AgentAction, AgentBudget, BudgetState
from app.domain.queries import SearchRequest, UserContext
from app.domain.retrieved_security import GuardedSearchResult
from app.evaluation.adaptive_retrieval_v3 import (
    ASSESSOR_PROMPT_VERSION,
    ASSESSOR_RESPONSE_FORMAT,
    EvidenceSufficiencyAssessment,
    assessor_metrics,
    build_assessor_request_fingerprints,
    build_evidence_sufficiency_messages,
    canonical_sha256,
    gold_retrieval_sufficient,
    parse_evidence_sufficiency_response,
)
from app.external_datasets.wixqa import (
    load_wixqa_articles,
    load_wixqa_questions,
    verify_wixqa_source,
)
from app.external_datasets.wixqa_agent_eval import WixQARankedNavigator
from app.external_datasets.wixqa_retrieval import (
    canonical_json_bytes,
    load_wixqa_flat_index,
    reciprocal_rank_fusion,
)
from app.ollama_chat import chat_with_ollama
from app.runtime.model_transport import ModelRequestError
from app.runtime.ollama_embeddings import OllamaEmbeddingClient

SCHEMA_VERSION = "adaptive_retrieval_v3_assessor_run_v1"
ASSESSOR_TEMPERATURE = 0.0
ASSESSOR_THINK = False
ASSESSOR_MAX_OUTPUT_TOKENS = 120
ASSESSOR_TIMEOUT_SECONDS = 30.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "G1 offline evidence-sufficiency assessment. This does not change "
            "serving behavior or execute a corrective retrieval."
        )
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--cohort", choices=("expertwritten", "simulated", "synthetic"), default="expertwritten"
    )
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--source-root", type=Path, default=Path(".private/external/wixqa/source"))
    parser.add_argument("--index-root", type=Path, default=Path(".private/external/wixqa/indexes"))
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        default=Path("data_manifests/WIXQA_MANIFEST.json"),
    )
    parser.add_argument(
        "--private-output-root",
        type=Path,
        default=Path(".private/adaptive_retrieval_v3/g1"),
    )
    parser.add_argument(
        "--public-output-dir",
        type=Path,
        default=Path("docs/adaptive_retrieval_v3/evidence"),
    )
    parser.add_argument("--max-cases", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_cases is not None and args.max_cases < 1:
        raise ValueError("max-cases must be positive")
    started = time.perf_counter()
    verify_wixqa_source(args.source_root, args.dataset_manifest)
    questions = load_wixqa_questions(args.cohort, args.source_root)
    if args.max_cases is not None:
        questions = questions[: args.max_cases]
    if not questions:
        raise ValueError("selected cohort has no questions")

    settings = get_settings()
    index = load_wixqa_flat_index(args.index_root)
    index_manifest_path = _index_manifest_path(
        args.index_root,
        index.manifest.run_id,
    )
    embedding = OllamaEmbeddingClient.from_settings(
        settings,
        probe_text="Adaptive retrieval V3 assessor dimension probe",
        endpoint_context="Adaptive retrieval V3 assessor",
    )
    if (
        embedding.model_identifier != index.manifest.embedding_model
        or embedding.model_sha256 != index.manifest.embedding_model_sha256
    ):
        raise ValueError("query and corpus embedding identities differ")
    articles = load_wixqa_articles(args.source_root)
    articles_by_id = {article.source_native_id: article for article in articles}
    ranking_cache: dict[str, list[str]] = {}

    def rank(query: str) -> list[str]:
        cached = ranking_cache.get(query)
        if cached is not None:
            return cached
        bm25 = index.bm25_article_ranking(query, candidate_k=200)
        vector = embedding.embed_batch([query])
        dense = index.dense_article_ranking(vector, candidate_k=200)
        ranking = reciprocal_rank_fusion(bm25, dense, rrf_k=index.manifest.rrf_k)
        ranking_cache[query] = ranking
        return ranking

    model_identity = _ollama_model_identity(args.model)
    runtime_identity = _runtime_identity()
    user = UserContext(
        user_id="adaptive-retrieval-v3-evaluator",
        tenant_id="wixqa-public",
        region="global",
        groups=["public"],
        roles=["evaluator"],
    )
    budget = AgentBudget(
        max_search_calls=1,
        max_find_calls=1,
        max_open_calls=1,
        max_steps=1,
        max_context_chars=12_000,
        deadline_ms=15_000,
    )
    rows: list[dict[str, object]] = []
    private_rows: list[dict[str, object]] = []
    for ordinal, question in enumerate(questions, start=1):
        retrieval_started = time.perf_counter()
        navigator = WixQARankedNavigator(
            rank_articles=rank,
            articles=articles,
            chunks=index.chunks,
            index_run_id=index.manifest.run_id,
            manifest_sha256=_sha256_file(index_manifest_path),
        )
        request = SearchRequest(
            request_id=f"g1-{_sha256_text(question.question_id)[:20]}",
            query=question.question,
            purpose="offline V3 first-pass evidence sufficiency measurement",
            user=user,
            top_k=5,
            candidate_k=200,
            mode="hybrid",
            max_chunks_per_doc=1,
            timeout_ms=15_000,
        )
        execution = V2ToolRegistry(navigator).run(
            AgentAction(sequence=1, tool="search", purpose=request.purpose, search_request=request),
            BudgetState(budget=budget),
        )
        evidence, ledger_summary, observed_document_ids = _admitted_evidence(
            execution, articles_by_id
        )
        retrieval_latency_ms = _elapsed_ms(retrieval_started)
        gold_sufficient = gold_retrieval_sufficient(question.article_ids, observed_document_ids)
        assessment, raw_output, assessment_latency_ms, fingerprints, transport = _assess(
            model=args.model,
            model_digest=model_identity["full_model_digest"],
            question=question.question,
            first_pass_query=request.query,
            evidence=evidence,
            ledger_summary=ledger_summary,
            seed=_assessor_seed(question.question_id),
        )
        prediction = (
            assessment.proposal.verdict == "insufficient"
            if assessment.status == "ok" and assessment.proposal is not None
            else None
        )
        row: dict[str, object] = {
            "case_sha256": _sha256_text(question.question_id),
            "gold_retrieval_sufficient": gold_sufficient,
            "prediction": prediction,
            "assessment_status": assessment.status,
            "reason_code": (
                assessment.proposal.reason_code if assessment.proposal is not None else None
            ),
            "missing_aspect_count": (
                len(assessment.proposal.missing_aspects)
                if assessment.proposal is not None
                else None
            ),
            "post_guard_unique_document_count": len(observed_document_ids),
            "post_guard_evidence_count": len(evidence),
            "retrieval_latency_ms": retrieval_latency_ms,
            "assessment_latency_ms": assessment_latency_ms,
            "assessor_input_messages_sha256": fingerprints["input_messages_sha256"],
            "assessor_request_sha256": fingerprints["request_sha256"],
            "assessor_schema_sha256": fingerprints["schema_sha256"],
            "assessor_seed": _assessor_seed(question.question_id),
            "model_transport_attempts": transport["attempts"],
            "model_transport_retries": transport["retries"],
            "model_transport_error_code": transport["error_code"],
        }
        rows.append(row)
        private_rows.append(
            {
                "question_id": question.question_id,
                "question": question.question,
                "gold_document_ids": question.article_ids,
                "post_guard_document_ids": observed_document_ids,
                "admitted_evidence": evidence,
                "ledger_summary": ledger_summary,
                "raw_assessor_output": raw_output,
                "assessment": assessment.model_dump(mode="json"),
                "public_row": row,
            }
        )
        print(f"evaluated {ordinal}/{len(questions)}", flush=True)

    metrics = assessor_metrics(rows)
    summary: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": args.run_id,
        "mode": "RETROSPECTIVE_DEVELOPMENT_ONLY_CONSUMED",
        "normal_serving_behavior_changed": False,
        "dataset": f"WixQA {args.cohort} first-pass post-Guard evidence assessment",
        "dataset_manifest_sha256": _sha256_file(args.dataset_manifest),
        "question_ids_sha256": canonical_sha256([item.question_id for item in questions]),
        "case_count": len(rows),
        "git": _git_provenance(),
        "critical_file_sha256": _critical_file_sha256(),
        "index_run_id": index.manifest.run_id,
        "index_manifest_sha256": _sha256_file(index_manifest_path),
        "embedding_model": embedding.model_identifier,
        "embedding_model_sha256": embedding.model_sha256,
        "assessor_model": model_identity,
        "ollama_runtime": runtime_identity,
        "assessor_prompt_version": ASSESSOR_PROMPT_VERSION,
        "assessor_generation_options": {
            "temperature": ASSESSOR_TEMPERATURE,
            "think": ASSESSOR_THINK,
            "num_predict": ASSESSOR_MAX_OUTPUT_TOKENS,
            "timeout_seconds": ASSESSOR_TIMEOUT_SECONDS,
            "seed_policy": "sha256(question_id) first 4 bytes modulo 2147483648",
        },
        "metrics": metrics,
        "retrieval_latency_ms_p95": _percentile(
            [float(row["retrieval_latency_ms"]) for row in rows], 0.95
        ),
        "assessment_latency_ms_p95": _percentile(
            [float(row["assessment_latency_ms"]) for row in rows], 0.95
        ),
        "runtime_ms": _elapsed_ms(started),
        "claim_boundary": (
            "Consumed development-only G1 assessor diagnostic. Gold labels are used "
            "only after inference for measurement; the model receives no gold labels, "
            "no rewrite field, and no tool authority. This is not answer correctness "
            "or independent validation."
        ),
    }
    _write_outputs(args, summary=summary, rows=rows, private_rows=private_rows)
    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


def _assess(
    *,
    model: str,
    model_digest: str | None,
    question: str,
    first_pass_query: str,
    evidence: list[dict[str, str]],
    ledger_summary: dict[str, object],
    seed: int,
) -> tuple[EvidenceSufficiencyAssessment, str | None, float, dict[str, str], dict[str, object]]:
    messages = build_evidence_sufficiency_messages(
        original_question=question,
        first_pass_query=first_pass_query,
        admitted_evidence=evidence,
        ledger_summary=ledger_summary,
    )
    fingerprints = build_assessor_request_fingerprints(
        model_name=model,
        model_digest=model_digest,
        messages=messages,
        seed=seed,
        temperature=ASSESSOR_TEMPERATURE,
        think=ASSESSOR_THINK,
        max_output_tokens=ASSESSOR_MAX_OUTPUT_TOKENS,
        timeout_seconds=ASSESSOR_TIMEOUT_SECONDS,
    )
    started = time.perf_counter()
    try:
        raw, attempts, retries = chat_with_ollama(
            model,
            messages,
            response_format=ASSESSOR_RESPONSE_FORMAT,
            think=ASSESSOR_THINK,
            timeout_seconds=ASSESSOR_TIMEOUT_SECONDS,
            max_output_tokens=ASSESSOR_MAX_OUTPUT_TOKENS,
            seed=seed,
            return_transport=True,
        )
    except ModelRequestError as error:
        status = (
            "timeout"
            if error.code in {"transport_timeout", "deadline_exhausted"}
            else "model_error"
        )
        return (
            EvidenceSufficiencyAssessment(status=status),
            None,
            _elapsed_ms(started),
            fingerprints,
            {
                "attempts": error.attempts,
                "retries": max(0, error.attempts - 1),
                "error_code": error.code,
            },
        )
    except Exception:
        return (
            EvidenceSufficiencyAssessment(status="model_error"),
            None,
            _elapsed_ms(started),
            fingerprints,
            {"attempts": 0, "retries": 0, "error_code": "unexpected_error"},
        )
    return (
        parse_evidence_sufficiency_response(raw),
        raw,
        _elapsed_ms(started),
        fingerprints,
        {"attempts": attempts, "retries": retries, "error_code": None},
    )


def _admitted_evidence(
    execution, articles_by_id
) -> tuple[
    list[dict[str, str]],
    dict[str, object],
    list[str],
]:
    result = execution.result
    if not isinstance(result, GuardedSearchResult):
        return (
            [],
            {
                "tool_status": execution.status,
                "post_guard_evidence_count": 0,
                "post_guard_unique_document_count": 0,
                "security_stop_reason": execution.security_stop_reason,
            },
            [],
        )
    evidence: list[dict[str, str]] = []
    document_ids: list[str] = []
    seen_documents: set[str] = set()
    for item in result.hits:
        document_id = item.hit.doc_id
        if document_id in seen_documents:
            continue
        seen_documents.add(document_id)
        document_ids.append(document_id)
        article = articles_by_id[document_id]
        evidence.append(
            {
                "document_id": document_id,
                "title": article.title,
                "text": item.hit.matched_text[:600],
            }
        )
        if len(evidence) == 5:
            break
    counters = execution.security_counters
    return (
        evidence,
        {
            "tool_status": execution.status,
            "search_stop_reason": result.stop_reason,
            "post_guard_evidence_count": counters.post_guard_evidence_count,
            "post_guard_unique_document_count": len(document_ids),
            "quarantined_count": counters.quarantined_count,
            "security_stop_reason": execution.security_stop_reason,
        },
        document_ids,
    )


def _write_outputs(args, *, summary, rows, private_rows) -> None:
    private_dir = args.private_output_root.resolve() / args.run_id
    public_dir = args.public_output_dir.resolve()
    if private_dir.exists():
        raise FileExistsError(f"private run already exists: {private_dir}")
    public_dir.mkdir(parents=True, exist_ok=True)
    private_dir.mkdir(parents=True)
    public_cases = {
        "schema_version": SCHEMA_VERSION,
        "run_id": args.run_id,
        "rows": rows,
    }
    public_cases_bytes = canonical_json_bytes(public_cases)
    private_bytes = canonical_json_bytes({"rows": private_rows})
    summary["case_rows_sha256"] = _sha256_bytes(public_cases_bytes)
    summary["private_rows_sha256"] = _sha256_bytes(private_bytes)
    summary["artifact_payload_sha256"] = canonical_sha256(
        {key: value for key, value in summary.items() if key != "artifact_payload_sha256"}
    )
    summary_path = public_dir / f"{args.run_id}-summary.json"
    cases_path = public_dir / f"{args.run_id}-cases.json"
    if summary_path.exists() or cases_path.exists():
        raise FileExistsError(f"public run already exists: {args.run_id}")
    summary_path.write_bytes(canonical_json_bytes(summary))
    cases_path.write_bytes(public_cases_bytes)
    (private_dir / "private_details.json").write_bytes(private_bytes)


def _git_provenance() -> dict[str, object]:
    return {
        "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "git_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        ),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], text=True).strip(),
    }


def _index_manifest_path(index_root: Path, run_id: str) -> Path:
    return index_root.resolve() / "versions" / run_id / "manifest.json"


def _critical_file_sha256() -> dict[str, str]:
    paths = (
        "app/evaluation/adaptive_retrieval_v3.py",
        "scripts/eval_adaptive_retrieval_v3_assessor.py",
        "app/ollama_chat.py",
    )
    return {path: _sha256_file(Path(path)) for path in paths}


def _ollama_model_identity(model: str) -> dict[str, str | None]:
    identity: dict[str, str | None] = {
        "model_name": model,
        "short_locator": None,
        "full_model_digest": None,
        "format": None,
        "parameter_size": None,
        "quantization_level": None,
    }
    try:
        lines = subprocess.check_output(["ollama", "list"], text=True).splitlines()
        for line in lines[1:]:
            fields = line.split()
            if len(fields) >= 2 and fields[0] == model:
                identity["short_locator"] = fields[1]
                break
        modelfile = subprocess.check_output(["ollama", "show", model, "--modelfile"], text=True)
        digest = re.search(r"sha256-([0-9a-f]{64})", modelfile)
        if digest:
            identity["full_model_digest"] = digest.group(1)
        verbose = subprocess.check_output(["ollama", "show", model, "--verbose"], text=True)
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


def _runtime_identity() -> dict[str, object]:
    try:
        ollama_version = subprocess.check_output(["ollama", "--version"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        ollama_version = None
    try:
        gpu = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version",
                "--format=csv,noheader",
            ],
            text=True,
        ).splitlines()
    except (OSError, subprocess.CalledProcessError):
        gpu = []
    return {
        "ollama_version": ollama_version,
        "os": platform.platform(),
        "architecture": platform.machine(),
        "gpu": gpu or None,
    }


def _assessor_seed(question_id: str) -> int:
    digest = hashlib.sha256(question_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % 2_147_483_648


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _elapsed_ms(started: float) -> float:
    return round(max(0.0, time.perf_counter() - started) * 1000, 3)


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower, upper = int(position), min(int(position) + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 3)


if __name__ == "__main__":
    raise SystemExit(main())
