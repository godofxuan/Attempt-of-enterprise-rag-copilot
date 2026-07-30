try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
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
    FinQACase,
    FinQAEvidenceUnit,
    build_finqa_evidence_units,
    load_finqa_split,
)
from app.external_datasets.finqa_eval import (
    FinQAAnswerResult,
    evaluate_finqa_case,
)
from app.external_datasets.finqa_typed_calibration import (
    FinQATypedCalibrationProtocol,
    case_ids_sha256,
)
from app.external_datasets.finqa_typed_calibration_run import (
    FinQATypedCalibrationRunCase,
    FinQATypedCalibrationRunManifest,
    publish_calibration_run,
    summarize_calibration_run,
    verify_calibration_run,
)
from app.external_datasets.finqa_typed_contract_v2 import (
    COMPILER_VERSION,
    INTENT_VERSION,
    VALIDATOR_VERSION,
)
from app.external_datasets.finqa_typed_planner import (
    TypedPlannerProtocolError,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    PLANNER_VERSION,
    LocalFinQATypedProgramPlannerV2,
)
from app.external_datasets.finqa_typed_program import (
    TypedProgramValidationError,
    extract_finqa_numeric_candidates,
)
from app.external_datasets.finqa_typed_retrospective import (
    FinQATypedRetrospectiveCase,
    FrozenModelIdentity,
    arm_evaluation_from_case,
    canonical_json_bytes,
    refused_arm_evaluation,
    verify_typed_retrospective_run,
)
from app.ollama_chat import chat_with_ollama
from app.runtime.model_transport import perform_model_request
from app.security.model_endpoint import parse_pinned_model_endpoint
from app.security.retrieved_content import RetrievedContentGuard


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_typed_contract_calibration_protocol_v1.json"
)
DEFAULT_SPLIT = (
    DEFAULT_PRIVATE_ROOT
    / "typed_contract_calibration"
    / "gate-e2-v1"
    / "split.json"
)
DEFAULT_SOURCE_RUN = (
    DEFAULT_PRIVATE_ROOT
    / "typed_retrospective_runs"
    / "finqa-typed-retrospective-dev-v1"
)
DEFAULT_OUT_ROOT = DEFAULT_PRIVATE_ROOT / "typed_contract_calibration_runs"
DEFAULT_CHECKPOINT_ROOT = (
    DEFAULT_PRIVATE_ROOT / "checkpoints" / "typed_contract_calibration"
)
IMPLEMENTATION_FILES = (
    "app/external_datasets/finqa_typed_contract_v2.py",
    "app/external_datasets/finqa_typed_planner_v2.py",
    "app/external_datasets/finqa_typed_calibration_run.py",
    "scripts/eval_finqa_typed_calibration_v2.py",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Gate E2 typed-contract calibration or validation."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--cohort",
        choices=("calibration", "internal_validation"),
        default="calibration",
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--private-split", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--source-run", type=Path, default=DEFAULT_SOURCE_RUN)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_SOURCE_ROOT / "dataset" / "dev.json",
    )
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument(
        "--checkpoint-root",
        type=Path,
        default=DEFAULT_CHECKPOINT_ROOT,
    )
    parser.add_argument(
        "--allow-internal-validation",
        action="store_true",
        help="Required to consume the frozen internal-validation cohort.",
    )
    parser.add_argument(
        "--fail-closed-suite-passed",
        action="store_true",
        help="Assert the frozen fail-closed suite passed before validation.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    revision = result.stdout.strip()
    if len(revision) != 40:
        raise ValueError("Git HEAD is not a full revision")
    return revision


def _implementation_hashes() -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in IMPLEMENTATION_FILES:
        path = REPOSITORY_ROOT / relative
        if not path.is_file():
            raise ValueError(f"implementation file is missing: {relative}")
        result[relative] = _sha256(path)
    return result


def _load_source_rows(
    path: Path,
) -> list[FinQATypedRetrospectiveCase]:
    return [
        FinQATypedRetrospectiveCase.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _load_private_split(
    path: Path,
    *,
    protocol: FinQATypedCalibrationProtocol,
    cohort: str,
) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version")
        != "finqa_typed_contract_private_split_v1"
        or payload.get("protocol_id") != protocol.protocol_id
        or payload.get("source_gate_e_details_sha256")
        != protocol.source_gate_e_details_sha256
    ):
        raise ValueError("private calibration split does not match protocol")
    key = (
        "calibration_case_ids"
        if cohort == "calibration"
        else "internal_validation_case_ids"
    )
    case_ids = payload.get(key)
    if (
        not isinstance(case_ids, list)
        or any(not isinstance(case_id, str) or not case_id for case_id in case_ids)
        or len(case_ids) != len(set(case_ids))
    ):
        raise ValueError("private calibration split case IDs are invalid")
    expected_count = (
        protocol.calibration_case_count
        if cohort == "calibration"
        else protocol.internal_validation_case_count
    )
    expected_sha = (
        protocol.calibration_case_ids_sha256
        if cohort == "calibration"
        else protocol.internal_validation_case_ids_sha256
    )
    if len(case_ids) != expected_count or case_ids_sha256(case_ids) != expected_sha:
        raise ValueError("private calibration cohort hash mismatch")
    return case_ids


def _source_evidence(
    case: FinQACase,
    selected_unit_ids: list[str],
) -> tuple[FinQAEvidenceUnit, ...]:
    by_id = {unit.unit_id: unit for unit in build_finqa_evidence_units(case)}
    if any(unit_id not in by_id for unit_id in selected_unit_ids):
        raise ValueError("source evaluation references unknown evidence")
    return tuple(by_id[unit_id] for unit_id in selected_unit_ids)


def _prepare_typed_context(
    case: FinQACase,
    evidence: tuple[FinQAEvidenceUnit, ...],
) -> dict:
    guard = RetrievedContentGuard()
    admitted: list[FinQAEvidenceUnit] = []
    rule_ids: set[str] = set()
    for unit in evidence:
        decision = guard.scan(unit.text)
        rule_ids.update(decision.rule_ids)
        if decision.disposition == "ADMIT":
            admitted.append(unit)
    admitted_ids = {unit.unit_id for unit in admitted}
    candidates = (
        extract_finqa_numeric_candidates(
            case,
            admitted_evidence_ids=admitted_ids,
        ).candidates
        if admitted_ids
        else ()
    )
    return {
        "admitted_ids": admitted_ids,
        "candidates": candidates,
        "context": {unit.unit_id: unit.text for unit in admitted},
        "quarantined_count": len(evidence) - len(admitted),
        "guard_rule_ids": sorted(rule_ids),
    }


def _typed_case_evaluation(
    *,
    case,
    evidence,
    execution,
    program,
    generation_calls,
    latency_ms,
    admitted_count,
    quarantined_count,
    guard_rule_ids,
):
    answer = FinQAAnswerResult(
        final_answer=format(execution.value, "f"),
        calculation=json.dumps(
            program.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ),
        cited_unit_ids=execution.evidence_ids,
        provided_unit_ids=tuple(unit.unit_id for unit in evidence),
        admitted_count=admitted_count,
        quarantined_count=quarantined_count,
        guard_rule_ids=tuple(guard_rule_ids),
        attempt_count=generation_calls,
        latency_ms=latency_ms,
        calculator_calls=execution.diagnostics.step_count,
    )
    return evaluate_finqa_case(
        case,
        retrieval_mode="hybrid",
        selected_units=evidence,
        answer=answer,
    )


def _bounded_failure_reason(error: ValueError) -> str:
    message = str(error).casefold()
    if "candidate budget" in message:
        return "candidate_budget_exceeded"
    if "context budget" in message or "prompt budget" in message:
        return "prompt_budget_exceeded"
    if "no admitted operand" in message:
        return "no_admitted_operand_candidate"
    return "typed_precondition_failed"


def _evaluate_b1_v2(
    *,
    case: FinQACase,
    source: FinQATypedRetrospectiveCase,
    planner: LocalFinQATypedProgramPlannerV2,
) -> FinQATypedCalibrationRunCase:
    evidence = _source_evidence(case, source.selected_unit_ids)
    context = _prepare_typed_context(case, evidence)
    candidates = context["candidates"]
    started = time.perf_counter()
    if not context["admitted_ids"] or not candidates:
        result = refused_arm_evaluation(
            arm_id="B1_TYPED_SINGLE",
            failure_reason=(
                "guard_quarantined_all"
                if not context["admitted_ids"]
                else "no_numeric_candidates"
            ),
            generation_calls=0,
            compiler_calls=0,
            generated_program_count=0,
            latency_ms=(time.perf_counter() - started) * 1000,
            candidate_count=len(candidates),
        )
    else:
        try:
            planned = planner.plan_and_execute(
                question=case.qa.question,
                candidates=candidates,
                admitted_evidence_ids=context["admitted_ids"],
                evidence_context_by_id=context["context"],
            )
        except TypedPlannerProtocolError as error:
            result = refused_arm_evaluation(
                arm_id="B1_TYPED_SINGLE",
                failure_reason=error.last_reason,
                generation_calls=error.attempt_count,
                compiler_calls=error.compiler_calls,
                generated_program_count=error.compiler_calls,
                latency_ms=error.latency_ms,
                candidate_count=len(candidates),
                status="PROTOCOL_ERROR",
            )
        except TypedProgramValidationError as error:
            result = refused_arm_evaluation(
                arm_id="B1_TYPED_SINGLE",
                failure_reason=error.reason,
                generation_calls=0,
                compiler_calls=0,
                generated_program_count=0,
                latency_ms=(time.perf_counter() - started) * 1000,
                candidate_count=len(candidates),
            )
        except ValueError as error:
            result = refused_arm_evaluation(
                arm_id="B1_TYPED_SINGLE",
                failure_reason=_bounded_failure_reason(error),
                generation_calls=0,
                compiler_calls=0,
                generated_program_count=0,
                latency_ms=(time.perf_counter() - started) * 1000,
                candidate_count=len(candidates),
            )
        else:
            evaluation = _typed_case_evaluation(
                case=case,
                evidence=evidence,
                execution=planned.execution,
                program=planned.program,
                generation_calls=planned.generation_calls,
                latency_ms=planned.latency_ms,
                admitted_count=len(context["admitted_ids"]),
                quarantined_count=context["quarantined_count"],
                guard_rule_ids=context["guard_rule_ids"],
            )
            result = arm_evaluation_from_case(
                arm_id="B1_TYPED_SINGLE",
                evaluation=evaluation,
                compiler_calls=planned.compiler_calls,
                generated_program_count=1,
                candidate_count=len(candidates),
                selected_program_sha256=planned.execution.program_sha256,
                selected_support_count=1,
                valid_program_count=1,
            )
    return FinQATypedCalibrationRunCase(
        case_id=case.id,
        cohort="calibration",
        diagnostic_category=source.diagnostic_category,
        selected_unit_ids=source.selected_unit_ids,
        gold_unit_ids=source.gold_unit_ids,
        b0=source.b0,
        b1_v1=source.b1,
        b1_v2=result,
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


def _ollama_model_digest(model: str) -> str:
    settings = get_settings()
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
        if isinstance(item, dict) and item.get("name") == model
    ]
    if len(exact) != 1 or not isinstance(exact[0], str):
        raise ValueError("frozen Ollama model is not installed exactly once")
    return exact[0]


def main() -> int:
    args = build_parser().parse_args()
    if args.cohort == "internal_validation" and not args.allow_internal_validation:
        raise ValueError(
            "internal validation requires --allow-internal-validation"
        )
    if args.cohort == "calibration" and args.fail_closed_suite_passed:
        raise ValueError(
            "calibration cohort must not assert an adoption-only suite result"
        )
    protocol = FinQATypedCalibrationProtocol.model_validate_json(
        args.protocol.read_bytes()
    )
    protocol_digest = hashlib.sha256(
        canonical_json_bytes(protocol.model_dump(mode="json"))
    ).hexdigest()
    source_manifest = verify_typed_retrospective_run(args.source_run)
    if (
        source_manifest.run_id != protocol.source_gate_e_run_id
        or _sha256(args.source_run / "manifest.json")
        != protocol.source_gate_e_manifest_sha256
        or _sha256(args.source_run / "details.jsonl")
        != protocol.source_gate_e_details_sha256
    ):
        raise ValueError("Gate E source run does not match calibration protocol")
    case_ids = _load_private_split(
        args.private_split,
        protocol=protocol,
        cohort=args.cohort,
    )
    source_rows = _load_source_rows(args.source_run / "details.jsonl")
    source_by_id = {row.case_id: row for row in source_rows}
    if any(case_id not in source_by_id for case_id in case_ids):
        raise ValueError("calibration split references a missing Gate E case")
    cases, _ = load_finqa_split(
        args.dataset,
        expected_sha256=FINQA_DEV_SHA256,
    )
    cases_by_id = {case.id: case for case in cases}
    if any(case_id not in cases_by_id for case_id in case_ids):
        raise ValueError("calibration split references a missing FinQA case")
    implementation_hashes = _implementation_hashes()
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "DRY_RUN_OK",
                    "cohort": args.cohort,
                    "case_count": len(case_ids),
                    "case_ids_sha256": case_ids_sha256(case_ids),
                    "protocol_sha256": protocol_digest,
                    "implementation_file_sha256": implementation_hashes,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    model = source_manifest.answer_model
    model_digest = _ollama_model_digest(model.name)
    if model_digest != model.sha256:
        raise ValueError("Ollama model digest changed since Gate E")
    settings = get_settings()
    planner = LocalFinQATypedProgramPlannerV2(
        model=model.name,
        chat_fn=_timed_chat(source_manifest.timeout_seconds),
        max_attempts=source_manifest.max_attempts,
    )
    selected_sources = [source_by_id[case_id] for case_id in case_ids]
    checkpoint = ResumableCaseCheckpoint.open(
        root=args.checkpoint_root,
        run_id=args.run_id,
        contract={
            "kind": "finqa_typed_contract_calibration_v2",
            "claim_label": protocol.claim_label,
            "protocol_sha256": protocol_digest,
            "source_gate_e_details_sha256": (
                protocol.source_gate_e_details_sha256
            ),
            "cohort": args.cohort,
            "answer_model": model.model_dump(mode="json"),
            "implementation_file_sha256": implementation_hashes,
            "intent_version": INTENT_VERSION,
            "validator_version": VALIDATOR_VERSION,
            "compiler_version": COMPILER_VERSION,
            "planner_version": PLANNER_VERSION,
        },
        expected_case_ids=case_ids,
    )
    existing = checkpoint.load_rows(FinQATypedCalibrationRunCase)
    if existing:
        print(
            f"resuming after {len(existing)}/{len(case_ids)} cases",
            file=sys.stderr,
            flush=True,
        )

    def evaluate(index: int, source: FinQATypedRetrospectiveCase):
        print(
            f"[{index + 1}/{len(case_ids)}] cohort={args.cohort}",
            file=sys.stderr,
            flush=True,
        )
        row = _evaluate_b1_v2(
            case=cases_by_id[source.case_id],
            source=source,
            planner=planner,
        )
        return row.model_copy(update={"cohort": args.cohort})

    lock_root = Path(settings.runtime_cache_dir).resolve() / "evaluation_locks"
    with evaluation_lock(settings.llm_base_url, lock_root=lock_root):
        rows = run_resumable_cases(
            checkpoint=checkpoint,
            row_type=FinQATypedCalibrationRunCase,
            cases=selected_sources,
            evaluate=evaluate,
        )
    summary = summarize_calibration_run(
        rows,
        cohort=args.cohort,
        adoption_gates=protocol.adoption_gates,
        fail_closed_regression_suite_passed=(
            args.fail_closed_suite_passed
        ),
    )
    manifest = FinQATypedCalibrationRunManifest(
        run_id=args.run_id,
        protocol_id=protocol.protocol_id,
        protocol_sha256=protocol_digest,
        source_gate_e_run_id=protocol.source_gate_e_run_id,
        source_gate_e_details_sha256=protocol.source_gate_e_details_sha256,
        cohort=args.cohort,
        selected_case_count=len(case_ids),
        selected_case_ids_sha256=case_ids_sha256(case_ids),
        answer_model=FrozenModelIdentity(
            name=model.name,
            sha256=model_digest,
        ),
        execution_code_revision=_git_head(),
        implementation_file_sha256=implementation_hashes,
        intent_version=INTENT_VERSION,
        validator_version=VALIDATOR_VERSION,
        compiler_version=COMPILER_VERSION,
        planner_version=PLANNER_VERSION,
        timeout_seconds=source_manifest.timeout_seconds,
        max_attempts=source_manifest.max_attempts,
        adoption_gates=protocol.adoption_gates,
        fail_closed_regression_suite_passed=(
            args.fail_closed_suite_passed
        ),
        summary=summary,
    )
    output = publish_calibration_run(
        root=args.out_root,
        manifest=manifest,
        details=rows,
    )
    verified = verify_calibration_run(output)
    checkpoint.seal(
        final_manifest_sha256=_sha256(output / "manifest.json"),
        final_details_sha256=_sha256(output / "details.jsonl"),
    )
    print(
        json.dumps(
            {
                "run_id": verified.run_id,
                "claim_label": verified.claim_label,
                "cohort": verified.cohort,
                "output_dir": str(output),
                "summary": verified.summary.model_dump(mode="json"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
