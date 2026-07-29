from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.external_datasets.finqa import (
    FinQACase,
    build_finqa_evidence_units,
)
from app.external_datasets.finqa_adjudication import (
    FinQAAdjudicationCaseEvaluation,
)
from app.external_datasets.finqa_diagnostics import (
    analyze_finqa_expression,
)
from app.external_datasets.finqa_eval import FinQACaseEvaluation
from app.filesystem import atomic_directory_move


FINQA_UNCERTAINTY_ALGORITHM_VERSION = "finqa_runtime_uncertainty_v1"
FINQA_UNCERTAINTY_TRIGGER_THRESHOLD = 2
_UNCERTAINTY_ARTIFACTS = {"details.jsonl", "summary.json"}

FinQAUncertaintyReason = Literal[
    "ungrounded_operand",
    "planner_retry",
    "quarantined_content",
    "multi_operation",
    "many_numbers",
    "multiple_citations",
    "multi_year",
    "ratio_division",
]

_NUMBER_PATTERN = re.compile(
    r"(?<![\w.])(\(?\s*-?\s*\$?\s*\d[\d,]*(?:\.\d+)?\s*%?\s*\)?)"
)
_YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
_RATIO_PATTERN = re.compile(
    r"\b(percent|percentage|ratio|rate|growth|change|margin|fraction)\b",
    re.IGNORECASE,
)
_OFFICIAL_CONSTANTS = {
    Decimal("-1"),
    Decimal("1"),
    Decimal("2"),
    Decimal("3"),
    Decimal("4"),
    Decimal("5"),
    Decimal("7"),
    Decimal("8"),
    Decimal("9"),
    Decimal("10"),
    Decimal("100"),
    Decimal("1000"),
    Decimal("1000000"),
}
_REASON_WEIGHTS: tuple[tuple[FinQAUncertaintyReason, int], ...] = (
    ("ungrounded_operand", 3),
    ("planner_retry", 2),
    ("quarantined_content", 3),
    ("multi_operation", 1),
    ("many_numbers", 1),
    ("multiple_citations", 1),
    ("multi_year", 1),
    ("ratio_division", 1),
)


class FinQARuntimeUncertainty(BaseModel):
    model_config = ConfigDict(extra="forbid")

    algorithm_version: Literal["finqa_runtime_uncertainty_v1"] = (
        FINQA_UNCERTAINTY_ALGORITHM_VERSION
    )
    case_id: str = Field(min_length=1)
    eligible_for_plan_review: bool
    triggered: bool
    score: int = Field(ge=0)
    threshold: Literal[2] = FINQA_UNCERTAINTY_TRIGGER_THRESHOLD
    reason_codes: list[FinQAUncertaintyReason]
    operand_grounding_rate: float | None = Field(default=None, ge=0, le=1)
    operation_count: int = Field(ge=0)
    numeric_operand_count: int = Field(ge=0)
    cited_evidence_number_count: int = Field(ge=0)
    cited_unit_count: int = Field(ge=0)
    selected_unit_count: int = Field(ge=0)
    distinct_year_count: int = Field(ge=0)
    planner_generation_calls: int = Field(ge=0)
    quarantined_unit_count: int = Field(ge=0)


class FinQAUncertaintyCaseEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    signal: FinQARuntimeUncertainty
    baseline: FinQACaseEvaluation
    full_strategy: FinQACaseEvaluation
    gated: FinQACaseEvaluation
    selected_source: Literal["baseline", "adjudicated"]
    gated_correctness_transition: Literal[
        "wrong_to_wrong",
        "wrong_to_correct",
        "correct_to_wrong",
        "correct_to_correct",
    ]
    full_strategy_correctness_transition: Literal[
        "wrong_to_wrong",
        "wrong_to_correct",
        "correct_to_wrong",
        "correct_to_correct",
    ]
    incremental_review_generation_calls: int = Field(ge=0)
    incremental_adjudication_generation_calls: int = Field(ge=0)
    incremental_review_calculator_calls: int = Field(ge=0)
    incremental_adjudication_calculator_calls: int = Field(ge=0)
    incremental_latency_ms: float = Field(ge=0)


class FinQAUncertaintySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_count: int = Field(ge=1)
    eligible_case_count: int = Field(ge=0)
    triggered_case_count: int = Field(ge=0)
    trigger_rate: float = Field(ge=0, le=1)
    reason_counts: dict[FinQAUncertaintyReason, int]
    baseline_execution_accuracy: float = Field(ge=0, le=1)
    full_strategy_execution_accuracy: float = Field(ge=0, le=1)
    gated_execution_accuracy: float = Field(ge=0, le=1)
    baseline_grounded_execution_accuracy: float = Field(ge=0, le=1)
    full_strategy_grounded_execution_accuracy: float = Field(ge=0, le=1)
    gated_grounded_execution_accuracy: float = Field(ge=0, le=1)
    full_strategy_wrong_to_correct: int = Field(ge=0)
    full_strategy_correct_to_wrong: int = Field(ge=0)
    gated_wrong_to_correct: int = Field(ge=0)
    gated_correct_to_wrong: int = Field(ge=0)
    gated_mcnemar_exact_p_value: float = Field(ge=0, le=1)
    beneficial_case_capture_rate: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    incremental_generation_calls: int = Field(ge=0)
    full_strategy_incremental_generation_calls: int = Field(ge=0)
    generation_call_reduction: float = Field(ge=0, le=1)
    incremental_calculator_calls: int = Field(ge=0)
    full_strategy_incremental_calculator_calls: int = Field(ge=0)
    calculator_call_reduction: float = Field(ge=0, le=1)
    incremental_latency_ms_total: float = Field(ge=0)
    full_strategy_incremental_latency_ms_total: float = Field(ge=0)
    incremental_latency_reduction: float = Field(ge=0, le=1)


class FinQAUncertaintyRunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["finqa_uncertainty_run_v1"] = (
        "finqa_uncertainty_run_v1"
    )
    uncertainty_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$"
    )
    algorithm_version: Literal["finqa_runtime_uncertainty_v1"] = (
        FINQA_UNCERTAINTY_ALGORITHM_VERSION
    )
    trigger_threshold: Literal[2] = FINQA_UNCERTAINTY_TRIGGER_THRESHOLD
    source_adjudication_run_id: str = Field(min_length=1, max_length=200)
    source_adjudication_manifest_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    source_adjudication_details_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    dataset_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    split: Literal["dev"]
    split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_case_count: int = Field(ge=1)
    retrieval_mode: Literal["oracle", "bm25", "dense", "hybrid"]
    source_adjudication_code_revision: str = Field(
        pattern=r"^[0-9a-f]{40}$"
    )
    uncertainty_code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    summary: FinQAUncertaintySummary
    artifacts: dict[str, str] = Field(default_factory=dict)

    @field_validator("artifacts")
    @classmethod
    def validate_artifacts(cls, value: dict[str, str]) -> dict[str, str]:
        if value and (
            set(value) != _UNCERTAINTY_ARTIFACTS
            or any(
                re.fullmatch(r"[0-9a-f]{64}", digest) is None
                for digest in value.values()
            )
        ):
            raise ValueError("FinQA uncertainty artifact set is invalid")
        return value


