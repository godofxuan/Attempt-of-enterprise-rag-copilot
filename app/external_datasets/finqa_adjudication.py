from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import tempfile
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.safe_calculator import execute_decimal_expression
from app.external_datasets.finqa import FinQACase, FinQAEvidenceUnit
from app.external_datasets.finqa_eval import (
    MAX_FINQA_EVIDENCE_UNITS,
    MAX_FINQA_UNIT_CHARS,
    FinQAAnswerResult,
    FinQACaseEvaluation,
    FinQAChatFn,
    FinQARetrievalMode,
    FinQASummary,
    evaluate_finqa_case,
    summarize_finqa_cases,
)
from app.external_datasets.finqa_review import (
    FinQACorrectnessTransition,
    FinQAReviewCaseEvaluation,
    FinQAReviewRunManifest,
    FinQAReviewStatus,
    FinQAReviewSummary,
)
from app.filesystem import atomic_directory_move
from app.ollama_chat import chat_with_ollama
from app.security.retrieved_content import RetrievedContentGuard


FinQAAdjudicationStatus = Literal[
    "proposal_accepted",
    "baseline_retained",
    "fallback_protocol_error",
    "not_applicable_unchanged_proposal",
]
FinQACandidateSource = Literal["baseline", "proposal"]

FINQA_ADJUDICATION_PROMPT_VERSION = "finqa_candidate_adjudication_v1"
_ADJUDICATION_ARTIFACTS = {"details.jsonl", "summary.json"}


class FinQAAdjudicationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_candidate: Literal["candidate-a", "candidate-b"]


@dataclass(frozen=True)
class FinQAAdjudicationResult:
    selected_source: FinQACandidateSource
    status: Literal[
        "proposal_accepted",
        "baseline_retained",
        "fallback_protocol_error",
    ]
    generation_calls: int
    calculator_calls: int
    latency_ms: float


class FinQAAdjudicationCaseEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    baseline: FinQACaseEvaluation
    proposal: FinQACaseEvaluation
    adjudicated: FinQACaseEvaluation
    proposal_review_status: FinQAReviewStatus
    adjudication_status: FinQAAdjudicationStatus
    correctness_transition: FinQACorrectnessTransition
    adjudication_generation_calls: int = Field(ge=0)
    adjudication_calculator_calls: int = Field(ge=0)
    adjudication_latency_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_pair_invariants(
        self,
    ) -> FinQAAdjudicationCaseEvaluation:
        if not (
            self.case_id
            == self.baseline.case_id
            == self.proposal.case_id
            == self.adjudicated.case_id
        ):
            raise ValueError("FinQA adjudication case IDs do not match")
        if not (
            self.baseline.retrieval_mode
            == self.proposal.retrieval_mode
            == self.adjudicated.retrieval_mode
        ):
            raise ValueError("FinQA adjudication changed retrieval mode")
        if not (
            self.baseline.selected_unit_ids
            == self.proposal.selected_unit_ids
            == self.adjudicated.selected_unit_ids
        ):
            raise ValueError("FinQA adjudication changed frozen evidence")
        expected_transition = _correctness_transition(
            self.baseline.strict_execution_match,
            self.adjudicated.strict_execution_match,
        )
        if self.correctness_transition != expected_transition:
            raise ValueError("FinQA adjudication transition is invalid")
        if self.adjudicated.generation_calls != (
            self.proposal.generation_calls
            + self.adjudication_generation_calls
        ):
            raise ValueError("FinQA adjudication generation total is invalid")
        if (
            self.proposal.calculator_calls is not None
            and self.adjudicated.calculator_calls
            != self.proposal.calculator_calls
            + self.adjudication_calculator_calls
        ):
            raise ValueError("FinQA adjudication calculator total is invalid")
        if abs(
            self.adjudicated.latency_ms
            - self.proposal.latency_ms
            - self.adjudication_latency_ms
        ) > 1e-6:
            raise ValueError("FinQA adjudication latency total is invalid")
        output = (
            self.adjudicated.final_answer,
            self.adjudicated.calculation,
            self.adjudicated.cited_unit_ids,
        )
        baseline_output = (
            self.baseline.final_answer,
            self.baseline.calculation,
            self.baseline.cited_unit_ids,
        )
        proposal_output = (
            self.proposal.final_answer,
            self.proposal.calculation,
            self.proposal.cited_unit_ids,
        )
        if self.adjudication_status == "proposal_accepted":
            if output != proposal_output:
                raise ValueError("FinQA accepted proposal output changed")
        elif self.adjudication_status in {
            "baseline_retained",
            "fallback_protocol_error",
        }:
            if output != baseline_output:
                raise ValueError("FinQA retained baseline output changed")
        else:
            if (
                output != proposal_output
                or self.adjudication_generation_calls != 0
                or self.adjudication_calculator_calls != 0
                or self.adjudication_latency_ms != 0
            ):
                raise ValueError(
                    "FinQA unchanged proposal must bypass adjudication"
                )
        return self


class FinQAAdjudicationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_count: int = Field(ge=1)
    adjudication_eligible_case_count: int = Field(ge=0)
    baseline: FinQASummary
    proposal: FinQASummary
    adjudicated: FinQASummary
    source_review: FinQAReviewSummary
    status_counts: dict[FinQAAdjudicationStatus, int]
    transition_counts: dict[FinQACorrectnessTransition, int]
    discordant_case_count: int = Field(ge=0)
    mcnemar_exact_p_value: float = Field(ge=0, le=1)
    incremental_adjudication_generation_calls: int = Field(ge=0)
    incremental_adjudication_calculator_calls: int = Field(ge=0)
    adjudication_latency_ms_mean_eligible: float = Field(ge=0)
    adjudication_latency_ms_p95_eligible: float = Field(ge=0)
    execution_accuracy_delta: float = Field(ge=-1, le=1)
    grounded_execution_accuracy_delta: float = Field(ge=-1, le=1)
    citation_recall_delta: float = Field(ge=-1, le=1)
    generation_call_multiplier: float = Field(ge=1)
    calculator_call_multiplier: float | None = Field(default=None, ge=1)
    latency_mean_multiplier: float = Field(ge=1)


class FinQAAdjudicationRunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["finqa_adjudication_run_v1"] = (
        "finqa_adjudication_run_v1"
    )
    adjudication_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$"
    )
    adjudication_prompt_version: Literal[
        "finqa_candidate_adjudication_v1"
    ] = FINQA_ADJUDICATION_PROMPT_VERSION
    source_review_run_id: str = Field(min_length=1, max_length=200)
    source_review_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_review_details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    split: Literal["dev"]
    split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_case_count: int = Field(ge=1)
    retrieval_mode: FinQARetrievalMode
    source_review_code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    adjudication_code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    adjudicator_model: str = Field(min_length=1)
    adjudicator_model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    timeout_seconds: float = Field(gt=0, le=300)
    max_attempts: int = Field(ge=1, le=3)
    summary: FinQAAdjudicationSummary
    artifacts: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_artifacts(self) -> FinQAAdjudicationRunManifest:
        if self.artifacts and (
            set(self.artifacts) != _ADJUDICATION_ARTIFACTS
            or any(
                re.fullmatch(r"[0-9a-f]{64}", digest) is None
                for digest in self.artifacts.values()
            )
        ):
            raise ValueError("FinQA adjudication artifact set is invalid")
        return self


