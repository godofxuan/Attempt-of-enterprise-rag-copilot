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
from app.evaluation.resumable_checkpoint import (
    ResumableCaseCheckpoint,
    run_resumable_cases,
)
from app.external_datasets.finqa import (
    DEFAULT_PRIVATE_ROOT,
    DEFAULT_SOURCE_ROOT,
    FINQA_DEV_SHA256,
    FINQA_REVISION,
    build_finqa_evidence_units,
    load_finqa_split,
)
from app.external_datasets.finqa_adjudication import (
    FinQAAdjudicationCaseEvaluation,
    FinQAAdjudicationRunManifest,
    LocalFinQACandidateAdjudicator,
    evaluate_finqa_adjudication_case,
    preserve_unadjudicated_finqa_case,
    publish_finqa_adjudication_run,
    summarize_finqa_adjudication_cases,
    verify_finqa_adjudication_run,
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
    parser.add_argument(
        "--runtime-backend",
        default="ollama_auto",
        help="Auditable runtime backend label stored in the run manifest.",
    )
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=DEFAULT_ADJUDICATION_ROOT,
    )
    parser.add_argument(
        "--checkpoint-root",
        type=Path,
        help=(
            "Private append-only checkpoint root. Defaults beside out-root."
        ),
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
    source_manifest_sha256 = hashlib.sha256(
        (source_dir / "manifest.json").read_bytes()
    ).hexdigest()
    checkpoint_root = (
        args.checkpoint_root.resolve()
        if args.checkpoint_root is not None
        else args.out_root.resolve().parent / "checkpoints" / "adjudication"
    )
    checkpoint = ResumableCaseCheckpoint.open(
        root=checkpoint_root,
        run_id=args.adjudication_run_id,
        contract={
            "kind": "finqa_adjudication",
            "source_review_run_id": source_manifest.review_run_id,
            "source_review_manifest_sha256": source_manifest_sha256,
            "source_review_details_sha256": source_manifest.artifacts[
                "details.jsonl"
            ],
            "dataset_revision": source_manifest.dataset_revision,
            "split_sha256": source_manifest.split_sha256,
            "selected_case_ids_sha256": (
                source_manifest.selected_case_ids_sha256
            ),
            "selected_case_count": source_manifest.selected_case_count,
            "retrieval_mode": source_manifest.retrieval_mode,
            "source_review_code_revision": (
                source_manifest.review_code_revision
            ),
            "adjudication_code_revision": code_revision,
            "adjudicator_model": adjudicator_model,
            "adjudicator_model_sha256": adjudicator_model_sha256,
            "runtime_backend": args.runtime_backend,
            "timeout_seconds": args.timeout_seconds,
            "max_attempts": args.max_attempts,
        },
        expected_case_ids=[case.id for case in selected_cases],
    )
    rows = checkpoint.load_rows(FinQAAdjudicationCaseEvaluation)
    if rows:
        print(
            (
                f"resuming after {len(rows)}/{len(selected_cases)} "
                "completed cases"
            ),
            file=sys.stderr,
            flush=True,
        )
    final_dir = args.out_root.resolve() / args.adjudication_run_id
    if final_dir.exists() and len(rows) != len(selected_cases):
        raise ValueError(
            "final FinQA adjudication run exists but checkpoint is incomplete"
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
    def evaluate_case(index, case):
        source = source_rows[index]
        if source.review_status != "revised":
            return preserve_unadjudicated_finqa_case(source)
        print(
            (
                f"[{index + 1}/{len(selected_cases)}] "
                f"adjudicating {case.id}"
            ),
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
        return evaluate_finqa_adjudication_case(
            case,
            source=source,
            selected_units=selected_units,
            result=result,
        )

    lock_root = Path(settings.runtime_cache_dir).resolve() / "evaluation_locks"
    with evaluation_lock(settings.llm_base_url, lock_root=lock_root):
        rows = run_resumable_cases(
            checkpoint=checkpoint,
            row_type=FinQAAdjudicationCaseEvaluation,
            cases=selected_cases,
            evaluate=evaluate_case,
        )

    summary = summarize_finqa_adjudication_cases(
        rows,
        source_review=source_manifest.summary,
    )
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
        runtime_backend=args.runtime_backend,
        timeout_seconds=args.timeout_seconds,
        max_attempts=args.max_attempts,
        summary=summary,
    )
    if final_dir.exists():
        existing_manifest = verify_finqa_adjudication_run(final_dir)
        if existing_manifest.model_copy(update={"artifacts": {}}) != manifest:
            raise ValueError(
                "existing final FinQA adjudication run does not match "
                "checkpoint"
            )
        output = final_dir
    else:
        output = publish_finqa_adjudication_run(
            root=args.out_root,
            manifest=manifest,
            details=rows,
        )
    checkpoint.seal(
        final_manifest_sha256=hashlib.sha256(
            (output / "manifest.json").read_bytes()
        ).hexdigest(),
        final_details_sha256=hashlib.sha256(
            (output / "details.jsonl").read_bytes()
        ).hexdigest(),
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