def assess_finqa_runtime_uncertainty(
    case: FinQACase,
    evaluation: FinQACaseEvaluation,
) -> FinQARuntimeUncertainty:
    if case.id != evaluation.case_id:
        raise ValueError("FinQA uncertainty case IDs do not match")
    eligible = (
        evaluation.answer_status == "ok"
        and evaluation.answer_parseable
        and bool(evaluation.calculation)
    )
    if not eligible:
        return FinQARuntimeUncertainty(
            case_id=case.id,
            eligible_for_plan_review=False,
            triggered=False,
            score=0,
            reason_codes=[],
            operand_grounding_rate=None,
            operation_count=0,
            numeric_operand_count=0,
            cited_evidence_number_count=0,
            cited_unit_count=len(evaluation.cited_unit_ids),
            selected_unit_count=len(evaluation.selected_unit_ids),
            distinct_year_count=0,
            planner_generation_calls=evaluation.generation_calls,
            quarantined_unit_count=evaluation.quarantined_count,
        )

    selected_ids = set(evaluation.selected_unit_ids)
    if not set(evaluation.cited_unit_ids).issubset(selected_ids):
        raise ValueError(
            "FinQA uncertainty citations are outside selected evidence"
        )
    units_by_id = {
        unit.unit_id: unit.text for unit in build_finqa_evidence_units(case)
    }
    missing_ids = set(evaluation.cited_unit_ids) - set(units_by_id)
    if missing_ids:
        raise ValueError("FinQA uncertainty cited evidence is unavailable")
    cited_text = " ".join(
        units_by_id[unit_id] for unit_id in evaluation.cited_unit_ids
    )
    evidence_numbers = _extract_evidence_numbers(cited_text)
    expression = analyze_finqa_expression(evaluation.calculation)
    grounded_count = sum(
        operand in evidence_numbers or operand in _OFFICIAL_CONSTANTS
        for operand in expression.numeric_operands
    )
    grounding_rate = (
        grounded_count / len(expression.numeric_operands)
        if expression.numeric_operands
        else 0.0
    )
    distinct_years = set(_YEAR_PATTERN.findall(cited_text))
    enabled = {
        "ungrounded_operand": grounding_rate < 1.0,
        "planner_retry": evaluation.generation_calls >= 2,
        "quarantined_content": evaluation.quarantined_count > 0,
        "multi_operation": len(expression.operations) >= 2,
        "many_numbers": len(evidence_numbers) >= 12,
        "multiple_citations": len(evaluation.cited_unit_ids) >= 2,
        "multi_year": len(distinct_years) >= 3,
        "ratio_division": (
            bool(_RATIO_PATTERN.search(case.qa.question))
            and "divide" in expression.operations
        ),
    }
    reasons = [
        reason for reason, _ in _REASON_WEIGHTS if enabled[reason]
    ]
    score = sum(
        weight for reason, weight in _REASON_WEIGHTS if enabled[reason]
    )
    return FinQARuntimeUncertainty(
        case_id=case.id,
        eligible_for_plan_review=True,
        triggered=score >= FINQA_UNCERTAINTY_TRIGGER_THRESHOLD,
        score=score,
        reason_codes=reasons,
        operand_grounding_rate=grounding_rate,
        operation_count=len(expression.operations),
        numeric_operand_count=len(expression.numeric_operands),
        cited_evidence_number_count=len(evidence_numbers),
        cited_unit_count=len(evaluation.cited_unit_ids),
        selected_unit_count=len(evaluation.selected_unit_ids),
        distinct_year_count=len(distinct_years),
        planner_generation_calls=evaluation.generation_calls,
        quarantined_unit_count=evaluation.quarantined_count,
    )


