try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import requests

from app.config import get_settings
from app.evaluation.ollama_evaluation_lock import evaluation_lock
from app.external_datasets.finqa import (
    DEFAULT_PRIVATE_ROOT,
    DEFAULT_SOURCE_ROOT,
    FINQA_DEV_SHA256,
    FINQA_REVISION,
    FINQA_TEST_SHA256,
    load_finqa_split,
    stable_sample_finqa_cases,
)
from app.external_datasets.finqa_eval import (
    FinQARunManifest,
    LocalFinQAAnswerer,
    evaluate_finqa_case,
    publish_finqa_run,
    rank_finqa_evidence,
    selected_case_ids_sha256,
    summarize_finqa_cases,
)
from app.ollama_chat import chat_with_ollama
from app.runtime.model_transport import perform_model_request
from app.runtime.ollama_embeddings import OllamaEmbeddingClient
from app.security.model_endpoint import parse_pinned_model_endpoint


DEFAULT_OUT_ROOT = DEFAULT_PRIVATE_ROOT / "eval_runs"
DEFAULT_FREEZE_PROTOCOL = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_holdout_protocol_v1.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate strict numerical answers and evidence citations on FinQA."
        )
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument(
        "--retrieval-mode",
        choices=["oracle", "bm25", "dense", "hybrid"],
        default="oracle",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--sample-count", type=int, default=20)
    parser.add_argument("--sample-seed", default="finqa-dev-pilot-v1")
    parser.add_argument("--model")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument(
        "--freeze-protocol",
        type=Path,
        default=DEFAULT_FREEZE_PROTOCOL,
    )
    parser.add_argument("--execute-frozen-test", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code_revision = _clean_git_revision()
    settings = get_settings()
    answer_model = args.model or settings.evidence_model
    if not 0 < args.timeout_seconds <= 300:
        raise ValueError("FinQA timeout must be between 0 and 300 seconds")
    if not 1 <= args.max_attempts <= 3:
        raise ValueError("FinQA max attempts must be between 1 and 3")

    split_path = (
        args.source_root.resolve() / "dataset" / f"{args.split}.json"
    )
    expected_sha256 = (
        FINQA_DEV_SHA256 if args.split == "dev" else FINQA_TEST_SHA256
    )
    if args.split == "test":
        if not args.execute_frozen_test:
            raise ValueError(
                "FinQA test requires explicit --execute-frozen-test confirmation"
            )
        _validate_frozen_test_configuration(args, answer_model)
    cases, split_sha256 = load_finqa_split(
        split_path,
        expected_sha256=expected_sha256,
    )
    selected = stable_sample_finqa_cases(
        cases,
        count=args.sample_count,
        seed=args.sample_seed,
    )

    answer_model_sha256 = _ollama_model_digest(settings, answer_model)
    embedding_client = None
    embedding_model = "none"
    embedding_model_sha256 = None
    if args.retrieval_mode in {"dense", "hybrid"}:
        embedding_client = OllamaEmbeddingClient.from_settings(
            settings,
            endpoint_context="FinQA evaluation",
        )
        embedding_model = embedding_client.model_identifier
        embedding_model_sha256 = embedding_client.model_sha256

    generation_calls = 0

    def tracked_chat(
        model,
        messages,
        *,
        response_format=None,
        think=None,
    ):
        nonlocal generation_calls
        generation_calls += 1
        return chat_with_ollama(
            model,
            messages,
            response_format=response_format,
            think=think,
            timeout_seconds=args.timeout_seconds,
        )

    answerer = LocalFinQAAnswerer(
        model=answer_model,
        chat_fn=tracked_chat,
        max_attempts=args.max_attempts,
    )
    rows = []
    lock_root = Path(settings.runtime_cache_dir).resolve() / "evaluation_locks"
    with evaluation_lock(settings.llm_base_url, lock_root=lock_root):
        for index, case in enumerate(selected, start=1):
            print(
                f"[{index}/{len(selected)}] evaluating {case.id}",
                file=sys.stderr,
                flush=True,
            )
            evidence = rank_finqa_evidence(
                case,
                mode=args.retrieval_mode,
                top_k=args.top_k,
                embed_batch=(
                    embedding_client.embed_batch
                    if embedding_client is not None
                    else None
                ),
            )
            answer = answerer.answer(
                question=case.qa.question,
                evidence_units=evidence,
            )
            rows.append(
                evaluate_finqa_case(
                    case,
                    retrieval_mode=args.retrieval_mode,
                    selected_units=evidence,
                    answer=answer,
                )
            )

    summary = summarize_finqa_cases(rows)
    if summary.generation_calls != generation_calls:
        raise ValueError("FinQA generation call accounting mismatch")
    manifest = FinQARunManifest(
        run_id=args.run_id,
        split=args.split,
        dataset_revision=FINQA_REVISION,
        split_sha256=split_sha256,
        selected_case_ids_sha256=selected_case_ids_sha256(selected),
        source_case_count=len(cases),
        selected_case_count=len(selected),
        sample_seed=args.sample_seed,
        retrieval_mode=args.retrieval_mode,
        top_k=args.top_k,
        answer_model=answer_model,
        answer_model_sha256=answer_model_sha256,
        embedding_model=embedding_model,
        embedding_model_sha256=embedding_model_sha256,
        code_revision=code_revision,
        timeout_seconds=args.timeout_seconds,
        max_attempts=args.max_attempts,
        summary=summary,
    )
    output = publish_finqa_run(
        root=args.out_root,
        manifest=manifest,
        details=rows,
    )
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "split": args.split,
                "output_dir": str(output),
                "summary": summary.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _validate_frozen_test_configuration(args, answer_model: str) -> None:
    payload = json.loads(
        args.freeze_protocol.resolve().read_text(encoding="utf-8")
    )
    expected = {
        "status": "FROZEN",
        "dataset_revision": FINQA_REVISION,
        "test_sha256": FINQA_TEST_SHA256,
        "sample_count": args.sample_count,
        "sample_seed": args.sample_seed,
        "retrieval_modes": ["oracle", "hybrid"],
        "top_k": args.top_k,
        "answer_model": answer_model,
        "timeout_seconds": args.timeout_seconds,
        "max_attempts": args.max_attempts,
    }
    actual = {
        key: payload.get(key)
        for key in expected
    }
    if actual != expected:
        raise ValueError("FinQA test configuration does not match frozen protocol")
    if args.retrieval_mode not in expected["retrieval_modes"]:
        raise ValueError("FinQA test retrieval mode is not frozen")


def _clean_git_revision() -> str:
    root = Path(__file__).resolve().parents[1]
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("FinQA evaluation requires a clean worktree")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Git returned an invalid FinQA code revision")
    return revision


def _ollama_model_digest(settings, model_identifier: str) -> str:
    origin = parse_pinned_model_endpoint(settings.llm_base_url).origin
    session = requests.Session()
    session.trust_env = False
    response = perform_model_request(
        lambda timeout: session.get(
            f"{origin}/api/tags",
            timeout=timeout,
            allow_redirects=False,
        ),
        operation="chat",
        timeout_seconds=settings.model_request_timeout_seconds,
        max_attempts=settings.model_max_attempts,
        backoff_seconds=settings.model_retry_backoff_ms / 1000.0,
    ).response
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(
        payload.get("models"),
        list,
    ):
        raise ValueError("Ollama model identity response is invalid")
    exact = [
        item.get("digest")
        for item in payload["models"]
        if isinstance(item, dict) and item.get("name") == model_identifier
    ]
    fallback = [
        item.get("digest")
        for item in payload["models"]
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and item["name"].removesuffix(":latest") == model_identifier
    ]
    candidates = exact or fallback
    if len(candidates) != 1 or not isinstance(candidates[0], str):
        raise ValueError("FinQA answer model identity is ambiguous")
    digest = candidates[0].removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("FinQA answer model digest is invalid")
    return digest


if __name__ == "__main__":
    raise SystemExit(main())
