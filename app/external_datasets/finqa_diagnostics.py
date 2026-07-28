from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agent.safe_calculator import execute_decimal_expression
from app.evaluation.numeric_answer import (
    normalize_direct_answer,
    presentation_tolerance_match,
)
from app.external_datasets.finqa import (
    FinQACase,
    build_finqa_evidence_units,
)
from app.external_datasets.finqa_eval import (
    FinQACaseEvaluation,
    FinQARetrievalMode,
    FinQARunManifest,
    verify_finqa_run,
)
from app.filesystem import atomic_directory_move


FinQADiagnosticCategory = Literal[
    "correct_grounded",
    "correct_citation_incomplete",
    "retrieval_miss",
    "generation_protocol_error",
    "unsupported_gold_operation",
    "operand_selection_signal",
    "operation_plan_signal",
    "composition_or_scale_signal",
]
FinQADiagnosticConfidence = Literal["high", "medium", "limited"]

DIAGNOSTIC_ALGORITHM_VERSION = "finqa_dev_diagnostic_v1"
_DIAGNOSTIC_ARTIFACTS = {"details.jsonl", "summary.json"}
_ARITHMETIC_OPERATIONS = {"add", "subtract", "multiply", "divide"}
_KNOWN_GOLD_OPERATIONS = {
    *_ARITHMETIC_OPERATIONS,
    "exp",
    "greater",
    "table_average",
    "table_max",
    "table_min",
    "table_sum",
}
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
_GOLD_STEP = re.compile(r"([a-z_]+)\(([^()]*)\)(?:,\s*|$)")
_GOLD_NUMBER = re.compile(r"-?(?:\d+(?:\.\d*)?|\.\d+)%?")
_GOLD_CONSTANT = re.compile(r"const_(m)?(\d+)")
_STEP_REFERENCE = re.compile(r"#[0-9]+")
_EVIDENCE_NUMBER = re.compile(
    r"(?<![\w.])(\(?\s*-?\s*\$?\s*\d[\d,]*(?:\.\d+)?\s*%?\s*\)?)"
)
_MAX_GOLD_PROGRAM_CHARS = 2000
_MAX_GOLD_PROGRAM_STEPS = 16


@dataclass(frozen=True)
class FinQAGoldProgram:
    operations: tuple[str, ...]
    numeric_operands: tuple[Decimal, ...]
    unsupported_operations: tuple[str, ...]


@dataclass(frozen=True)
class FinQAExpressionAnalysis:
    operations: tuple[str, ...]
    numeric_operands: tuple[Decimal, ...]


class FinQADiagnosticRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    retrieval_mode: FinQARetrievalMode
    category: FinQADiagnosticCategory
    confidence: FinQADiagnosticConfidence
    strict_execution_match: bool
    evidence_recall: float = Field(ge=0, le=1)
    citation_recall: float = Field(ge=0, le=1)
    gold_operation_sequence: list[str]
    predicted_operation_sequence: list[str] | None
    unsupported_gold_operations: list[str]
    gold_operand_recall: float | None = Field(default=None, ge=0, le=1)
    expression_operand_grounding_rate: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    diagnostic_note: str = Field(min_length=1, max_length=500)


class FinQADiagnosticSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_count: int = Field(ge=1)
    source_execution_accuracy: float = Field(ge=0, le=1)
    source_evidence_recall: float = Field(ge=0, le=1)
    source_citation_recall: float = Field(ge=0, le=1)
    category_counts: dict[FinQADiagnosticCategory, int]
    category_rates: dict[FinQADiagnosticCategory, float]
    incorrect_case_count: int = Field(ge=0)
    gold_operand_recall_mean: float | None = Field(default=None, ge=0, le=1)
    expression_operand_grounding_rate_mean: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    classification_coverage: float = Field(ge=0, le=1)


class FinQALabelQualitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_count: int = Field(ge=1)
    reported_answer_parseable_count: int = Field(ge=0)
    reported_answer_parse_rate: float = Field(ge=0, le=1)
    reported_answer_unparseable_count: int = Field(ge=0)
    parseable_target_tolerance_disagreement_count: int = Field(ge=0)
    parseable_target_tolerance_disagreement_rate: float = Field(ge=0, le=1)


class FinQADiagnosticManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["finqa_diagnostic_run_v1"] = (
        "finqa_diagnostic_run_v1"
    )
    diagnostic_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$"
    )
    algorithm_version: Literal["finqa_dev_diagnostic_v1"] = (
        DIAGNOSTIC_ALGORITHM_VERSION
    )
    source_run_id: str = Field(min_length=1, max_length=200)
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    split: Literal["dev"]
    split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    diagnostic_code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    retrieval_mode: FinQARetrievalMode
    summary: FinQADiagnosticSummary
    artifacts: dict[str, str] = Field(default_factory=dict)

    @field_validator("artifacts")
    @classmethod
    def validate_artifacts(cls, value: dict[str, str]) -> dict[str, str]:
        if value and (
            set(value) != _DIAGNOSTIC_ARTIFACTS
            or any(
                re.fullmatch(r"[0-9a-f]{64}", digest) is None
                for digest in value.values()
            )
        ):
            raise ValueError("FinQA diagnostic artifact set is invalid")
        return value


def parse_finqa_gold_program(source: str) -> FinQAGoldProgram:
    text = source.strip()
    if not text or len(text) > _MAX_GOLD_PROGRAM_CHARS:
        raise ValueError("FinQA gold program is empty or exceeds its budget")
    operations: list[str] = []
    operands: list[Decimal] = []
    position = 0
    while position < len(text):
        match = _GOLD_STEP.match(text, position)
        if match is None:
            raise ValueError("FinQA gold program has unsupported syntax")
        operation = match.group(1)
        if operation not in _KNOWN_GOLD_OPERATIONS:
            raise ValueError(f"FinQA gold program uses unknown operation: {operation}")
        arguments = [item.strip() for item in match.group(2).split(",")]
        if len(arguments) != 2 or any(not item for item in arguments):
            raise ValueError("FinQA gold operation must have two arguments")
        operations.append(operation)
        if len(operations) > _MAX_GOLD_PROGRAM_STEPS:
            raise ValueError("FinQA gold program exceeds its step budget")
        for argument in arguments:
            numeric = _parse_gold_operand(argument)
            if numeric is not None:
                operands.append(numeric)
            elif (
                operation in _ARITHMETIC_OPERATIONS | {"exp", "greater"}
                and _STEP_REFERENCE.fullmatch(argument) is None
            ):
                raise ValueError(
                    "FinQA arithmetic gold program contains a non-numeric operand"
                )
        position = match.end()
    unsupported = tuple(
        operation
        for operation in operations
        if operation not in _ARITHMETIC_OPERATIONS
    )
    return FinQAGoldProgram(
        operations=tuple(operations),
        numeric_operands=tuple(operands),
        unsupported_operations=unsupported,
    )


def analyze_finqa_expression(source: str) -> FinQAExpressionAnalysis:
    execute_decimal_expression(source)
    tree = ast.parse(source.strip(), mode="eval")
    operations: list[str] = []
    operands: list[Decimal] = []
    _walk_expression(
        tree.body,
        source.strip(),
        operations=operations,
        operands=operands,
        unary_sign=1,
    )
    return FinQAExpressionAnalysis(
        operations=tuple(operations),
        numeric_operands=tuple(operands),
    )