def evaluate_finqa_uncertainty_case(
    adjudication: FinQAAdjudicationCaseEvaluation,
    signal: FinQARuntimeUncertainty,
) -> FinQAUncertaintyCaseEvaluation:
    if adjudication.case_id != signal.case_id:
        raise ValueError("FinQA uncertainty signal case ID mismatch")
    if signal.triggered and not signal.eligible_for_plan_review:
        raise ValueError("ineligible FinQA case cannot trigger plan review")

    baseline = adjudication.baseline
    full_strategy = adjudication.adjudicated
    selected_source: Literal["baseline", "adjudicated"] = (
        "adjudicated" if signal.triggered else "baseline"
    )
    gated = full_strategy if signal.triggered else baseline
    if signal.triggered:
        review_generation_calls = (
            adjudication.proposal.generation_calls
            - baseline.generation_calls
        )
        review_calculator_calls = (
            (adjudication.proposal.calculator_calls or 0)
            - (baseline.calculator_calls or 0)
        )
        adjudication_generation_calls = (
            adjudication.adjudication_generation_calls
        )
        adjudication_calculator_calls = (
            adjudication.adjudication_calculator_calls
        )
        incremental_latency_ms = (
            full_strategy.latency_ms - baseline.latency_ms
        )
    else:
        review_generation_calls = 0
        review_calculator_calls = 0
        adjudication_generation_calls = 0
        adjudication_calculator_calls = 0
        incremental_latency_ms = 0.0
    if (
        review_generation_calls < 0
        or review_calculator_calls < 0
        or incremental_latency_ms < -1e-6
    ):
        raise ValueError("FinQA uncertainty source cost is invalid")

    return FinQAUncertaintyCaseEvaluation(
        case_id=adjudication.case_id,
        signal=signal,
        baseline=baseline,
        full_strategy=full_strategy,
        gated=gated,
        selected_source=selected_source,
        gated_correctness_transition=_correctness_transition(
            baseline.strict_execution_match,
            gated.strict_execution_match,
        ),
        full_strategy_correctness_transition=_correctness_transition(
            baseline.strict_execution_match,
            full_strategy.strict_execution_match,
        ),
        incremental_review_generation_calls=review_generation_calls,
        incremental_adjudication_generation_calls=(
            adjudication_generation_calls
        ),
        incremental_review_calculator_calls=review_calculator_calls,
        incremental_adjudication_calculator_calls=(
            adjudication_calculator_calls
        ),
        incremental_latency_ms=max(0.0, incremental_latency_ms),
    )


def summarize_finqa_uncertainty_cases(
    rows: Sequence[FinQAUncertaintyCaseEvaluation],
) -> FinQAUncertaintySummary:
    if not rows:
        raise ValueError("FinQA uncertainty summary requires cases")
    if len({row.case_id for row in rows}) != len(rows):
        raise ValueError("FinQA uncertainty case IDs must be unique")

    count = len(rows)
    triggered = [row for row in rows if row.signal.triggered]
    full_w2c = sum(
        row.full_strategy_correctness_transition == "wrong_to_correct"
        for row in rows
    )
    full_c2w = sum(
        row.full_strategy_correctness_transition == "correct_to_wrong"
        for row in rows
    )
    gated_w2c = sum(
        row.gated_correctness_transition == "wrong_to_correct"
        for row in rows
    )
    gated_c2w = sum(
        row.gated_correctness_transition == "correct_to_wrong"
        for row in rows
    )
    gated_generation_calls = sum(
        row.incremental_review_generation_calls
        + row.incremental_adjudication_generation_calls
        for row in rows
    )
    full_generation_calls = sum(
        row.full_strategy.generation_calls - row.baseline.generation_calls
        for row in rows
    )
    gated_calculator_calls = sum(
        row.incremental_review_calculator_calls
        + row.incremental_adjudication_calculator_calls
        for row in rows
    )
    full_calculator_calls = sum(
        (row.full_strategy.calculator_calls or 0)
        - (row.baseline.calculator_calls or 0)
        for row in rows
    )
    gated_latency = sum(row.incremental_latency_ms for row in rows)
    full_latency = sum(
        row.full_strategy.latency_ms - row.baseline.latency_ms
        for row in rows
    )
    reason_counts = Counter(
        reason
        for row in rows
        for reason in row.signal.reason_codes
        if row.signal.triggered
    )
    return FinQAUncertaintySummary(
        case_count=count,
        eligible_case_count=sum(
            row.signal.eligible_for_plan_review for row in rows
        ),
        triggered_case_count=len(triggered),
        trigger_rate=len(triggered) / count,
        reason_counts=dict(sorted(reason_counts.items())),
        baseline_execution_accuracy=sum(
            row.baseline.strict_execution_match for row in rows
        )
        / count,
        full_strategy_execution_accuracy=sum(
            row.full_strategy.strict_execution_match for row in rows
        )
        / count,
        gated_execution_accuracy=sum(
            row.gated.strict_execution_match for row in rows
        )
        / count,
        baseline_grounded_execution_accuracy=sum(
            row.baseline.grounded_execution_match for row in rows
        )
        / count,
        full_strategy_grounded_execution_accuracy=sum(
            row.full_strategy.grounded_execution_match for row in rows
        )
        / count,
        gated_grounded_execution_accuracy=sum(
            row.gated.grounded_execution_match for row in rows
        )
        / count,
        full_strategy_wrong_to_correct=full_w2c,
        full_strategy_correct_to_wrong=full_c2w,
        gated_wrong_to_correct=gated_w2c,
        gated_correct_to_wrong=gated_c2w,
        gated_mcnemar_exact_p_value=_exact_mcnemar_p_value(
            gated_w2c,
            gated_c2w,
        ),
        beneficial_case_capture_rate=(
            gated_w2c / full_w2c if full_w2c else None
        ),
        incremental_generation_calls=gated_generation_calls,
        full_strategy_incremental_generation_calls=full_generation_calls,
        generation_call_reduction=_reduction(
            gated_generation_calls,
            full_generation_calls,
        ),
        incremental_calculator_calls=gated_calculator_calls,
        full_strategy_incremental_calculator_calls=full_calculator_calls,
        calculator_call_reduction=_reduction(
            gated_calculator_calls,
            full_calculator_calls,
        ),
        incremental_latency_ms_total=gated_latency,
        full_strategy_incremental_latency_ms_total=full_latency,
        incremental_latency_reduction=_reduction(
            gated_latency,
            full_latency,
        ),
    )


