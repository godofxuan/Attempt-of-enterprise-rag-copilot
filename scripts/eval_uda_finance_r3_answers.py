from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from app.config import get_settings
from app.domain.queries import QueryFilters, SearchRequest, UserContext
from app.evaluation.ollama_evaluation_lock import evaluation_lock
from app.evaluation.runtime import build_live_runtime
from app.external_datasets.finqa_eval import FinQAAnswerProtocolError
from app.external_datasets.uda_finance_r3 import (
    R3_PREPARED_ROOT,
    R3_PRIVATE_ROOT,
    R3_PROTOCOL_PATH,
    load_uda_finance_r3_cases,
    load_uda_finance_r3_protocol,
    verify_uda_finance_r3_preparation,
)
from app.external_datasets.uda_finance_r3_answer_eval import (
    R3_ANSWER_PROTOCOL_PATH,
    evidence_from_hits,
    evaluate_answer_result,
    load_answer_protocol,
    make_answerer,
    publish_answer_campaign,
    summarize_answer_results,
    verify_answer_campaign,
)
from app.ollama_chat import chat_with_ollama
from app.runtime.model_transport import perform_model_request
from app.security.model_endpoint import parse_pinned_model_endpoint


STRATEGIES = ("direct", "typed_candidate")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen UDA R3 answer and citation campaign."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--split", choices=("dev", "validation", "test"), required=True)
    parser.add_argument("--strategy", action="append", choices=STRATEGIES, required=True)
    parser.add_argument("--prepared-root", type=Path, default=R3_PREPARED_ROOT)
    parser.add_argument("--index-root", type=Path, default=R3_PRIVATE_ROOT / "indexes")
    parser.add_argument("--out-root", type=Path, default=R3_PRIVATE_ROOT / "answer_eval_runs")
    parser.add_argument("--dataset-protocol", type=Path, default=R3_PROTOCOL_PATH)
    parser.add_argument("--answer-protocol", type=Path, default=R3_ANSWER_PROTOCOL_PATH)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--execute-validation", action="store_true")
    parser.add_argument("--execute-frozen-test", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    strategies = list(dict.fromkeys(args.strategy))
    _validate_arguments(args, strategies)
    dataset_protocol, dataset_protocol_sha = load_uda_finance_r3_protocol(
        args.dataset_protocol
    )
    answer_protocol, answer_protocol_sha = load_answer_protocol(args.answer_protocol)
    if answer_protocol["dataset_protocol_sha256"] != dataset_protocol_sha:
        raise ValueError("R3 answer protocol is not bound to the dataset protocol")
    verify_uda_finance_r3_preparation(prepared_root=args.prepared_root)
    cases, cases_sha = load_uda_finance_r3_cases(args.prepared_root, split=args.split)
    code_revision = clean_git_revision()
    settings = get_settings().model_copy(update={"v2_indexes_dir": args.index_root.resolve()})
    runtime = build_live_runtime(settings)
    if runtime.snapshot.version.manifest_sha256 != answer_protocol["index_manifest_sha256"]:
        raise ValueError("R3 answer campaign loaded the wrong index manifest")
    answer_model = answer_protocol["answer_model"]
    answer_model_sha = ollama_model_digest(settings, answer_model)
    if answer_model_sha != answer_protocol["answer_model_sha256"]:
        raise ValueError("R3 answer model digest differs from the frozen protocol")

    marker = None
    if args.split in {"validation", "test"}:
        marker = claim_split_execution(
            args.out_root,
            split=args.split,
            run_id=args.run_id,
            code_revision=code_revision,
            answer_protocol_sha256=answer_protocol_sha,
            cases_sha256=cases_sha,
            strategies=strategies,
        )

    generation_calls = 0

    def tracked_chat(model, messages, *, response_format=None, think=None):
        nonlocal generation_calls
        generation_calls += 1
        return chat_with_ollama(
            model,
            messages,
            response_format=response_format,
            think=think,
            timeout_seconds=args.timeout_seconds,
        )

    answerers = {
        strategy: make_answerer(
            strategy,
            model=answer_model,
            chat_fn=tracked_chat,
            max_attempts=answer_protocol["max_attempts"],
        )
        for strategy in strategies
    }
    details_by_strategy = {strategy: [] for strategy in strategies}
    user = UserContext(
        user_id="uda-evaluator",
        tenant_id="uda-external",
        region="global",
        groups=["uda-evaluator"],
    )
    lock_root = Path(settings.runtime_cache_dir).resolve() / "evaluation_locks"
    with evaluation_lock(settings.llm_base_url, lock_root=lock_root):
        for index, case in enumerate(cases, start=1):
            request = SearchRequest(
                request_id=f"r3-answer-{case.case_id}",
                query=case.question,
                purpose="UDA R3 document-conditioned answer and citation evaluation",
                user=user,
                filters=QueryFilters(
                    policy_ids=[case.gold_doc_id],
                    temporal_scope="all",
                    authoritative_only=False,
                ),
                top_k=answer_protocol["retrieval"]["top_k"],
                candidate_k=answer_protocol["retrieval"]["candidate_k"],
                mode="dense",
                include_parent=answer_protocol["retrieval"]["include_parent"],
                max_chunks_per_doc=answer_protocol["retrieval"]["max_chunks_per_doc"],
                timeout_ms=120_000,
            )
            started = time.perf_counter()
            response = runtime.pipeline.search(request)
            retrieval_latency_ms = (time.perf_counter() - started) * 1000
            units, pages_by_unit, retrieved_pages = evidence_from_hits(response.hits)
            for strategy in strategies:
                calls_before = generation_calls
                answer = None
                error = None
                status = "ok"
                try:
                    answer = answerers[strategy].answer(
                        question=case.question,
                        evidence_units=units,
                    )
                except FinQAAnswerProtocolError as exc:
                    error = exc
                    status = "protocol_error"
                except ValueError:
                    status = "no_admitted_evidence"
                details_by_strategy[strategy].append(
                    evaluate_answer_result(
                        case=case,
                        strategy=strategy,
                        answer=answer,
                        status=status,
                        pages_by_unit=pages_by_unit,
                        retrieved_pages=retrieved_pages,
                        retrieval_latency_ms=retrieval_latency_ms,
                        generation_calls=generation_calls - calls_before,
                        protocol_error=error,
                    )
                )
            print(
                f"[{index}/{len(cases)}] {case.case_id} "
                + " ".join(
                    f"{strategy}={details_by_strategy[strategy][-1].status}:"
                    f"{int(details_by_strategy[strategy][-1].answer_correct)}"
                    for strategy in strategies
                ),
                file=sys.stderr,
                flush=True,
            )

    summaries = {
        strategy: summarize_answer_results(rows, strategy=strategy)
        for strategy, rows in details_by_strategy.items()
    }
    if sum(item.generation_calls for item in summaries.values()) != generation_calls:
        raise ValueError("R3 answer generation call accounting mismatch")
    dataset_manifest_path = (
        args.prepared_root.resolve() / "external_dataset_manifest.json"
    )
    run_dir = publish_answer_campaign(
        root=args.out_root,
        manifest_fields={
            "run_id": args.run_id,
            "split": args.split,
            "code_revision": code_revision,
            "dataset_protocol_sha256": dataset_protocol_sha,
            "answer_protocol_sha256": answer_protocol_sha,
            "dataset_manifest_sha256": hashlib.sha256(
                dataset_manifest_path.read_bytes()
            ).hexdigest(),
            "cases_sha256": cases_sha,
            "index_manifest_sha256": runtime.snapshot.version.manifest_sha256,
            "answer_model": answer_model,
            "answer_model_sha256": answer_model_sha,
        },
        details_by_strategy=details_by_strategy,
        summaries=summaries,
    )
    verified = verify_answer_campaign(run_dir)
    if marker is not None:
        complete_split_execution(
            marker,
            result_manifest_sha256=hashlib.sha256(
                (run_dir / "manifest.json").read_bytes()
            ).hexdigest(),
        )
    print(json.dumps(verified.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


def _validate_arguments(args, strategies: list[str]) -> None:
    if len(strategies) != len(args.strategy):
        raise ValueError("R3 answer campaign strategies must be unique")
    if not 0 < args.timeout_seconds <= 300:
        raise ValueError("R3 answer timeout must be between 0 and 300 seconds")
    if args.split == "validation" and not args.execute_validation:
        raise ValueError("R3 answer validation requires --execute-validation")
    if args.split == "test" and not args.execute_frozen_test:
        raise ValueError("R3 answer test requires --execute-frozen-test")
    if args.split in {"validation", "test"} and "direct" not in strategies:
        raise ValueError("R3 answer validation and test require the direct baseline")


def clean_git_revision() -> str:
    root = Path(__file__).resolve().parents[1]
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
        raise ValueError("R3 answer evaluation requires a clean tracked Git tree")
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Git returned an invalid R3 answer revision")
    return revision


def ollama_model_digest(settings, model_identifier: str) -> str:
    origin = parse_pinned_model_endpoint(settings.llm_base_url).origin
    session = requests.Session()
    session.trust_env = False
    response = perform_model_request(
        lambda timeout: session.get(
            f"{origin}/api/tags", timeout=timeout, allow_redirects=False
        ),
        operation="chat",
        timeout_seconds=settings.model_request_timeout_seconds,
        max_attempts=settings.model_max_attempts,
        backoff_seconds=settings.model_retry_backoff_ms / 1000.0,
    ).response
    payload = response.json()
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        raise ValueError("Ollama model identity response is invalid")
    exact = [
        item.get("digest")
        for item in models
        if isinstance(item, dict) and item.get("name") == model_identifier
    ]
    fallback = [
        item.get("digest")
        for item in models
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and item["name"].removesuffix(":latest") == model_identifier
    ]
    candidates = exact or fallback
    if len(candidates) != 1 or not isinstance(candidates[0], str):
        raise ValueError("R3 answer model identity is ambiguous")
    digest = candidates[0].removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("R3 answer model digest is invalid")
    return digest


def claim_split_execution(
    out_root: Path,
    *,
    split: str,
    run_id: str,
    code_revision: str,
    answer_protocol_sha256: str,
    cases_sha256: str,
    strategies: list[str],
) -> Path:
    if split not in {"validation", "test"}:
        raise ValueError("only R3 validation and test require one-shot markers")
    root = Path(out_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / f"{split}_execution_v1.json"
    payload = {
        "schema_version": "uda_finance_r3_answer_split_execution_v1",
        "status": "STARTED",
        "split": split,
        "run_id": run_id,
        "code_revision": code_revision,
        "answer_protocol_sha256": answer_protocol_sha256,
        "cases_sha256": cases_sha256,
        "strategies": strategies,
    }
    with marker.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    return marker


def complete_split_execution(marker: Path, *, result_manifest_sha256: str) -> None:
    marker = Path(marker).resolve()
    payload = json.loads(marker.read_text(encoding="utf-8"))
    if payload.get("status") != "STARTED":
        raise ValueError("R3 answer split execution marker is not STARTED")
    if not re.fullmatch(r"[0-9a-f]{64}", result_manifest_sha256):
        raise ValueError("R3 answer result manifest hash is invalid")
    payload["result_manifest_sha256"] = result_manifest_sha256
    payload["status"] = "COMPLETED"
    temp = marker.with_suffix(".tmp")
    with temp.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, marker)


if __name__ == "__main__":
    raise SystemExit(main())
