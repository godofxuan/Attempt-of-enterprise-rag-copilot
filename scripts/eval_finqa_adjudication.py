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
)
from app.external_datasets.finqa_adjudication import (
    FinQAAdjudicationRunManifest,
    LocalFinQACandidateAdjudicator,
    evaluate_finqa_adjudication_case,
    preserve_unadjudicated_finqa_case,
    publish_finqa_adjudication_run,
    summarize_finqa_adjudication_cases,
)
from app.external_datasets.finqa_review import (
    FinQAReviewCaseEvaluation,
    verify_finqa_review_run,
)
from app.ollama_chat import chat_with_ollama
from app.runtime.model_transport import perform_model_request
from app.security.model_endpoint import parse_pinned_model_endpoint


DEFAULT_ADJUDICATION_ROOT = DEFAULT_PRIVATE_ROOT / "adjudication_runs"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Adjudicate only revised candidates from an immutable FinQA "
            "review run."
        )
    )
    parser.add_argument("--adjudication-run-id", required=True)
    parser.add_argument("--source-review-run-dir", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=DEFAULT_ADJUDICATION_ROOT,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code_revision = _clean_git_revision()
    if not 0 < args.timeout_seconds <= 300:
        raise ValueError(
            "FinQA adjudication timeout must be between 0 and 300 seconds"
        )
    if not 1 <= args.max_attempts <= 3:
        raise ValueError(
            "FinQA adjudication attempts must be between 1 and 3"
        )

    source_dir = args.source_review_run_dir.resolve()
    source_manifest = verify_finqa_review_run(source_dir)
    if (
        source_manifest.split != "dev"
        or source_manifest.dataset_revision != FINQA_REVISION
    ):
        raise ValueError("FinQA adjudication accepts only pinned dev runs")
    source_rows = [
        FinQAReviewCaseEvaluation.model_validate_json(line)
        for line in (source_dir / "details.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]

    split_path = args.source_root.resolve() / "dataset" / "dev.json"
    cases, split_sha256 = load_finqa_split(
        split_path,
        expected_sha256=FINQA_DEV_SHA256,
    )
    if split_sha256 != source_manifest.split_sha256:
        raise ValueError("FinQA adjudication split hash mismatch")
    cases_by_id = {case.id: case for case in cases}
    if len(cases_by_id) != len(cases):
        raise ValueError("FinQA dev case IDs are not unique")
    try:
        selected_cases = [cases_by_id[row.case_id] for row in source_rows]
    except KeyError as exc:
        raise ValueError(
            "FinQA adjudication source references an unknown case"
        ) from exc

    settings = get_settings()
    adjudicator_model = args.model or settings.evidence_model
    adjudicator_model_sha256 = _ollama_model_digest(
        settings,
        adjudicator_model,
    )

    def adjudication_chat(
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

    adjudicator = LocalFinQACandidateAdjudicator(
        model=adjudicator_model,
        chat_fn=adjudication_chat,
        max_attempts=args.max_attempts,
    )
    rows = []
    lock_root = Path(settings.runtime_cache_dir).resolve() / "evaluation_locks"
    with evaluation_lock(settings.llm_base_url, lock_root=lock_root):
        for index, (case, source) in enumerate(
            zip(selected_cases, source_rows, strict=True),
            start=1,
        ):
            if source.review_status != "revised":
                rows.append(preserve_unadjudicated_finqa_case(source))
                continue
            print(
                f"[{index}/{len(selected_cases)}] adjudicating {case.id}",
                file=sys.stderr,
                flush=True,
            )
            units_by_id = {
                unit.unit_id: unit for unit in build_finqa_evidence_units(case)
            }
            try:
                selected_units = [
                    units_by_id[unit_id]
                    for unit_id in source.baseline.selected_unit_ids
                ]
            except KeyError as exc:
                raise ValueError(
                    "FinQA adjudication source evidence is unavailable"
                ) from exc
            result = adjudicator.adjudicate(
                case_id=case.id,
                question=case.qa.question,
                evidence_units=selected_units,
                source=source,
            )
            rows.append(
                evaluate_finqa_adjudication_case(
                    case,
                    source=source,
                    selected_units=selected_units,
                    result=result,
                )
            )

    summary = summarize_finqa_adjudication_cases(
        rows,
        source_review=source_manifest.summary,
    )
    source_manifest_sha256 = hashlib.sha256(
        (source_dir / "manifest.json").read_bytes()
    ).hexdigest()
    manifest = FinQAAdjudicationRunManifest(
        adjudication_run_id=args.adjudication_run_id,
        source_review_run_id=source_manifest.review_run_id,
        source_review_manifest_sha256=source_manifest_sha256,
        source_review_details_sha256=source_manifest.artifacts[
            "details.jsonl"
        ],
        dataset_revision=source_manifest.dataset_revision,
        split="dev",
        split_sha256=source_manifest.split_sha256,
        selected_case_ids_sha256=(
            source_manifest.selected_case_ids_sha256
        ),
        selected_case_count=source_manifest.selected_case_count,
        retrieval_mode=source_manifest.retrieval_mode,
        source_review_code_revision=source_manifest.review_code_revision,
        adjudication_code_revision=code_revision,
        adjudicator_model=adjudicator_model,
        adjudicator_model_sha256=adjudicator_model_sha256,
        timeout_seconds=args.timeout_seconds,
        max_attempts=args.max_attempts,
        summary=summary,
    )
    output = publish_finqa_adjudication_run(
        root=args.out_root,
        manifest=manifest,
        details=rows,
    )
    print(
        json.dumps(
            {
                "adjudication_run_id": args.adjudication_run_id,
                "source_review_run_id": source_manifest.review_run_id,
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
        raise ValueError("FinQA adjudication requires a clean worktree")
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("Git returned an invalid adjudication revision")
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
        raise ValueError("Ollama adjudicator identity response is invalid")
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
        raise ValueError("FinQA adjudicator model identity is ambiguous")
    digest = candidates[0].removeprefix("sha256:")
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("FinQA adjudicator model digest is invalid")
    return digest


if __name__ == "__main__":
    raise SystemExit(main())