def publish_finqa_uncertainty_run(
    *,
    root: Path,
    manifest: FinQAUncertaintyRunManifest,
    details: Sequence[FinQAUncertaintyCaseEvaluation],
) -> Path:
    rows = list(details)
    if manifest.artifacts:
        raise ValueError(
            "FinQA uncertainty artifacts are assigned during publication"
        )
    _validate_run_rows(rows, manifest)
    if summarize_finqa_uncertainty_cases(rows) != manifest.summary:
        raise ValueError("FinQA uncertainty summary does not match details")

    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    final = root / manifest.uncertainty_run_id
    if final.exists():
        raise FileExistsError(
            "FinQA uncertainty run already exists: "
            f"{manifest.uncertainty_run_id}"
        )
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{manifest.uncertainty_run_id}.staging-",
            dir=root,
        )
    )
    try:
        details_bytes = b"".join(
            _canonical_json_bytes(row.model_dump(mode="json"))
            for row in rows
        )
        summary_bytes = _canonical_json_bytes(
            manifest.summary.model_dump(mode="json")
        )
        artifact_bytes = {
            "details.jsonl": details_bytes,
            "summary.json": summary_bytes,
        }
        artifacts = {
            name: hashlib.sha256(content).hexdigest()
            for name, content in artifact_bytes.items()
        }
        final_manifest = manifest.model_copy(update={"artifacts": artifacts})
        for name, content in artifact_bytes.items():
            (staging / name).write_bytes(content)
        (staging / "manifest.json").write_bytes(
            _canonical_json_bytes(final_manifest.model_dump(mode="json"))
        )
        verify_finqa_uncertainty_run(staging)
        atomic_directory_move(staging, final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    verify_finqa_uncertainty_run(final)
    return final


def verify_finqa_uncertainty_run(
    run_dir: Path,
) -> FinQAUncertaintyRunManifest:
    run_dir = Path(run_dir).resolve()
    expected_files = {*_UNCERTAINTY_ARTIFACTS, "manifest.json"}
    actual_files = {
        child.name for child in run_dir.iterdir() if child.is_file()
    }
    if actual_files != expected_files:
        raise ValueError(
            "FinQA uncertainty run has an unexpected artifact set"
        )
    manifest = FinQAUncertaintyRunManifest.model_validate_json(
        (run_dir / "manifest.json").read_bytes()
    )
    if (
        manifest.uncertainty_run_id != run_dir.name
        and ".staging-" not in run_dir.name
    ):
        raise ValueError(
            "FinQA uncertainty directory does not match manifest ID"
        )
    for name, expected_sha256 in manifest.artifacts.items():
        actual_sha256 = hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"FinQA uncertainty artifact mismatch: {name}"
            )
    details = [
        FinQAUncertaintyCaseEvaluation.model_validate(
            json.loads(line, object_pairs_hook=_unique_object)
        )
        for line in (run_dir / "details.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    _validate_run_rows(details, manifest)
    summary = FinQAUncertaintySummary.model_validate_json(
        (run_dir / "summary.json").read_bytes()
    )
    if summary != manifest.summary:
        raise ValueError(
            "FinQA uncertainty manifest summary does not match"
        )
    if summarize_finqa_uncertainty_cases(details) != summary:
        raise ValueError("FinQA uncertainty summary cannot be reproduced")
    return manifest


def _extract_evidence_numbers(source: str) -> set[Decimal]:
    values: set[Decimal] = set()
    for match in _NUMBER_PATTERN.finditer(source):
        token = re.sub(r"[\s$,()%]", "", match.group(1))
        if not token:
            continue
        negative = match.group(1).strip().startswith("(")
        value = Decimal(token)
        values.add(-value if negative and value > 0 else value)
    return values


def _correctness_transition(
    before: bool,
    after: bool,
) -> Literal[
    "wrong_to_wrong",
    "wrong_to_correct",
    "correct_to_wrong",
    "correct_to_correct",
]:
    if before:
        return "correct_to_correct" if after else "correct_to_wrong"
    return "wrong_to_correct" if after else "wrong_to_wrong"


def _exact_mcnemar_p_value(
    wrong_to_correct: int,
    correct_to_wrong: int,
) -> float:
    discordant = wrong_to_correct + correct_to_wrong
    if discordant == 0:
        return 1.0
    smaller = min(wrong_to_correct, correct_to_wrong)
    lower_tail = sum(
        Decimal(_binomial(discordant, k))
        for k in range(smaller + 1)
    ) / (Decimal(2) ** discordant)
    return float(min(Decimal(1), Decimal(2) * lower_tail))


def _binomial(n: int, k: int) -> int:
    if k < 0 or k > n:
        return 0
    result = 1
    for index in range(1, min(k, n - k) + 1):
        result = result * (n - index + 1) // index
    return result


def _reduction(selected: float, full: float) -> float:
    if full <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - selected / full))


