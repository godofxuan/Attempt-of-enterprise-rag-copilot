try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings
from app.external_datasets.finqa import (
    DEFAULT_PRIVATE_ROOT,
    DEFAULT_SOURCE_ROOT,
    FINQA_DEV_SHA256,
    FINQA_REVISION,
    load_finqa_split,
)
from app.external_datasets.finqa_eval import (
    FinQACaseEvaluation,
    verify_finqa_run,
)
from app.external_datasets.finqa_selective import (
    FinQASelectiveExecutionProtocol,
    FinQASelectiveExclusionSource,
    FinQASelectiveModelIdentity,
    FinQASelectiveReviewRuntimeOptions,
    FinQASelectiveSuccessGate,
    case_ids_sha256,
    select_finqa_cases_excluding,
    unordered_case_ids_sha256,
)
from app.runtime.ollama_embeddings import OllamaEmbeddingClient
from scripts.eval_finqa_selective import _ollama_model_digests


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_selective_execution_protocol_v2.json"
)
DEFAULT_EXCLUSION_RUN_IDS = (
    "finqa-v2-diagnostic-dev-v1-hybrid",
    "finqa-plan-review-validation-v1-hybrid-baseline",
)
FROZEN_SOURCE_FILES = (
    "app/external_datasets/finqa.py",
    "app/external_datasets/finqa_adjudication.py",
    "app/external_datasets/finqa_eval.py",
    "app/external_datasets/finqa_review.py",
    "app/external_datasets/finqa_selective.py",
    "app/external_datasets/finqa_uncertainty.py",
    "app/evaluation/resumable_checkpoint.py",
    "app/ollama_chat.py",
    "scripts/eval_finqa_selective.py",
    "scripts/freeze_finqa_selective_protocol.py",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze a zero-overlap FinQA selective-execution protocol before "
            "reading any new cohort outcomes."
        )
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--sample-seed",
        default="finqa-selective-execution-v1-20260729",
    )
    parser.add_argument("--sample-count", type=int, default=100)
    parser.add_argument("--answer-model", default="qwen3:8b")
    parser.add_argument("--review-model", default="qwen3-coder:30b")
    parser.add_argument("--adjudicator-model", default="qwen3:8b")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument(
        "--eval-root",
        type=Path,
        default=DEFAULT_PRIVATE_ROOT / "eval_runs",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    parent_revision = _clean_git_revision()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(
            f"FinQA selective protocol already exists: {output}"
        )

    cases, split_sha256 = load_finqa_split(
        args.source_root.resolve() / "dataset" / "dev.json",
        expected_sha256=FINQA_DEV_SHA256,
    )
    exclusion_sources = []
    excluded_ids: set[str] = set()
    for run_id in DEFAULT_EXCLUSION_RUN_IDS:
        run_dir = args.eval_root.resolve() / run_id
        manifest = verify_finqa_run(run_dir)
        manifest_bytes = (run_dir / "manifest.json").read_bytes()
        details_bytes = (run_dir / "details.jsonl").read_bytes()
        rows = [
            FinQACaseEvaluation.model_validate_json(line)
            for line in details_bytes.decode("utf-8").splitlines()
            if line
        ]
        source_ids = [row.case_id for row in rows]
        if (
            manifest.split != "dev"
            or manifest.dataset_revision != FINQA_REVISION
            or manifest.split_sha256 != split_sha256
            or len(rows) != manifest.selected_case_count
            or case_ids_sha256(source_ids)
            != manifest.selected_case_ids_sha256
        ):
            raise ValueError(
                f"FinQA exclusion source is inconsistent: {run_id}"
            )
        exclusion_sources.append(
            FinQASelectiveExclusionSource(
                run_id=run_id,
                manifest_sha256=hashlib.sha256(
                    manifest_bytes
                ).hexdigest(),
                details_sha256=hashlib.sha256(details_bytes).hexdigest(),
                selected_case_ids_sha256=(
                    manifest.selected_case_ids_sha256
                ),
                selected_case_count=manifest.selected_case_count,
            )
        )
        excluded_ids.update(source_ids)
    selected = select_finqa_cases_excluding(
        cases,
        excluded_case_ids=excluded_ids,
        count=args.sample_count,
        seed=args.sample_seed,
    )
    if any(case.id in excluded_ids for case in selected):
        raise ValueError("FinQA frozen sample overlaps exclusion sources")

    settings = get_settings()
    model_digests = _ollama_model_digests(
        settings,
        {
            args.answer_model,
            args.review_model,
            args.adjudicator_model,
        },
    )
    embedding_client = OllamaEmbeddingClient.from_settings(
        settings,
        endpoint_context="FinQA selective protocol freeze",
    )
    protocol = FinQASelectiveExecutionProtocol(
        status="FROZEN_BEFORE_EXECUTION",
        frozen_at_utc=(
            datetime.now(UTC).replace(microsecond=0).isoformat()
            .replace("+00:00", "Z")
        ),
        freeze_parent_revision=parent_revision,
        dataset_revision=FINQA_REVISION,
        split="dev",
        split_sha256=split_sha256,
        sample_seed=args.sample_seed,
        sample_count=args.sample_count,
        selected_case_ids_sha256=case_ids_sha256(
            case.id for case in selected
        ),
        excluded_case_count=len(excluded_ids),
        excluded_case_ids_sha256=unordered_case_ids_sha256(excluded_ids),
        overlap_with_excluded_case_count=0,
        exclusion_sources=exclusion_sources,
        retrieval_mode="hybrid",
        top_k=args.top_k,
        answer_strategy="program",
        answer_model=FinQASelectiveModelIdentity(
            name=args.answer_model,
            sha256=model_digests[args.answer_model],
        ),
        review_model=FinQASelectiveModelIdentity(
            name=args.review_model,
            sha256=model_digests[args.review_model],
        ),
        adjudicator_model=FinQASelectiveModelIdentity(
            name=args.adjudicator_model,
            sha256=model_digests[args.adjudicator_model],
        ),
        embedding_model=FinQASelectiveModelIdentity(
            name=embedding_client.model_identifier,
            sha256=embedding_client.model_sha256,
        ),
        review_prompt_version="finqa_plan_review_v2",
        review_runtime_options=FinQASelectiveReviewRuntimeOptions(
            num_gpu=5,
            num_ctx=4096,
            num_batch=512,
        ),
        uncertainty_algorithm_version="finqa_runtime_uncertainty_v1",
        pipeline_version="finqa_selective_execution_v1",
        timeout_seconds=args.timeout_seconds,
        max_attempts=args.max_attempts,
        shadow_full_strategy=True,
        runtime_backend_requirement="normal_cuda_no_vulkan",
        success_gate=FinQASelectiveSuccessGate(
            correct_to_wrong_max=0,
            trigger_rate_max=0.75,
            generation_call_reduction_min=0.2,
            calculator_call_reduction_min=0.2,
            exact_mcnemar_p_value_max=0.05,
        ),
        source_sha256={
            relative_path: hashlib.sha256(
                (REPOSITORY_ROOT / relative_path).read_bytes()
            ).hexdigest()
            for relative_path in FROZEN_SOURCE_FILES
        },
        public_content_boundary=(
            "aggregate_metrics_hashes_and_versions_only"
        ),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            protocol.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "protocol_sha256": hashlib.sha256(
                    output.read_bytes()
                ).hexdigest(),
                "excluded_case_count": len(excluded_ids),
                "selected_case_count": len(selected),
                "selected_case_ids_sha256": (
                    protocol.selected_case_ids_sha256
                ),
                "overlap_with_excluded_case_count": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


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
        raise ValueError(
            "FinQA selective protocol freeze requires a clean worktree"
        )
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("Git returned an invalid freeze parent revision")
    return revision


if __name__ == "__main__":
    raise SystemExit(main())
