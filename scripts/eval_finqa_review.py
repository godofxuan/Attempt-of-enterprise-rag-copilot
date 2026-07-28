try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
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
    build_finqa_evidence_units,
    load_finqa_split,
    stable_sample_finqa_cases,
)
from app.external_datasets.finqa_diagnostics import (
    load_verified_finqa_details,
)
from app.external_datasets.finqa_eval import selected_case_ids_sha256
from app.external_datasets.finqa_review import (
    FinQAReviewRunManifest,
    LocalFinQAPlanReviewer,
    evaluate_finqa_review_case,
    preserve_unreviewable_finqa_case,
    publish_finqa_review_run,
    summarize_finqa_review_cases,
)
from app.ollama_chat import chat_with_ollama
from app.runtime.model_transport import perform_model_request
from app.security.model_endpoint import parse_pinned_model_endpoint


DEFAULT_REVIEW_ROOT = DEFAULT_PRIVATE_ROOT / "review_runs"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Review immutable FinQA dev planner outputs without regenerating them."
        )
    )
    parser.add_argument("--review-run-id", required=True)
    parser.add_argument("--source-run-dir", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_REVIEW_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    review_revision = _clean_git_revision()
    if not 0 < args.timeout_seconds <= 300:
        raise ValueError("FinQA review timeout must be between 0 and 300 seconds")
    if not 1 <= args.max_attempts <= 3:
        raise ValueError("FinQA review attempts must be between 1 and 3")

    source_manifest, evaluations, details_sha256 = (
        load_verified_finqa_details(args.source_run_dir)
    )
    if source_manifest.split != "dev":
        raise ValueError("FinQA plan review refuses test source runs")
    if source_manifest.answer_strategy != "program":
        raise ValueError("FinQA plan review requires a program baseline")
    if source_manifest.dataset_revision != FINQA_REVISION:
        raise ValueError("FinQA plan review dataset revision mismatch")

    split_path = args.source_root.resolve() / "dataset" / "dev.json"
    cases, split_sha256 = load_finqa_split(
        split_path,
        expected_sha256=FINQA_DEV_SHA256,
    )
    if split_sha256 != source_manifest.split_sha256:
        raise ValueError("FinQA plan review split hash mismatch")
    selected = stable_sample_finqa_cases(
        cases,
        count=source_manifest.selected_case_count,
        seed=source_manifest.sample_seed,
    )
    if (
        selected_case_ids_sha256(selected)
        != source_manifest.selected_case_ids_sha256
    ):
        raise ValueError("FinQA plan review selected case hash mismatch")
    evaluations_by_id = {row.case_id: row for row in evaluations}
    if len(evaluations_by_id) != len(evaluations) or set(
        evaluations_by_id
    ) != {case.id for case in selected}:
        raise ValueError("FinQA plan review source rows do not match sample")

    settings = get_settings()
    review_model = args.model or settings.evidence_model
    review_model_sha256 = _ollama_model_digest(settings, review_model)

    def review_chat(
        model,
        messages,
        *,
        response_format=None,
        think=None,
    ):
        return chat_with_ollama(
            model,
            messages,
            response_format=response_format,
            think=think,
            timeout_seconds=args.timeout_seconds,
        )

    reviewer = LocalFinQAPlanReviewer(
        model=review_model,
        chat_fn=review_chat,
        max_attempts=args.max_attempts,
    )
    rows = []
    lock_root = Path(settings.runtime_cache_dir).resolve() / "evaluation_locks"
    with evaluation_lock(settings.llm_base_url, lock_root=lock_root):
        for index, case in enumerate(selected, start=1):
            print(
                f"[{index}/{len(selected)}] reviewing {case.id}",
                file=sys.stderr,
                flush=True,
            )
            baseline = evaluations_by_id[case.id]
            if baseline.answer_status != "ok" or not baseline.calculation:
                rows.append(preserve_unreviewable_finqa_case(baseline))
                continue
            units_by_id = {
                unit.unit_id: unit for unit in build_finqa_evidence_units(case)
            }
            try:
                selected_units = [
                    units_by_id[unit_id]
                    for unit_id in baseline.selected_unit_ids
                ]
            except KeyError as exc:
                raise ValueError(
                    "FinQA plan review baseline references missing evidence"
                ) from exc
            review = reviewer.review(
                question=case.qa.question,
                evidence_units=selected_units,
                baseline=baseline,
            )
            rows.append(
                evaluate_finqa_review_case(
                    case,
                    baseline=baseline,
                    selected_units=selected_units,
                    review=review,
                )
            )

    summary = summarize_finqa_review_cases(rows)
    source_manifest_sha256 = hashlib.sha256(
        (Path(args.source_run_dir).resolve() / "manifest.json").read_bytes()
    ).hexdigest()
    manifest = FinQAReviewRunManifest(
        review_run_id=args.review_run_id,
        source_run_id=source_manifest.run_id,
        source_manifest_sha256=source_manifest_sha256,
        source_details_sha256=details_sha256,
        dataset_revision=source_manifest.dataset_revision,
        split="dev",
        split_sha256=source_manifest.split_sha256,
        selected_case_ids_sha256=source_manifest.selected_case_ids_sha256,
        selected_case_count=source_manifest.selected_case_count,
        retrieval_mode=source_manifest.retrieval_mode,
        source_code_revision=source_manifest.code_revision,
        review_code_revision=review_revision,
        review_model=review_model,
        review_model_sha256=review_model_sha256,
        timeout_seconds=args.timeout_seconds,
        max_attempts=args.max_attempts,
        summary=summary,
    )
    output = publish_finqa_review_run(
        root=args.out_root,
        manifest=manifest,
        details=rows,
    )
    print(
        json.dumps(
            {
                "review_run_id": args.review_run_id,
                "source_run_id": source_manifest.run_id,
                "output_dir": str(output),
                "summary": summary.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


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
        raise ValueError("FinQA plan review requires a clean worktree")
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("Git returned an invalid FinQA review revision")
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
        raise ValueError("Ollama review model identity response is invalid")
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
        raise ValueError("FinQA review model identity is ambiguous")
    digest = candidates[0].removeprefix("sha256:")
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("FinQA review model digest is invalid")
    return digest


if __name__ == "__main__":
    raise SystemExit(main())