class LocalFinQACandidateAdjudicator:
    def __init__(
        self,
        *,
        model: str,
        chat_fn: FinQAChatFn = chat_with_ollama,
        guard: RetrievedContentGuard | None = None,
        max_attempts: int = 2,
    ) -> None:
        if not model.strip():
            raise ValueError("FinQA adjudicator model must be non-empty")
        if not 1 <= max_attempts <= 3:
            raise ValueError("FinQA adjudication attempts must be between 1 and 3")
        self.model = model.strip()
        self.chat_fn = chat_fn
        self.guard = guard or RetrievedContentGuard()
        self.max_attempts = max_attempts

    def adjudicate(
        self,
        *,
        case_id: str,
        question: str,
        evidence_units: Sequence[FinQAEvidenceUnit],
        source: FinQAReviewCaseEvaluation,
    ) -> FinQAAdjudicationResult:
        if source.case_id != case_id or source.review_status != "revised":
            raise ValueError("FinQA adjudication requires a revised source case")
        question = question.strip()
        units = list(evidence_units)
        if not question or len(question) > 2000:
            raise ValueError(
                "FinQA adjudication question must contain 1-2000 characters"
            )
        if not 1 <= len(units) <= MAX_FINQA_EVIDENCE_UNITS:
            raise ValueError("FinQA adjudication requires 1-20 evidence units")
        unit_ids = [unit.unit_id for unit in units]
        if (
            len(unit_ids) != len(set(unit_ids))
            or unit_ids != source.baseline.selected_unit_ids
        ):
            raise ValueError(
                "FinQA adjudication evidence does not match source order"
            )

        started = time.perf_counter()
        baseline_value = _execute_and_verify(source.baseline)
        proposal_value = _execute_and_verify(source.reviewed)
        calculator_calls = 2
        admitted: list[FinQAEvidenceUnit] = []
        for unit in units:
            if self.guard.scan(unit.text).disposition == "ADMIT":
                admitted.append(unit)
        if not admitted:
            raise ValueError("FinQA adjudication guard removed every unit")
        admitted_ids = {unit.unit_id for unit in admitted}
        required_citations = {
            *source.baseline.cited_unit_ids,
            *source.reviewed.cited_unit_ids,
        }
        if not required_citations.issubset(admitted_ids):
            raise ValueError("FinQA adjudication guard removed a citation")

        candidate_ids = [
            f"evidence-{index:02d}"
            for index in range(1, len(admitted) + 1)
        ]
        by_unit_id = {
            unit.unit_id: candidate_id
            for candidate_id, unit in zip(
                candidate_ids,
                admitted,
                strict=True,
            )
        }
        baseline_first = _baseline_is_candidate_a(case_id)
        candidate_sources: dict[str, FinQACandidateSource] = (
            {
                "candidate-a": "baseline",
                "candidate-b": "proposal",
            }
            if baseline_first
            else {
                "candidate-a": "proposal",
                "candidate-b": "baseline",
            }
        )
        candidates = {
            "baseline": _candidate_payload(
                source.baseline,
                baseline_value,
                by_unit_id,
            ),
            "proposal": _candidate_payload(
                source.reviewed,
                proposal_value,
                by_unit_id,
            ),
        }
        messages = _build_adjudication_messages(
            question=question,
            candidate_ids=candidate_ids,
            units=admitted,
            candidate_sources=candidate_sources,
            candidates=candidates,
        )
        generation_calls = 0
        selected_source: FinQACandidateSource | None = None
        for attempt in range(1, self.max_attempts + 1):
            generation_calls += 1
            raw = self.chat_fn(
                self.model,
                messages,
                response_format=_adjudication_response_format(),
                think=False,
            )
            try:
                parsed = FinQAAdjudicationPayload.model_validate(
                    json.loads(raw, object_pairs_hook=_unique_object)
                )
                selected_source = candidate_sources[
                    parsed.selected_candidate
                ]
                break
            except (json.JSONDecodeError, ValueError):
                if attempt < self.max_attempts:
                    messages = [
                        *messages,
                        {
                            "role": "user",
                            "content": (
                                "Return only JSON selecting candidate-a or "
                                "candidate-b. Do not create another expression."
                            ),
                        },
                    ]
        latency_ms = (time.perf_counter() - started) * 1000
        if selected_source is None:
            return FinQAAdjudicationResult(
                selected_source="baseline",
                status="fallback_protocol_error",
                generation_calls=generation_calls,
                calculator_calls=calculator_calls,
                latency_ms=latency_ms,
            )
        return FinQAAdjudicationResult(
            selected_source=selected_source,
            status=(
                "proposal_accepted"
                if selected_source == "proposal"
                else "baseline_retained"
            ),
            generation_calls=generation_calls,
            calculator_calls=calculator_calls,
            latency_ms=latency_ms,
        )


def evaluate_finqa_adjudication_case(
    case: FinQACase,
    *,
    source: FinQAReviewCaseEvaluation,
    selected_units: Sequence[FinQAEvidenceUnit],
    result: FinQAAdjudicationResult,
) -> FinQAAdjudicationCaseEvaluation:
    if case.id != source.case_id:
        raise ValueError("FinQA adjudication case does not match source")
    chosen = (
        source.reviewed
        if result.selected_source == "proposal"
        else source.baseline
    )
    proposal_calculator_calls = source.reviewed.calculator_calls
    if proposal_calculator_calls is None:
        raise ValueError("FinQA proposal calculator calls are unavailable")
    answer = FinQAAnswerResult(
        final_answer=chosen.final_answer,
        calculation=chosen.calculation,
        cited_unit_ids=tuple(chosen.cited_unit_ids),
        provided_unit_ids=tuple(source.reviewed.selected_unit_ids),
        admitted_count=source.reviewed.admitted_count,
        quarantined_count=source.reviewed.quarantined_count,
        guard_rule_ids=tuple(source.reviewed.guard_rule_ids),
        attempt_count=(
            source.reviewed.generation_calls + result.generation_calls
        ),
        calculator_calls=(
            proposal_calculator_calls + result.calculator_calls
        ),
        latency_ms=source.reviewed.latency_ms + result.latency_ms,
    )
    adjudicated = evaluate_finqa_case(
        case,
        retrieval_mode=source.baseline.retrieval_mode,
        selected_units=selected_units,
        answer=answer,
    )
    return FinQAAdjudicationCaseEvaluation(
        case_id=case.id,
        baseline=source.baseline,
        proposal=source.reviewed,
        adjudicated=adjudicated,
        proposal_review_status=source.review_status,
        adjudication_status=result.status,
        correctness_transition=_correctness_transition(
            source.baseline.strict_execution_match,
            adjudicated.strict_execution_match,
        ),
        adjudication_generation_calls=result.generation_calls,
        adjudication_calculator_calls=result.calculator_calls,
        adjudication_latency_ms=result.latency_ms,
    )


