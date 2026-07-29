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
    FINQA_REVISION,
    FinQACase,
    FinQAEvidenceUnit,
    build_finqa_evidence_units,
    load_finqa_split,
)
from app.external_datasets.finqa_diagnostics import FinQADiagnosticRow
from app.external_datasets.finqa_eval import (
    FinQAAnswerProtocolError,
    FinQAAnswerResult,
    FinQACaseEvaluation,
    LocalFinQAProgramAnswerer,
    evaluate_finqa_case,
    evaluate_finqa_protocol_error,
    selected_case_ids_sha256,
    verify_finqa_run,
)
from app.external_datasets.finqa_multi_program import (
    MULTI_PROGRAM_PLANNER_VERSION,
    SELECTOR_VERSION,
    LocalFinQAMultiProgramPlanner,
    MultiProgramProtocolError,
)
from app.external_datasets.finqa_typed_planner import (
    INTENT_VERSION,
    PLANNER_VERSION,
    LocalFinQATypedProgramPlanner,
    TypedPlannerProtocolError,
)
from app.external_datasets.finqa_typed_program import (
    COMPILER_VERSION,
    DSL_VERSION,
    EXTRACTION_CONFIG_SHA256,
    EXTRACTION_VERSION,
    VALIDATOR_VERSION,
    TypedProgramValidationError,
    extract_finqa_numeric_candidates,
)
from app.external_datasets.finqa_typed_retrospective import (
    FinQATypedArmEvaluation,
    FinQATypedRetrospectiveCase,
    FinQATypedRetrospectiveRunManifest,
    FrozenModelIdentity,
    arm_evaluation_from_case,
    implementation_snapshot_sha256,
    load_protocol,
    protocol_sha256,
    publish_typed_retrospective_run,
    refused_arm_evaluation,
    summarize_typed_retrospective,
    validate_frozen_source_files,
    verify_typed_retrospective_run,
)
from app.ollama_chat import chat_with_ollama
from app.runtime.model_transport import perform_model_request
from app.security.retrieved_content import RetrievedContentGuard
from app.security.model_endpoint import parse_pinned_model_endpoint


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_typed_retrospective_protocol_v1.json"
)
DEFAULT_OUT_ROOT = DEFAULT_PRIVATE_ROOT / "typed_retrospective_runs"
DEFAULT_CHECKPOINT_ROOT = (
    DEFAULT_PRIVATE_ROOT / "checkpoints" / "typed_retrospective"
)
_ARM_ORDERS = (
    ("B0_FREE_LITERAL", "B1_TYPED_SINGLE", "B2_TYPED_MULTI"),
    ("B1_TYPED_SINGLE", "B2_TYPED_MULTI", "B0_FREE_LITERAL"),
    ("B2_TYPED_MULTI", "B0_FREE_LITERAL", "B1_TYPED_SINGLE"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the frozen FinQA typed-program retrospective dev comparison."
        )
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument(
        "--checkpoint-root",
        type=Path,
        default=DEFAULT_CHECKPOINT_ROOT,
    )
    parser.add_argument("--validate-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol = load_protocol(args.protocol)
    protocol_digest = protocol_sha256(args.protocol)
    validate_frozen_source_files(
        protocol,
        repository_root=REPOSITORY_ROOT,
    )
    _validate_versions(protocol)
    if (
        protocol.dataset_revision != FINQA_REVISION
        or protocol.split_sha256 != FINQA_DEV_SHA256
    ):
        raise ValueError("typed retrospective dataset pin mismatch")

    settings = get_settings()
    model_digest = _ollama_model_digest(protocol.answer_model.name)
    if model_digest != protocol.answer_model.sha256:
        raise ValueError("typed retrospective answer-model identity mismatch")

    split_path = args.source_root.resolve() / "dataset" / "dev.json"
    source_cases, split_sha256 = load_finqa_split(
        split_path,
        expected_sha256=protocol.split_sha256,
    )
    cases_by_id = {case.id: case for case in source_cases}
    source_run_dir = (
        DEFAULT_PRIVATE_ROOT / "eval_runs" / protocol.source_eval_run.run_id
    )
    source_manifest = verify_finqa_run(source_run_dir)
    _validate_source_artifact(
        source_run_dir / "manifest.json",
        protocol.source_eval_run.manifest_sha256,
    )
    _validate_source_artifact(
        source_run_dir / "details.jsonl",
        protocol.source_eval_run.details_sha256,
    )
    source_rows = _load_model_rows(
        source_run_dir / "details.jsonl",
        FinQACaseEvaluation,
    )
    diagnostic_dir = (
        DEFAULT_PRIVATE_ROOT
        / "diagnostic_runs"
        / protocol.source_diagnostic_run.run_id
    )
    _validate_source_artifact(
        diagnostic_dir / "manifest.json",
        protocol.source_diagnostic_run.manifest_sha256,
    )
    _validate_source_artifact(
        diagnostic_dir / "details.jsonl",
        protocol.source_diagnostic_run.details_sha256,
    )
    diagnostic_rows = _load_model_rows(
        diagnostic_dir / "details.jsonl",
        FinQADiagnosticRow,
    )
    selected_case_ids = [row.case_id for row in source_rows]
    if (
        source_manifest.retrieval_mode != protocol.retrieval_mode
        or source_manifest.top_k != protocol.top_k
        or source_manifest.answer_model != protocol.answer_model.name
        or source_manifest.answer_model_sha256 != protocol.answer_model.sha256
        or source_manifest.selected_case_count != protocol.selected_case_count
        or source_manifest.selected_case_ids_sha256
        != protocol.selected_case_ids_sha256
        or selected_case_ids_sha256(
            [cases_by_id[item] for item in selected_case_ids]
        )
        != protocol.selected_case_ids_sha256
        or len(diagnostic_rows) != protocol.selected_case_count
        or [row.case_id for row in diagnostic_rows] != selected_case_ids
    ):
        raise ValueError("typed retrospective selected-case contract mismatch")
    if args.validate_only:
        print(
            json.dumps(
                {
                    "status": "VALIDATED_NOT_EXECUTED",
                    "claim_label": protocol.claim_label,
                    "protocol_id": protocol.protocol_id,
                    "protocol_sha256": protocol_digest,
                    "selected_case_count": len(source_rows),
                    "selected_case_ids_sha256": (
                        protocol.selected_case_ids_sha256
                    ),
                    "answer_model": protocol.answer_model.model_dump(
                        mode="json"
                    ),
                    "implementation_snapshot_sha256": (
                        implementation_snapshot_sha256(
                            protocol.source_file_sha256
                        )
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    checkpoint = ResumableCaseCheckpoint.open(
        root=args.checkpoint_root,
        run_id=args.run_id,
        contract={
            "kind": "finqa_typed_retrospective",
            "claim_label": protocol.claim_label,
            "protocol_sha256": protocol_digest,
            "dataset_revision": protocol.dataset_revision,
            "split_sha256": split_sha256,
            "selected_case_ids_sha256": protocol.selected_case_ids_sha256,
            "answer_model": protocol.answer_model.model_dump(mode="json"),
            "implementation_snapshot_sha256": implementation_snapshot_sha256(
                protocol.source_file_sha256
            ),
            "arm_order_policy": protocol.arm_order_policy,
            "timeout_seconds": protocol.timeout_seconds,
            "max_attempts": protocol.max_attempts,
            "multi_program_count": protocol.multi_program_count,
        },
        expected_case_ids=selected_case_ids,
    )
    existing_rows = checkpoint.load_rows(FinQATypedRetrospectiveCase)
    if existing_rows:
        print(
            f"resuming after {len(existing_rows)}/{len(source_rows)} cases",
            file=sys.stderr,
            flush=True,
        )

    answerer = LocalFinQAProgramAnswerer(
        model=protocol.answer_model.name,
        chat_fn=_timed_chat(protocol.timeout_seconds),
        max_attempts=protocol.max_attempts,
    )
    typed_planner = LocalFinQATypedProgramPlanner(
        model=protocol.answer_model.name,
        chat_fn=_timed_chat(protocol.timeout_seconds),
        max_attempts=protocol.max_attempts,
    )
    multi_planner = LocalFinQAMultiProgramPlanner(
        model=protocol.answer_model.name,
        chat_fn=_timed_chat(protocol.timeout_seconds),
        program_count=protocol.multi_program_count,
        max_attempts=protocol.max_attempts,
    )
    diagnostic_by_id = {row.case_id: row for row in diagnostic_rows}

    def evaluate(index: int, source_row: FinQACaseEvaluation):
        case = cases_by_id[source_row.case_id]
        evidence = _source_evidence(case, source_row.selected_unit_ids)
        order = _ARM_ORDERS[index % len(_ARM_ORDERS)]
        print(
            f"[{index + 1}/{len(source_rows)}] {case.id} order={','.join(order)}",
            file=sys.stderr,
            flush=True,
        )
        arm_results: dict[str, FinQATypedArmEvaluation] = {}
        typed_context = _prepare_typed_context(case, evidence)
        for arm_id in order:
            if arm_id == "B0_FREE_LITERAL":
                arm_results[arm_id] = _evaluate_b0(
                    case=case,
                    evidence=evidence,
                    answerer=answerer,
                )
            elif arm_id == "B1_TYPED_SINGLE":
                arm_results[arm_id] = _evaluate_b1(
                    case=case,
                    evidence=evidence,
                    typed_context=typed_context,
                    planner=typed_planner,
                )
            else:
                arm_results[arm_id] = _evaluate_b2(
                    case=case,
                    evidence=evidence,
                    typed_context=typed_context,
                    planner=multi_planner,
                )
        selected_gold = set(source_row.selected_unit_ids).intersection(
            source_row.gold_unit_ids
        )
        return FinQATypedRetrospectiveCase(
            case_id=case.id,
            diagnostic_category=diagnostic_by_id[case.id].category,
            execution_order=order,
            selected_unit_ids=source_row.selected_unit_ids,
            gold_unit_ids=source_row.gold_unit_ids,
            selected_evidence_recall=(
                len(selected_gold) / len(source_row.gold_unit_ids)
            ),
            admitted_unit_count=len(typed_context["admitted_ids"]),
            quarantined_unit_count=typed_context["quarantined_count"],
            guard_rule_ids=typed_context["guard_rule_ids"],
            historical_b0_strict_execution_match=(
                source_row.strict_execution_match
            ),
            historical_b0_grounded_execution_match=(
                source_row.grounded_execution_match
            ),
            b0=arm_results["B0_FREE_LITERAL"],
            b1=arm_results["B1_TYPED_SINGLE"],
            b2=arm_results["B2_TYPED_MULTI"],
        )

    lock_root = Path(settings.runtime_cache_dir).resolve() / "evaluation_locks"
    with evaluation_lock(settings.llm_base_url, lock_root=lock_root):
        rows = run_resumable_cases(
            checkpoint=checkpoint,
            row_type=FinQATypedRetrospectiveCase,
            cases=source_rows,
            evaluate=evaluate,
        )

    summary = summarize_typed_retrospective(rows)
    manifest = FinQATypedRetrospectiveRunManifest(
        run_id=args.run_id,
        protocol_id=protocol.protocol_id,
        protocol_sha256=protocol_digest,
        dataset_revision=protocol.dataset_revision,
        split="dev",
        split_sha256=protocol.split_sha256,
        selected_case_count=protocol.selected_case_count,
        selected_case_ids_sha256=protocol.selected_case_ids_sha256,
        retrieval_mode=protocol.retrieval_mode,
        top_k=protocol.top_k,
        answer_model=FrozenModelIdentity(
            name=protocol.answer_model.name,
            sha256=model_digest,
        ),
        execution_code_revision=_git_head(),
        implementation_snapshot_sha256=implementation_snapshot_sha256(
            protocol.source_file_sha256
        ),
        timeout_seconds=protocol.timeout_seconds,
        max_attempts=protocol.max_attempts,
        multi_program_count=protocol.multi_program_count,
        summary=summary,
    )
    final_dir = args.out_root.resolve() / args.run_id
    if final_dir.exists():
        existing = verify_typed_retrospective_run(final_dir)
        if existing.model_copy(update={"artifacts": {}}) != manifest:
            raise ValueError("existing retrospective run does not match checkpoint")
        output = final_dir
    else:
        output = publish_typed_retrospective_run(
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
                "run_id": args.run_id,
                "claim_label": protocol.claim_label,
                "output_dir": str(output),
                "summary": summary.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


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


def _evaluate_b0(*, case, evidence, answerer) -> FinQATypedArmEvaluation:
    try:
        answer = answerer.answer(
            question=case.qa.question,
            evidence_units=evidence,
        )
    except FinQAAnswerProtocolError as error:
        evaluation = evaluate_finqa_protocol_error(
            case,
            retrieval_mode="hybrid",
            selected_units=evidence,
            error=error,
        )
    else:
        evaluation = evaluate_finqa_case(
            case,
            retrieval_mode="hybrid",
            selected_units=evidence,
            answer=answer,
        )
    return arm_evaluation_from_case(
        arm_id="B0_FREE_LITERAL",
        evaluation=evaluation,
        compiler_calls=evaluation.calculator_calls or 0,
        generated_program_count=evaluation.calculator_calls or 0,
        candidate_count=0,
    )


def _evaluate_b1(
    *,
    case,
    evidence,
    typed_context,
    planner,
) -> FinQATypedArmEvaluation:
    candidates = typed_context["candidates"]
    started = time.perf_counter()
    if not typed_context["admitted_ids"]:
        return refused_arm_evaluation(
            arm_id="B1_TYPED_SINGLE",
            failure_reason="guard_quarantined_all",
            generation_calls=0,
            compiler_calls=0,
            generated_program_count=0,
            latency_ms=(time.perf_counter() - started) * 1000,
            candidate_count=0,
        )
    if not candidates:
        return refused_arm_evaluation(
            arm_id="B1_TYPED_SINGLE",
            failure_reason="no_numeric_candidates",
            generation_calls=0,
            compiler_calls=0,
            generated_program_count=0,
            latency_ms=(time.perf_counter() - started) * 1000,
            candidate_count=0,
        )
    try:
        result = planner.plan_and_execute(
            question=case.qa.question,
            candidates=candidates,
            admitted_evidence_ids=typed_context["admitted_ids"],
            evidence_context_by_id=typed_context["context"],
        )
    except TypedPlannerProtocolError as error:
        return refused_arm_evaluation(
            arm_id="B1_TYPED_SINGLE",
            failure_reason=error.last_reason,
            generation_calls=error.attempt_count,
            compiler_calls=0,
            generated_program_count=0,
            latency_ms=error.latency_ms,
            candidate_count=len(candidates),
            status="PROTOCOL_ERROR",
        )
    except TypedProgramValidationError as error:
        return refused_arm_evaluation(
            arm_id="B1_TYPED_SINGLE",
            failure_reason=error.reason,
            generation_calls=0,
            compiler_calls=0,
            generated_program_count=0,
            latency_ms=(time.perf_counter() - started) * 1000,
            candidate_count=len(candidates),
        )
    except ValueError as error:
        return refused_arm_evaluation(
            arm_id="B1_TYPED_SINGLE",
            failure_reason=_bounded_failure_reason(error),
            generation_calls=0,
            compiler_calls=0,
            generated_program_count=0,
            latency_ms=(time.perf_counter() - started) * 1000,
            candidate_count=len(candidates),
        )
    evaluation = _typed_case_evaluation(
        case=case,
        evidence=evidence,
        execution=result.execution,
        program=result.program,
        generation_calls=result.generation_calls,
        latency_ms=result.latency_ms,
        admitted_count=len(typed_context["admitted_ids"]),
        quarantined_count=typed_context["quarantined_count"],
        guard_rule_ids=typed_context["guard_rule_ids"],
    )
    return arm_evaluation_from_case(
        arm_id="B1_TYPED_SINGLE",
        evaluation=evaluation,
        compiler_calls=result.compiler_calls,
        generated_program_count=1,
        candidate_count=len(candidates),
        selected_program_sha256=result.execution.program_sha256,
        selected_support_count=1,
        valid_program_count=1,
    )


def _evaluate_b2(
    *,
    case,
    evidence,
    typed_context,
    planner,
) -> FinQATypedArmEvaluation:
    candidates = typed_context["candidates"]
    started = time.perf_counter()
    if not typed_context["admitted_ids"] or not candidates:
        return refused_arm_evaluation(
            arm_id="B2_TYPED_MULTI",
            failure_reason=(
                "guard_quarantined_all"
                if not typed_context["admitted_ids"]
                else "no_numeric_candidates"
            ),
            generation_calls=0,
            compiler_calls=0,
            generated_program_count=0,
            latency_ms=(time.perf_counter() - started) * 1000,
            candidate_count=len(candidates),
        )
    try:
        result = planner.plan_and_select(
            question=case.qa.question,
            candidates=candidates,
            admitted_evidence_ids=typed_context["admitted_ids"],
            evidence_context_by_id=typed_context["context"],
        )
    except MultiProgramProtocolError as error:
        return refused_arm_evaluation(
            arm_id="B2_TYPED_MULTI",
            failure_reason=error.last_reason,
            generation_calls=error.attempt_count,
            compiler_calls=0,
            generated_program_count=0,
            latency_ms=error.latency_ms,
            candidate_count=len(candidates),
            status="PROTOCOL_ERROR",
        )
    except TypedProgramValidationError as error:
        return refused_arm_evaluation(
            arm_id="B2_TYPED_MULTI",
            failure_reason=error.reason,
            generation_calls=0,
            compiler_calls=0,
            generated_program_count=0,
            latency_ms=(time.perf_counter() - started) * 1000,
            candidate_count=len(candidates),
        )
    except ValueError as error:
        return refused_arm_evaluation(
            arm_id="B2_TYPED_MULTI",
            failure_reason=_bounded_failure_reason(error),
            generation_calls=0,
            compiler_calls=0,
            generated_program_count=0,
            latency_ms=(time.perf_counter() - started) * 1000,
            candidate_count=len(candidates),
        )
    selection = result.selection
    if selection.status != "SELECTED":
        return refused_arm_evaluation(
            arm_id="B2_TYPED_MULTI",
            failure_reason=selection.status.casefold(),
            generation_calls=result.generation_calls,
            compiler_calls=result.compiler_calls,
            generated_program_count=result.generated_program_count,
            latency_ms=result.latency_ms,
            candidate_count=len(candidates),
            valid_program_count=selection.valid_program_count,
            invalid_program_count=selection.invalid_program_count,
            duplicate_program_count=selection.duplicate_program_count,
        )
    assert selection.selected_execution is not None
    assert selection.selected_program is not None
    evaluation = _typed_case_evaluation(
        case=case,
        evidence=evidence,
        execution=selection.selected_execution,
        program=selection.selected_program,
        generation_calls=result.generation_calls,
        latency_ms=result.latency_ms,
        admitted_count=len(typed_context["admitted_ids"]),
        quarantined_count=typed_context["quarantined_count"],
        guard_rule_ids=typed_context["guard_rule_ids"],
    )
    return arm_evaluation_from_case(
        arm_id="B2_TYPED_MULTI",
        evaluation=evaluation,
        compiler_calls=result.compiler_calls,
        generated_program_count=result.generated_program_count,
        candidate_count=len(candidates),
        selected_program_sha256=selection.selected_program_sha256,
        selected_support_count=selection.selected_support_count,
        valid_program_count=selection.valid_program_count,
        invalid_program_count=selection.invalid_program_count,
        duplicate_program_count=selection.duplicate_program_count,
    )


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


def _source_evidence(
    case: FinQACase,
    selected_unit_ids: list[str],
) -> tuple[FinQAEvidenceUnit, ...]:
    by_id = {unit.unit_id: unit for unit in build_finqa_evidence_units(case)}
    if any(unit_id not in by_id for unit_id in selected_unit_ids):
        raise ValueError("source evaluation references unknown evidence")
    return tuple(by_id[unit_id] for unit_id in selected_unit_ids)


def _load_model_rows(path: Path, model_type):
    return [
        model_type.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _validate_source_artifact(path: Path, expected_sha256: str) -> None:
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError(f"source artifact hash mismatch: {path.name}")


def _bounded_failure_reason(error: ValueError) -> str:
    message = str(error).casefold()
    if "candidate budget" in message:
        return "candidate_budget_exceeded"
    if "context budget" in message or "prompt budget" in message:
        return "prompt_budget_exceeded"
    if "no admitted operand" in message:
        return "no_admitted_operand_candidate"
    return "typed_precondition_failed"


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
    fallback = [
        item.get("digest")
        for item in payload["models"]
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and item["name"].removesuffix(":latest") == model
    ]
    candidates = exact or fallback
    if len(candidates) != 1 or not isinstance(candidates[0], str):
        raise ValueError("typed retrospective model identity is ambiguous")
    digest = candidates[0].removeprefix("sha256:")
    if len(digest) != 64 or any(
        char not in "0123456789abcdef" for char in digest
    ):
        raise ValueError("typed retrospective model digest is invalid")
    return digest


def _validate_versions(protocol) -> None:
    actual = {
        "candidate_extraction_version": EXTRACTION_VERSION,
        "candidate_extraction_config_sha256": EXTRACTION_CONFIG_SHA256,
        "intent_version": INTENT_VERSION,
        "dsl_version": DSL_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "compiler_version": COMPILER_VERSION,
        "typed_planner_version": PLANNER_VERSION,
        "multi_program_planner_version": MULTI_PROGRAM_PLANNER_VERSION,
        "selector_version": SELECTOR_VERSION,
    }
    expected = {name: getattr(protocol, name) for name in actual}
    if actual != expected:
        raise ValueError("typed retrospective implementation-version mismatch")


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