def diagnose_finqa_case(
    case: FinQACase,
    evaluation: FinQACaseEvaluation,
) -> FinQADiagnosticRow:
    if case.id != evaluation.case_id:
        raise ValueError("FinQA diagnostic case ID does not match evaluation")
    gold = parse_finqa_gold_program(case.qa.program)
    expression = None
    if evaluation.calculation:
        expression = analyze_finqa_expression(evaluation.calculation)
    operand_recall = (
        _multiset_recall(gold.numeric_operands, expression.numeric_operands)
        if expression is not None and gold.numeric_operands
        else None
    )
    grounding_rate = (
        _expression_grounding_rate(case, evaluation, expression)
        if expression is not None and expression.numeric_operands
        else None
    )

    if evaluation.answer_status != "ok":
        category: FinQADiagnosticCategory = "generation_protocol_error"
        confidence: FinQADiagnosticConfidence = "high"
        note = "The answer contract exhausted its allowed generation attempts."
    elif evaluation.strict_execution_match:
        if evaluation.citation_recall == 1.0:
            category = "correct_grounded"
            confidence = "high"
            note = "The strict answer matched and every gold evidence unit was cited."
        else:
            category = "correct_citation_incomplete"
            confidence = "high"
            note = (
                "The strict answer matched, but citation recall was below one."
            )
    elif evaluation.evidence_recall < 1.0:
        category = "retrieval_miss"
        confidence = "high"
        note = (
            "At least one annotated gold evidence unit was absent from the "
            "retrieved context."
        )
    elif gold.unsupported_operations:
        category = "unsupported_gold_operation"
        confidence = "high"
        note = (
            "The official program requires an operation outside the current "
            "four-operation calculator contract."
        )
    elif operand_recall is not None and operand_recall < 1.0:
        category = "operand_selection_signal"
        confidence = "medium"
        note = (
            "The predicted expression does not contain every numeric operand "
            "from the official program; algebraic rewrites can be false positives."
        )
    elif expression is not None and expression.operations != gold.operations:
        category = "operation_plan_signal"
        confidence = "medium"
        note = (
            "The predicted arithmetic operation sequence differs from the "
            "official program; equivalent rewrites can be false positives."
        )
    else:
        category = "composition_or_scale_signal"
        confidence = "limited"
        note = (
            "Evidence, operand multiset, and operation sequence passed the "
            "mechanical checks, so argument order, grouping, scale, or another "
            "reason remains."
        )
    return FinQADiagnosticRow(
        case_id=case.id,
        retrieval_mode=evaluation.retrieval_mode,
        category=category,
        confidence=confidence,
        strict_execution_match=evaluation.strict_execution_match,
        evidence_recall=evaluation.evidence_recall,
        citation_recall=evaluation.citation_recall,
        gold_operation_sequence=list(gold.operations),
        predicted_operation_sequence=(
            list(expression.operations) if expression is not None else None
        ),
        unsupported_gold_operations=list(gold.unsupported_operations),
        gold_operand_recall=operand_recall,
        expression_operand_grounding_rate=grounding_rate,
        diagnostic_note=note,
    )


def summarize_finqa_diagnostics(
    rows: Sequence[FinQADiagnosticRow],
) -> FinQADiagnosticSummary:
    values = list(rows)
    if not values:
        raise ValueError("FinQA diagnostic summary requires at least one row")
    categories = [
        "correct_grounded",
        "correct_citation_incomplete",
        "retrieval_miss",
        "generation_protocol_error",
        "unsupported_gold_operation",
        "operand_selection_signal",
        "operation_plan_signal",
        "composition_or_scale_signal",
    ]
    counts = Counter(row.category for row in values)
    category_counts = {category: counts[category] for category in categories}
    count = len(values)
    operand_recalls = [
        row.gold_operand_recall
        for row in values
        if row.gold_operand_recall is not None
    ]
    grounding_rates = [
        row.expression_operand_grounding_rate
        for row in values
        if row.expression_operand_grounding_rate is not None
    ]
    return FinQADiagnosticSummary(
        case_count=count,
        source_execution_accuracy=(
            sum(row.strict_execution_match for row in values) / count
        ),
        source_evidence_recall=(
            sum(row.evidence_recall for row in values) / count
        ),
        source_citation_recall=(
            sum(row.citation_recall for row in values) / count
        ),
        category_counts=category_counts,
        category_rates={
            category: category_counts[category] / count
            for category in categories
        },
        incorrect_case_count=sum(
            not row.strict_execution_match for row in values
        ),
        gold_operand_recall_mean=(
            sum(operand_recalls) / len(operand_recalls)
            if operand_recalls
            else None
        ),
        expression_operand_grounding_rate_mean=(
            sum(grounding_rates) / len(grounding_rates)
            if grounding_rates
            else None
        ),
        classification_coverage=1.0,
    )


