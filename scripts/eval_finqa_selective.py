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
import time
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
    LocalFinQACandidateAdjudicator,
    evaluate_finqa_adjudication_case,
    preserve_unadjudicated_finqa_case,
)
from app.external_datasets.finqa_eval import (
    FinQAAnswerProtocolError,
    FinQACaseEvaluation,
    LocalFinQAProgramAnswerer,
    evaluate_finqa_case,
    evaluate_finqa_protocol_error,
    rank_finqa_evidence,
    verify_finqa_run,
)
from app.external_datasets.finqa_review import (
    LocalFinQAPlanReviewer,
    evaluate_finqa_review_case,
    preserve_unreviewable_finqa_case,
)
from app.external_datasets.finqa_selective import (
    FinQASelectiveCaseEvaluation,
    FinQASelectiveExecutionProtocol,
    FinQASelectiveRunManifest,
    case_ids_sha256,
    publish_finqa_selective_run,
    select_finqa_cases_excluding,
    summarize_finqa_selective_cases,
    unordered_case_ids_sha256,
    verify_finqa_selective_run,
)
from app.external_datasets.finqa_uncertainty import (
    assess_finqa_runtime_uncertainty,
    evaluate_finqa_uncertainty_case,
)
from app.ollama_chat import chat_with_ollama
from app.runtime.model_transport import perform_model_request
from app.runtime.ollama_embeddings import OllamaEmbeddingClient
from app.security.model_endpoint import parse_pinned_model_endpoint


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_selective_execution_protocol_v1.json"
)
DEFAULT_OUT_ROOT = DEFAULT_PRIVATE_ROOT / "selective_runs"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Execute FinQA runtime uncertainty routing before expensive "
            "review and isolate untriggered full-strategy work in a shadow arm."
        )
    )
    parser.add_argument("--selective-run-id", required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument(
        "--runtime-backend",
        required=True,
        help=(
            "Auditable backend label. A production latency claim additionally "
            "requires external proof that this was normal CUDA, not Vulkan."
        ),
    )
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument(
        "--checkpoint-root",
        type=Path,
        help="Private append-only checkpoint root.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code_revision = _clean_git_revision()
    protocol_path = args.protocol.resolve()
    protocol_bytes = protocol_path.read_bytes()
    protocol_sha256 = hashlib.sha256(protocol_bytes).hexdigest()
    protocol = FinQASelectiveExecutionProtocol.model_validate_json(
        protocol_bytes
    )
    _validate_protocol_sources(protocol)
    if protocol.dataset_revision != FINQA_REVISION:
        raise ValueError("FinQA selective dataset revision mismatch")

    cases, split_sha256 = load_finqa_split(
        args.source_root.resolve() / "dataset" / "dev.json",
        expected_sha256=FINQA_DEV_SHA256,
    )
    if split_sha256 != protocol.split_sha256:
        raise ValueError("FinQA selective split hash mismatch")
    excluded_ids = _load_protocol_exclusions(protocol)
    if (
        len(excluded_ids) != protocol.excluded_case_count
        or unordered_case_ids_sha256(excluded_ids)
        != protocol.excluded_case_ids_sha256
    ):
        raise ValueError("FinQA selective exclusion set mismatch")
    selected = select_finqa_cases_excluding(
        cases,
        excluded_case_ids=excluded_ids,
        count=protocol.sample_count,
        seed=protocol.sample_seed,
    )
    if (
        case_ids_sha256(case.id for case in selected)
        != protocol.selected_case_ids_sha256
    ):
        raise ValueError("FinQA selective frozen sample mismatch")
    if any(case.id in excluded_ids for case in selected):
        raise ValueError("FinQA selective sample overlaps prior cohorts")

    settings = get_settings()
    model_digests = _ollama_model_digests(
        settings,
        {
            protocol.answer_model.name,
            protocol.review_model.name,
            protocol.adjudicator_model.name,
        },
    )
    _validate_model_identity(
        "answer",
        protocol.answer_model.name,
        protocol.answer_model.sha256,
        model_digests,
    )
    _validate_model_identity(
        "review",
        protocol.review_model.name,
        protocol.review_model.sha256,
        model_digests,
    )
    _validate_model_identity(
        "adjudicator",
        protocol.adjudicator_model.name,
        protocol.adjudicator_model.sha256,
        model_digests,
    )
    embedding_client = OllamaEmbeddingClient.from_settings(
        settings,
        endpoint_context="FinQA selective evaluation",
    )
    if (
        embedding_client.model_identifier != protocol.embedding_model.name
        or embedding_client.model_sha256 != protocol.embedding_model.sha256
    ):
        raise ValueError("FinQA selective embedding identity mismatch")

    checkpoint_root = (
        args.checkpoint_root.resolve()
        if args.checkpoint_root is not None
        else args.out_root.resolve().parent / "checkpoints" / "selective"
    )
    checkpoint = ResumableCaseCheckpoint.open(
        root=checkpoint_root,
        run_id=args.selective_run_id,
        contract={
            "kind": "finqa_selective_execution",
            "protocol_sha256": protocol_sha256,
            "dataset_revision": protocol.dataset_revision,
            "split_sha256": protocol.split_sha256,
            "excluded_case_ids_sha256": (
                protocol.excluded_case_ids_sha256
            ),
            "selected_case_ids_sha256": (
                protocol.selected_case_ids_sha256
            ),
            "selected_case_count": protocol.sample_count,
            "pipeline_version": protocol.pipeline_version,
            "uncertainty_algorithm_version": (
                protocol.uncertainty_algorithm_version
            ),
            "review_prompt_version": protocol.review_prompt_version,
            "answer_model": protocol.answer_model.name,
            "answer_model_sha256": protocol.answer_model.sha256,
            "review_model": protocol.review_model.name,
            "review_model_sha256": protocol.review_model.sha256,
            "adjudicator_model": protocol.adjudicator_model.name,
            "adjudicator_model_sha256": (
                protocol.adjudicator_model.sha256
            ),
            "embedding_model": protocol.embedding_model.name,
            "embedding_model_sha256": protocol.embedding_model.sha256,
            "runtime_backend": args.runtime_backend,
            "code_revision": code_revision,
            "timeout_seconds": protocol.timeout_seconds,
            "max_attempts": protocol.max_attempts,
            "shadow_full_strategy": True,
        },
        expected_case_ids=[case.id for case in selected],
    )
    rows = checkpoint.load_rows(FinQASelectiveCaseEvaluation)
    if rows:
        print(
            f"resuming after {len(rows)}/{len(selected)} completed cases",
            file=sys.stderr,
            flush=True,
        )
    final_dir = args.out_root.resolve() / args.selective_run_id
    if final_dir.exists() and len(rows) != len(selected):
        raise ValueError(
            "final FinQA selective run exists but checkpoint is incomplete"
        )

    answerer = LocalFinQAProgramAnswerer(
        model=protocol.answer_model.name,
        chat_fn=_timed_chat(protocol.timeout_seconds),
        max_attempts=protocol.max_attempts,
    )
    reviewer = LocalFinQAPlanReviewer(
        model=protocol.review_model.name,
        chat_fn=_timed_chat(protocol.timeout_seconds),
        max_attempts=protocol.max_attempts,
        prompt_version=protocol.review_prompt_version,
    )
    adjudicator = LocalFinQACandidateAdjudicator(
        model=protocol.adjudicator_model.name,
        chat_fn=_timed_chat(protocol.timeout_seconds),
        max_attempts=protocol.max_attempts,
    )

    def evaluate_case(index: int, case) -> FinQASelectiveCaseEvaluation:
        print(
            f"[{index + 1}/{len(selected)}] baseline {case.id}",
            file=sys.stderr,
            flush=True,
        )
        experiment_started = time.perf_counter()
        evidence = rank_finqa_evidence(
            case,
            mode=protocol.retrieval_mode,
            top_k=protocol.top_k,
            embed_batch=embedding_client.embed_batch,
        )
        try:
            answer = answerer.answer(
                question=case.qa.question,
                evidence_units=evidence,
            )
        except FinQAAnswerProtocolError as error:
            baseline = evaluate_finqa_protocol_error(
                case,
                retrieval_mode=protocol.retrieval_mode,
                selected_units=evidence,
                error=error,
            )
        else:
            baseline = evaluate_finqa_case(
                case,
                retrieval_mode=protocol.retrieval_mode,
                selected_units=evidence,
                answer=answer,
            )
        signal = assess_finqa_runtime_uncertainty(case, baseline)
        if not signal.triggered:
            selective_finished = time.perf_counter()
            print(
                (
                    f"[{index + 1}/{len(selected)}] baseline route "
                    f"score={signal.score}; running isolated shadow arm"
                    if signal.eligible_for_plan_review
                    else (
                        f"[{index + 1}/{len(selected)}] ineligible baseline; "
                        "no review"
                    )
                ),
                file=sys.stderr,
                flush=True,
            )
        else:
            selective_finished = None
            print(
                (
                    f"[{index + 1}/{len(selected)}] review route "
                    f"score={signal.score}"
                ),
                file=sys.stderr,
                flush=True,
            )

        review = _execute_review(
            case=case,
            baseline=baseline,
            evidence=evidence,
            reviewer=reviewer,
        )
        adjudication = _execute_adjudication(
            case=case,
            review=review,
            evidence=evidence,
            adjudicator=adjudicator,
        )
        experiment_finished = time.perf_counter()
        if selective_finished is None:
            selective_finished = experiment_finished
            shadow_latency_ms = 0.0
        elif not signal.eligible_for_plan_review:
            selective_finished = experiment_finished
            shadow_latency_ms = 0.0
        else:
            shadow_latency_ms = (
                experiment_finished - selective_finished
            ) * 1000
        policy = evaluate_finqa_uncertainty_case(adjudication, signal)
        route = (
            "baseline"
            if not signal.triggered
            else (
                "adjudicated"
                if review.review_status == "revised"
                else "reviewed_kept"
            )
        )
        return FinQASelectiveCaseEvaluation(
            case_id=case.id,
            signal=signal,
            full_strategy_execution=adjudication,
            policy=policy,
            route=route,
            production_review_executed=signal.triggered,
            production_adjudication_executed=(
                signal.triggered and review.review_status == "revised"
            ),
            shadow_review_executed=(
                signal.eligible_for_plan_review and not signal.triggered
            ),
            shadow_adjudication_executed=(
                signal.eligible_for_plan_review
                and not signal.triggered
                and review.review_status == "revised"
            ),
            observed_selective_latency_ms=(
                selective_finished - experiment_started
            )
            * 1000,
            observed_shadow_latency_ms=shadow_latency_ms,
            observed_experiment_latency_ms=(
                experiment_finished - experiment_started
            )
            * 1000,
        )

    lock_root = Path(settings.runtime_cache_dir).resolve() / "evaluation_locks"
    with evaluation_lock(settings.llm_base_url, lock_root=lock_root):
        rows = run_resumable_cases(
            checkpoint=checkpoint,
            row_type=FinQASelectiveCaseEvaluation,
            cases=selected,
            evaluate=evaluate_case,
        )

    summary = summarize_finqa_selective_cases(rows)
    manifest = FinQASelectiveRunManifest(
        selective_run_id=args.selective_run_id,
        protocol_sha256=protocol_sha256,
        dataset_revision=protocol.dataset_revision,
        split="dev",
        split_sha256=protocol.split_sha256,
        excluded_case_ids_sha256=protocol.excluded_case_ids_sha256,
        excluded_case_count=protocol.excluded_case_count,
        selected_case_ids_sha256=protocol.selected_case_ids_sha256,
        selected_case_count=protocol.sample_count,
        sample_seed=protocol.sample_seed,
        retrieval_mode=protocol.retrieval_mode,
        top_k=protocol.top_k,
        answer_model=protocol.answer_model.name,
        answer_model_sha256=protocol.answer_model.sha256,
        review_model=protocol.review_model.name,
        review_model_sha256=protocol.review_model.sha256,
        adjudicator_model=protocol.adjudicator_model.name,
        adjudicator_model_sha256=protocol.adjudicator_model.sha256,
        embedding_model=protocol.embedding_model.name,
        embedding_model_sha256=protocol.embedding_model.sha256,
        runtime_backend=args.runtime_backend,
        code_revision=code_revision,
        timeout_seconds=protocol.timeout_seconds,
        max_attempts=protocol.max_attempts,
        shadow_full_strategy=True,
        summary=summary,
    )
    if final_dir.exists():
        existing = verify_finqa_selective_run(final_dir)
        if existing.model_copy(update={"artifacts": {}}) != manifest:
            raise ValueError(
                "existing final FinQA selective run does not match checkpoint"
            )
        output = final_dir
    else:
        output = publish_finqa_selective_run(
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
                "selective_run_id": args.selective_run_id,
                "output_dir": str(output),
                "summary": summary.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _execute_review(*, case, baseline, evidence, reviewer):
    if baseline.answer_status != "ok" or not baseline.calculation:
        return preserve_unreviewable_finqa_case(baseline)
    review_result = reviewer.review(
        question=case.qa.question,
        evidence_units=evidence,
        baseline=baseline,
    )
    return evaluate_finqa_review_case(
        case,
        baseline=baseline,
        selected_units=evidence,
        review=review_result,
    )


def _execute_adjudication(*, case, review, evidence, adjudicator):
    if review.review_status != "revised":
        return preserve_unadjudicated_finqa_case(review)
    result = adjudicator.adjudicate(
        case_id=case.id,
        question=case.qa.question,
        evidence_units=evidence,
        source=review,
    )
    return evaluate_finqa_adjudication_case(
        case,
        source=review,
        selected_units=evidence,
        result=result,
    )


def _timed_chat(timeout_seconds: float):
    def chat(model, messages, *, response_format=None, think=None):
        return chat_with_ollama(
            model,
            messages,
            response_format=response_format,
            think=think,
            timeout_seconds=timeout_seconds,
        )

    return chat


def _load_protocol_exclusions(
    protocol: FinQASelectiveExecutionProtocol,
) -> set[str]:
    root = DEFAULT_PRIVATE_ROOT / "eval_runs"
    excluded_ids: set[str] = set()
    for source in protocol.exclusion_sources:
        run_dir = root / source.run_id
        manifest = verify_finqa_run(run_dir)
        manifest_sha256 = hashlib.sha256(
            (run_dir / "manifest.json").read_bytes()
        ).hexdigest()
        details_bytes = (run_dir / "details.jsonl").read_bytes()
        details_sha256 = hashlib.sha256(details_bytes).hexdigest()
        if (
            manifest_sha256 != source.manifest_sha256
            or details_sha256 != source.details_sha256
            or manifest.selected_case_ids_sha256
            != source.selected_case_ids_sha256
            or manifest.selected_case_count != source.selected_case_count
        ):
            raise ValueError(
                f"FinQA selective exclusion source changed: {source.run_id}"
            )
        rows = [
            FinQACaseEvaluation.model_validate_json(line)
            for line in details_bytes.decode("utf-8").splitlines()
            if line
        ]
        source_ids = [row.case_id for row in rows]
        if (
            len(source_ids) != source.selected_case_count
            or case_ids_sha256(source_ids)
            != source.selected_case_ids_sha256
        ):
            raise ValueError(
                f"FinQA selective exclusion rows changed: {source.run_id}"
            )
        excluded_ids.update(source_ids)
    return excluded_ids


def _validate_protocol_sources(
    protocol: FinQASelectiveExecutionProtocol,
) -> None:
    root = REPOSITORY_ROOT.resolve()
    for relative_path, expected_sha256 in protocol.source_sha256.items():
        source_path = (root / relative_path).resolve()
        try:
            source_path.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                "FinQA selective source path escapes repository"
            ) from exc
        if not source_path.is_file():
            raise ValueError(
                f"FinQA selective source file is missing: {relative_path}"
            )
        actual_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"FinQA selective source hash mismatch: {relative_path}"
            )


def _clean_git_revision() -> str:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("FinQA selective execution requires a clean worktree")
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("Git returned an invalid selective revision")
    return revision


def _ollama_model_digests(settings, models: set[str]) -> dict[str, str]:
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
    available = {
        item["name"]: item["digest"].removeprefix("sha256:")
        for item in payload["models"]
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and isinstance(item.get("digest"), str)
    }
    result: dict[str, str] = {}
    for model in models:
        matches = [
            digest
            for name, digest in available.items()
            if name == model or name.removesuffix(":latest") == model
        ]
        if (
            len(matches) != 1
            or re.fullmatch(r"[0-9a-f]{64}", matches[0]) is None
        ):
            raise ValueError(
                f"Ollama model identity is unavailable or ambiguous: {model}"
            )
        result[model] = matches[0]
    return result


def _validate_model_identity(
    role: str,
    model: str,
    expected_sha256: str,
    actual: dict[str, str],
) -> None:
    if actual.get(model) != expected_sha256:
        raise ValueError(f"FinQA selective {role} model identity mismatch")


if __name__ == "__main__":
    raise SystemExit(main())