def _validate_run_rows(
    rows: Sequence[FinQAUncertaintyCaseEvaluation],
    manifest: FinQAUncertaintyRunManifest,
) -> None:
    if len(rows) != manifest.selected_case_count:
        raise ValueError("FinQA uncertainty case count mismatch")
    case_ids = [row.case_id for row in rows]
    if (
        not case_ids
        or len(case_ids) != len(set(case_ids))
        or _case_ids_sha256(case_ids) != manifest.selected_case_ids_sha256
    ):
        raise ValueError("FinQA uncertainty selected case hash mismatch")
    if any(
        row.baseline.retrieval_mode != manifest.retrieval_mode
        for row in rows
    ):
        raise ValueError("FinQA uncertainty retrieval mode mismatch")


def _case_ids_sha256(case_ids: Sequence[str]) -> str:
    return hashlib.sha256(
        ("\n".join(case_ids) + "\n").encode("utf-8")
    ).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _canonical_json_bytes(value: object) -> bytes:
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
    "FINQA_UNCERTAINTY_ALGORITHM_VERSION",
    "FINQA_UNCERTAINTY_TRIGGER_THRESHOLD",
    "FinQARuntimeUncertainty",
    "FinQAUncertaintyCaseEvaluation",
    "FinQAUncertaintyReason",
    "FinQAUncertaintyRunManifest",
    "FinQAUncertaintySummary",
    "assess_finqa_runtime_uncertainty",
    "evaluate_finqa_uncertainty_case",
    "publish_finqa_uncertainty_run",
    "summarize_finqa_uncertainty_cases",
    "verify_finqa_uncertainty_run",
]