def summarize_finqa_label_quality(
    cases: Sequence[FinQACase],
) -> FinQALabelQualitySummary:
    values = list(cases)
    if not values:
        raise ValueError("FinQA label quality summary requires at least one case")
    parseable = []
    for case in values:
        try:
            normalize_direct_answer(case.qa.answer)
        except ValueError:
            continue
        parseable.append(case)
    disagreements = sum(
        not presentation_tolerance_match(case.qa.answer, case.qa.exe_ans)
        for case in parseable
    )
    count = len(values)
    parseable_count = len(parseable)
    return FinQALabelQualitySummary(
        case_count=count,
        reported_answer_parseable_count=parseable_count,
        reported_answer_parse_rate=parseable_count / count,
        reported_answer_unparseable_count=count - parseable_count,
        parseable_target_tolerance_disagreement_count=disagreements,
        parseable_target_tolerance_disagreement_rate=(
            disagreements / parseable_count if parseable_count else 0.0
        ),
    )


def load_verified_finqa_details(
    run_dir: Path,
) -> tuple[FinQARunManifest, list[FinQACaseEvaluation], str]:
    run_dir = Path(run_dir).resolve()
    manifest = verify_finqa_run(run_dir)
    details_bytes = (run_dir / "details.jsonl").read_bytes()
    details_sha256 = hashlib.sha256(details_bytes).hexdigest()
    if details_sha256 != manifest.artifacts["details.jsonl"]:
        raise ValueError("FinQA details changed after source run verification")
    details = [
        FinQACaseEvaluation.model_validate(
            json.loads(line, object_pairs_hook=_unique_object)
        )
        for line in details_bytes.decode("utf-8").splitlines()
        if line
    ]
    return manifest, details, details_sha256