def preserve_unadjudicated_finqa_case(
    source: FinQAReviewCaseEvaluation,
) -> FinQAAdjudicationCaseEvaluation:
    if source.review_status == "revised":
        raise ValueError("FinQA revised proposal requires adjudication")
    return FinQAAdjudicationCaseEvaluation(
        case_id=source.case_id,
        baseline=source.baseline,
        proposal=source.reviewed,
        adjudicated=source.reviewed.model_copy(deep=True),
        proposal_review_status=source.review_status,
        adjudication_status="not_applicable_unchanged_proposal",
        correctness_transition=_correctness_transition(
            source.baseline.strict_execution_match,
            source.reviewed.strict_execution_match,
        ),
        adjudication_generation_calls=0,
        adjudication_calculator_calls=0,
        adjudication_latency_ms=0,
    )


def summarize_finqa_adjudication_cases(
    rows: Sequence[FinQAAdjudicationCaseEvaluation],
    *,
    source_review: FinQAReviewSummary,
) -> FinQAAdjudicationSummary:
    values = list(rows)
    if not values:
        raise ValueError("FinQA adjudication summary requires rows")
    baseline = summarize_finqa_cases([row.baseline for row in values])
    proposal = summarize_finqa_cases([row.proposal for row in values])
    adjudicated = summarize_finqa_cases([row.adjudicated for row in values])
    if proposal != source_review.reviewed or baseline != source_review.baseline:
        raise ValueError("FinQA adjudication source summary mismatch")
    status_names = [
        "proposal_accepted",
        "baseline_retained",
        "fallback_protocol_error",
        "not_applicable_unchanged_proposal",
    ]
    transition_names = [
        "correct_to_correct",
        "correct_to_wrong",
        "wrong_to_correct",
        "wrong_to_wrong",
    ]
    statuses = Counter(row.adjudication_status for row in values)
    transitions = Counter(row.correctness_transition for row in values)
    eligible_latencies = sorted(
        row.adjudication_latency_ms
        for row in values
        if row.adjudication_status
        != "not_applicable_unchanged_proposal"
    )
    p95_index = (
        max(0, int(np.ceil(len(eligible_latencies) * 0.95)) - 1)
        if eligible_latencies
        else 0
    )
    discordant = (
        transitions["correct_to_wrong"]
        + transitions["wrong_to_correct"]
    )
    calculator_multiplier = (
        adjudicated.calculator_calls / baseline.calculator_calls
        if adjudicated.calculator_calls is not None
        and baseline.calculator_calls not in {None, 0}
        else None
    )
    return FinQAAdjudicationSummary(
        case_count=len(values),
        adjudication_eligible_case_count=len(eligible_latencies),
        baseline=baseline,
        proposal=proposal,
        adjudicated=adjudicated,
        source_review=source_review,
        status_counts={
            status: statuses[status] for status in status_names
        },
        transition_counts={
            transition: transitions[transition]
            for transition in transition_names
        },
        discordant_case_count=discordant,
        mcnemar_exact_p_value=_exact_mcnemar_p_value(
            correct_to_wrong=transitions["correct_to_wrong"],
            wrong_to_correct=transitions["wrong_to_correct"],
        ),
        incremental_adjudication_generation_calls=sum(
            row.adjudication_generation_calls for row in values
        ),
        incremental_adjudication_calculator_calls=sum(
            row.adjudication_calculator_calls for row in values
        ),
        adjudication_latency_ms_mean_eligible=(
            sum(eligible_latencies) / len(eligible_latencies)
            if eligible_latencies
            else 0
        ),
        adjudication_latency_ms_p95_eligible=(
            eligible_latencies[p95_index] if eligible_latencies else 0
        ),
        execution_accuracy_delta=(
            adjudicated.execution_accuracy - baseline.execution_accuracy
        ),
        grounded_execution_accuracy_delta=(
            adjudicated.grounded_execution_accuracy
            - baseline.grounded_execution_accuracy
        ),
        citation_recall_delta=(
            adjudicated.citation_recall - baseline.citation_recall
        ),
        generation_call_multiplier=(
            adjudicated.generation_calls / baseline.generation_calls
        ),
        calculator_call_multiplier=calculator_multiplier,
        latency_mean_multiplier=(
            adjudicated.latency_ms_mean / baseline.latency_ms_mean
        ),
    )