def publish_finqa_diagnostic(
    *,
    root: Path,
    manifest: FinQADiagnosticManifest,
    details: Sequence[FinQADiagnosticRow],
) -> Path:
    rows = list(details)
    if manifest.artifacts:
        raise ValueError(
            "FinQA diagnostic artifacts are assigned during publication"
        )
    if summarize_finqa_diagnostics(rows) != manifest.summary:
        raise ValueError("FinQA diagnostic summary does not match details")
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    final = root / manifest.diagnostic_id
    if final.exists():
        raise FileExistsError(
            f"FinQA diagnostic already exists: {manifest.diagnostic_id}"
        )
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{manifest.diagnostic_id}.staging-",
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
        verify_finqa_diagnostic(staging)
        atomic_directory_move(staging, final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    verify_finqa_diagnostic(final)
    return final


def verify_finqa_diagnostic(run_dir: Path) -> FinQADiagnosticManifest:
    run_dir = Path(run_dir).resolve()
    expected_files = {*_DIAGNOSTIC_ARTIFACTS, "manifest.json"}
    actual_files = {
        child.name for child in run_dir.iterdir() if child.is_file()
    }
    if actual_files != expected_files:
        raise ValueError("FinQA diagnostic has an unexpected artifact set")
    manifest = FinQADiagnosticManifest.model_validate_json(
        (run_dir / "manifest.json").read_bytes()
    )
    if (
        manifest.diagnostic_id != run_dir.name
        and ".staging-" not in run_dir.name
    ):
        raise ValueError(
            "FinQA diagnostic directory does not match manifest ID"
        )
    for name, expected_sha256 in manifest.artifacts.items():
        actual_sha256 = hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(f"FinQA diagnostic artifact mismatch: {name}")
    details = [
        FinQADiagnosticRow.model_validate(
            json.loads(line, object_pairs_hook=_unique_object)
        )
        for line in (run_dir / "details.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    summary = FinQADiagnosticSummary.model_validate_json(
        (run_dir / "summary.json").read_bytes()
    )
    if summary != manifest.summary:
        raise ValueError("FinQA diagnostic manifest summary does not match")
    if summarize_finqa_diagnostics(details) != summary:
        raise ValueError("FinQA diagnostic summary cannot be reproduced")
    return manifest


def _parse_gold_operand(argument: str) -> Decimal | None:
    if _STEP_REFERENCE.fullmatch(argument) or argument == "none":
        return None
    constant = _GOLD_CONSTANT.fullmatch(argument)
    if constant is not None:
        sign = "-" if constant.group(1) else ""
        return Decimal(f"{sign}{constant.group(2)}")
    if _GOLD_NUMBER.fullmatch(argument):
        return Decimal(argument.removesuffix("%"))
    return None


def _walk_expression(
    node: ast.AST,
    source: str,
    *,
    operations: list[str],
    operands: list[Decimal],
    unary_sign: int,
) -> None:
    if isinstance(node, ast.Constant) and not isinstance(node.value, bool):
        literal = ast.get_source_segment(source, node)
        if literal is None:
            raise ValueError("FinQA expression literal is unavailable")
        operands.append(Decimal(literal) * unary_sign)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(
        node.op,
        (ast.UAdd, ast.USub),
    ):
        if isinstance(node.operand, ast.Constant):
            sign = -unary_sign if isinstance(node.op, ast.USub) else unary_sign
            _walk_expression(
                node.operand,
                source,
                operations=operations,
                operands=operands,
                unary_sign=sign,
            )
            return
        _walk_expression(
            node.operand,
            source,
            operations=operations,
            operands=operands,
            unary_sign=unary_sign,
        )
        if isinstance(node.op, ast.USub):
            operands.append(Decimal("-1"))
            operations.append("multiply")
        return
    if isinstance(node, ast.BinOp):
        _walk_expression(
            node.left,
            source,
            operations=operations,
            operands=operands,
            unary_sign=unary_sign,
        )
        _walk_expression(
            node.right,
            source,
            operations=operations,
            operands=operands,
            unary_sign=unary_sign,
        )
        operation = {
            ast.Add: "add",
            ast.Sub: "subtract",
            ast.Mult: "multiply",
            ast.Div: "divide",
        }.get(type(node.op))
        if operation is None:
            raise ValueError("FinQA expression uses an unsupported operation")
        operations.append(operation)
        return
    raise ValueError("FinQA expression contains an unsupported node")


def _multiset_recall(
    expected: Sequence[Decimal],
    actual: Sequence[Decimal],
) -> float:
    expected_counts = Counter(expected)
    actual_counts = Counter(actual)
    matched = sum(
        min(count, actual_counts[value])
        for value, count in expected_counts.items()
    )
    return matched / len(expected)


def _expression_grounding_rate(
    case: FinQACase,
    evaluation: FinQACaseEvaluation,
    expression: FinQAExpressionAnalysis,
) -> float:
    units = {
        unit.unit_id: unit.text for unit in build_finqa_evidence_units(case)
    }
    cited_text = " ".join(
        units[unit_id]
        for unit_id in evaluation.cited_unit_ids
        if unit_id in units
    )
    grounded_values = set(_extract_evidence_numbers(cited_text))
    grounded = sum(
        operand in grounded_values or operand in _OFFICIAL_CONSTANTS
        for operand in expression.numeric_operands
    )
    return grounded / len(expression.numeric_operands)


def _extract_evidence_numbers(source: str) -> tuple[Decimal, ...]:
    values: list[Decimal] = []
    for match in _EVIDENCE_NUMBER.finditer(source):
        token = re.sub(r"[\s$,()%]", "", match.group(1))
        if not token:
            continue
        negative = match.group(1).strip().startswith("(")
        value = Decimal(token)
        values.append(-value if negative and value > 0 else value)
    return tuple(values)


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
    "DIAGNOSTIC_ALGORITHM_VERSION",
    "FinQADiagnosticCategory",
    "FinQADiagnosticManifest",
    "FinQADiagnosticRow",
    "FinQADiagnosticSummary",
    "FinQAExpressionAnalysis",
    "FinQAGoldProgram",
    "FinQALabelQualitySummary",
    "analyze_finqa_expression",
    "diagnose_finqa_case",
    "load_verified_finqa_details",
    "parse_finqa_gold_program",
    "publish_finqa_diagnostic",
    "summarize_finqa_diagnostics",
    "summarize_finqa_label_quality",
    "verify_finqa_diagnostic",
]