def publish_finqa_adjudication_run(
    *,
    root: Path,
    manifest: FinQAAdjudicationRunManifest,
    details: Sequence[FinQAAdjudicationCaseEvaluation],
) -> Path:
    rows = list(details)
    if manifest.artifacts:
        raise ValueError("FinQA adjudication artifacts assigned at publication")
    if summarize_finqa_adjudication_cases(
        rows,
        source_review=manifest.summary.source_review,
    ) != manifest.summary:
        raise ValueError("FinQA adjudication summary does not match details")
    if len(rows) != manifest.selected_case_count:
        raise ValueError("FinQA adjudication detail count does not match manifest")
    _validate_case_ids(rows, manifest.selected_case_ids_sha256)
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    final = root / manifest.adjudication_run_id
    if final.exists():
        raise FileExistsError(
            f"FinQA adjudication run already exists: "
            f"{manifest.adjudication_run_id}"
        )
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{manifest.adjudication_run_id}.staging-",
            dir=root,
        )
    )
    try:
        artifact_bytes = {
            "details.jsonl": b"".join(
                _canonical_json_bytes(row.model_dump(mode="json"))
                for row in rows
            ),
            "summary.json": _canonical_json_bytes(
                manifest.summary.model_dump(mode="json")
            ),
        }
        artifacts = {
            name: hashlib.sha256(content).hexdigest()
            for name, content in artifact_bytes.items()
        }
        final_manifest = manifest.model_copy(
            update={"artifacts": artifacts}
        )
        for name, content in artifact_bytes.items():
            (staging / name).write_bytes(content)
        (staging / "manifest.json").write_bytes(
            _canonical_json_bytes(final_manifest.model_dump(mode="json"))
        )
        verify_finqa_adjudication_run(staging)
        atomic_directory_move(staging, final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    verify_finqa_adjudication_run(final)
    return final


def verify_finqa_adjudication_run(
    run_dir: Path,
) -> FinQAAdjudicationRunManifest:
    run_dir = Path(run_dir).resolve()
    expected_files = {*_ADJUDICATION_ARTIFACTS, "manifest.json"}
    actual_files = {
        child.name for child in run_dir.iterdir() if child.is_file()
    }
    if actual_files != expected_files:
        raise ValueError("FinQA adjudication artifact set is unexpected")
    manifest = FinQAAdjudicationRunManifest.model_validate_json(
        (run_dir / "manifest.json").read_bytes()
    )
    if (
        manifest.adjudication_run_id != run_dir.name
        and ".staging-" not in run_dir.name
    ):
        raise ValueError("FinQA adjudication directory does not match manifest")
    for name, expected_sha256 in manifest.artifacts.items():
        actual_sha256 = hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(f"FinQA adjudication artifact mismatch: {name}")
    details = [
        FinQAAdjudicationCaseEvaluation.model_validate(
            json.loads(line, object_pairs_hook=_unique_object)
        )
        for line in (run_dir / "details.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    if len(details) != manifest.selected_case_count:
        raise ValueError("FinQA adjudication detail count mismatch")
    _validate_case_ids(details, manifest.selected_case_ids_sha256)
    summary = FinQAAdjudicationSummary.model_validate_json(
        (run_dir / "summary.json").read_bytes()
    )
    if summary != manifest.summary:
        raise ValueError("FinQA adjudication manifest summary mismatch")
    if summarize_finqa_adjudication_cases(
        details,
        source_review=summary.source_review,
    ) != summary:
        raise ValueError("FinQA adjudication summary cannot be reproduced")
    return manifest


def _execute_and_verify(evaluation: FinQACaseEvaluation) -> Decimal:
    if evaluation.answer_status != "ok" or not evaluation.calculation:
        raise ValueError("FinQA adjudication candidate is not executable")
    result = execute_decimal_expression(evaluation.calculation)
    if format(result, "f") != evaluation.final_answer:
        raise ValueError("FinQA adjudication candidate result mismatch")
    return result


def _candidate_payload(
    evaluation: FinQACaseEvaluation,
    value: Decimal,
    by_unit_id: dict[str, str],
) -> dict[str, Any]:
    return {
        "expression": evaluation.calculation,
        "calculator_result": format(value, "f"),
        "cited_candidate_ids": [
            by_unit_id[unit_id] for unit_id in evaluation.cited_unit_ids
        ],
    }


def _baseline_is_candidate_a(case_id: str) -> bool:
    digest = hashlib.sha256(
        f"{FINQA_ADJUDICATION_PROMPT_VERSION}|{case_id}".encode("utf-8")
    ).digest()
    return digest[0] % 2 == 0


def _build_adjudication_messages(
    *,
    question: str,
    candidate_ids: Sequence[str],
    units: Sequence[FinQAEvidenceUnit],
    candidate_sources: dict[str, FinQACandidateSource],
    candidates: dict[FinQACandidateSource, dict[str, Any]],
) -> list[dict[str, str]]:
    evidence = [
        {
            "candidate_id": candidate_id,
            "kind": unit.kind,
            "text": unit.text[:MAX_FINQA_UNIT_CHARS],
        }
        for candidate_id, unit in zip(candidate_ids, units, strict=True)
    ]
    labelled_candidates = {
        label: candidates[source]
        for label, source in candidate_sources.items()
    }
    system_prompt = (
        "You adjudicate two anonymous numerical candidates over untrusted "
        "financial evidence. Select one candidate; never create a third expression. "
        "Check the exact quantity, years, categories, operands, old/base value, "
        "operation, sign, and scale. The scorer requires raw ratios: 5.4 percent is "
        "0.054, not 5.4. For percentage change use signed new-minus-old divided by "
        "old; for part-of-total questions divide the requested part by the total. "
        "Prefer the candidate directly supported by the supplied evidence. Candidate "
        "order is randomized and does not indicate source or quality. Return only "
        "JSON with selected_candidate."
    )
    user_prompt = json.dumps(
        {
            "question": question,
            "evidence": evidence,
            "candidates": labelled_candidates,
            "output_contract": {
                "selected_candidate": "candidate-a or candidate-b"
            },
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _adjudication_response_format() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "selected_candidate": {
                "type": "string",
                "enum": ["candidate-a", "candidate-b"],
            }
        },
        "required": ["selected_candidate"],
        "additionalProperties": False,
    }


def _correctness_transition(
    before: bool,
    after: bool,
) -> FinQACorrectnessTransition:
    if before and after:
        return "correct_to_correct"
    if before and not after:
        return "correct_to_wrong"
    if not before and after:
        return "wrong_to_correct"
    return "wrong_to_wrong"


def _exact_mcnemar_p_value(
    *,
    correct_to_wrong: int,
    wrong_to_correct: int,
) -> float:
    discordant = correct_to_wrong + wrong_to_correct
    if discordant == 0:
        return 1.0
    smaller = min(correct_to_wrong, wrong_to_correct)
    lower_tail = sum(
        math.comb(discordant, index)
        for index in range(smaller + 1)
    ) / (2**discordant)
    return min(1.0, 2 * lower_tail)


def _validate_case_ids(
    rows: Sequence[FinQAAdjudicationCaseEvaluation],
    expected_sha256: str,
) -> None:
    case_ids = [row.case_id for row in rows]
    if not case_ids or len(case_ids) != len(set(case_ids)):
        raise ValueError("FinQA adjudication case IDs must be unique")
    actual = hashlib.sha256(
        ("\n".join(case_ids) + "\n").encode("utf-8")
    ).hexdigest()
    if actual != expected_sha256:
        raise ValueError("FinQA adjudication case order hash mismatch")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


__all__ = [
    "FINQA_ADJUDICATION_PROMPT_VERSION",
    "FinQAAdjudicationCaseEvaluation",
    "FinQAAdjudicationResult",
    "FinQAAdjudicationRunManifest",
    "FinQAAdjudicationStatus",
    "FinQAAdjudicationSummary",
    "LocalFinQACandidateAdjudicator",
    "evaluate_finqa_adjudication_case",
    "preserve_unadjudicated_finqa_case",
    "publish_finqa_adjudication_run",
    "summarize_finqa_adjudication_cases",
    "verify_finqa_adjudication_run",
]
