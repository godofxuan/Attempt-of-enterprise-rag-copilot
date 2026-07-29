from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.external_datasets.finqa_eval import FinQACaseEvaluation
from app.filesystem import atomic_directory_move


CLAIM_LABEL = "RETROSPECTIVE_DEVELOPMENT_ONLY"
PROTOCOL_SCHEMA_VERSION = "finqa_typed_retrospective_protocol_v1"
RUN_SCHEMA_VERSION = "finqa_typed_retrospective_run_v1"
PUBLIC_EVIDENCE_SCHEMA_VERSION = "finqa_typed_retrospective_public_v1"

ArmId = Literal["B0_FREE_LITERAL", "B1_TYPED_SINGLE", "B2_TYPED_MULTI"]
ArmStatus = Literal["ANSWERED", "REFUSED", "PROTOCOL_ERROR"]
DiagnosticCategory = Literal[
    "composition_or_scale_signal",
    "correct_citation_incomplete",
    "correct_grounded",
    "generation_protocol_error",
    "operand_selection_signal",
    "operation_plan_signal",
    "retrieval_miss",
    "unsupported_gold_operation",
]

_ARMS: tuple[ArmId, ...] = (
    "B0_FREE_LITERAL",
    "B1_TYPED_SINGLE",
    "B2_TYPED_MULTI",
)
_RUN_ARTIFACTS = {"details.jsonl", "summary.json"}
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FrozenModelIdentity(_StrictModel):
    name: str = Field(min_length=1, max_length=200)
    sha256: str = Field(pattern=_SHA256_PATTERN)


class FrozenSourceRun(_StrictModel):
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    details_sha256: str = Field(pattern=_SHA256_PATTERN)


class FrozenDiagnosticRun(FrozenSourceRun):
    pass


class FinQATypedRetrospectiveProtocol(_StrictModel):
    schema_version: Literal[
        "finqa_typed_retrospective_protocol_v1"
    ] = PROTOCOL_SCHEMA_VERSION
    status: Literal["FROZEN_BEFORE_EXECUTION"]
    claim_label: Literal[
        "RETROSPECTIVE_DEVELOPMENT_ONLY"
    ] = CLAIM_LABEL
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    implementation_base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    dataset_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    split: Literal["dev"]
    split_sha256: str = Field(pattern=_SHA256_PATTERN)
    sample_seed: str = Field(min_length=1, max_length=200)
    selected_case_count: int = Field(ge=1)
    selected_case_ids_sha256: str = Field(pattern=_SHA256_PATTERN)
    retrieval_mode: Literal["hybrid"]
    top_k: Literal[10]
    source_eval_run: FrozenSourceRun
    source_diagnostic_run: FrozenDiagnosticRun
    arms: tuple[ArmId, ArmId, ArmId]
    arm_order_policy: Literal["cyclic_latin_square_v1"]
    answer_model: FrozenModelIdentity
    timeout_seconds: float = Field(gt=0, le=300)
    max_attempts: int = Field(ge=1, le=3)
    multi_program_count: int = Field(ge=2, le=4)
    candidate_extraction_version: str = Field(min_length=1, max_length=200)
    candidate_extraction_config_sha256: str = Field(pattern=_SHA256_PATTERN)
    intent_version: str = Field(min_length=1, max_length=200)
    dsl_version: str = Field(min_length=1, max_length=200)
    validator_version: str = Field(min_length=1, max_length=200)
    compiler_version: str = Field(min_length=1, max_length=200)
    typed_planner_version: str = Field(min_length=1, max_length=200)
    multi_program_planner_version: str = Field(min_length=1, max_length=200)
    selector_version: str = Field(min_length=1, max_length=200)
    source_file_sha256: dict[str, str] = Field(min_length=1)
    primary_metrics: tuple[str, ...] = Field(min_length=1)
    operational_metrics: tuple[str, ...] = Field(min_length=1)
    stop_conditions: tuple[str, ...] = Field(min_length=1)
    non_claims: tuple[str, ...] = Field(min_length=1)

    @field_validator("source_file_sha256")
    @classmethod
    def validate_source_file_hashes(
        cls,
        value: dict[str, str],
    ) -> dict[str, str]:
        if (
            any(
                not path
                or Path(path).is_absolute()
                or ".." in Path(path).parts
                for path in value
            )
            or any(
                len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
                for digest in value.values()
            )
        ):
            raise ValueError("frozen source-file hash map is invalid")
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def validate_experiment_contract(
        self,
    ) -> FinQATypedRetrospectiveProtocol:
        if self.arms != _ARMS:
            raise ValueError("retrospective arms must be the frozen B0/B1/B2 order")
        if self.source_eval_run.run_id != self.source_diagnostic_run.run_id:
            raise ValueError("source evaluation and diagnostic run IDs must match")
        return self


class FinQATypedArmEvaluation(_StrictModel):
    arm_id: ArmId
    status: ArmStatus
    failure_reason: str | None = Field(default=None, max_length=128)
    final_answer: str
    calculation: str
    cited_unit_ids: list[str]
    answer_parseable: bool
    strict_execution_match: bool
    presentation_tolerance_match: bool
    citation_precision: float = Field(ge=0, le=1)
    citation_recall: float = Field(ge=0, le=1)
    grounded_execution_match: bool
    grounded_presentation_match: bool
    generation_calls: int = Field(ge=0)
    compiler_calls: int = Field(ge=0)
    generated_program_count: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    candidate_count: int = Field(ge=0)
    selected_program_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    selected_support_count: int = Field(ge=0)
    valid_program_count: int = Field(ge=0)
    invalid_program_count: int = Field(ge=0)
    duplicate_program_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_status_contract(self) -> FinQATypedArmEvaluation:
        if self.status == "ANSWERED" and self.failure_reason is not None:
            raise ValueError("answered arm cannot have a failure reason")
        if self.status != "ANSWERED" and self.failure_reason is None:
            raise ValueError("non-answer arm requires a failure reason")
        if self.status != "ANSWERED" and (
            self.final_answer
            or self.calculation
            or self.cited_unit_ids
            or self.strict_execution_match
            or self.grounded_execution_match
        ):
            raise ValueError("non-answer arm must fail closed")
        return self


class FinQATypedRetrospectiveCase(_StrictModel):
    case_id: str = Field(min_length=1)
    diagnostic_category: DiagnosticCategory
    execution_order: tuple[ArmId, ArmId, ArmId]
    selected_unit_ids: list[str] = Field(min_length=1)
    gold_unit_ids: list[str] = Field(min_length=1)
    selected_evidence_recall: float = Field(ge=0, le=1)
    admitted_unit_count: int = Field(ge=0)
    quarantined_unit_count: int = Field(ge=0)
    guard_rule_ids: list[str]
    historical_b0_strict_execution_match: bool
    historical_b0_grounded_execution_match: bool
    b0: FinQATypedArmEvaluation
    b1: FinQATypedArmEvaluation
    b2: FinQATypedArmEvaluation

    @model_validator(mode="after")
    def validate_arm_contract(self) -> FinQATypedRetrospectiveCase:
        if (
            set(self.execution_order) != set(_ARMS)
            or self.b0.arm_id != "B0_FREE_LITERAL"
            or self.b1.arm_id != "B1_TYPED_SINGLE"
            or self.b2.arm_id != "B2_TYPED_MULTI"
        ):
            raise ValueError("retrospective case arm contract is invalid")
        if len(self.selected_unit_ids) != len(set(self.selected_unit_ids)):
            raise ValueError("selected FinQA evidence IDs must be unique")
        return self


class FinQATypedArmSummary(_StrictModel):
    arm_id: ArmId
    case_count: int = Field(ge=1)
    answered_count: int = Field(ge=0)
    refusal_count: int = Field(ge=0)
    protocol_error_count: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1)
    execution_accuracy: float = Field(ge=0, le=1)
    execution_accuracy_on_answered: float | None = Field(default=None, ge=0, le=1)
    grounded_execution_accuracy: float = Field(ge=0, le=1)
    presentation_tolerance_accuracy: float = Field(ge=0, le=1)
    citation_precision_mean: float = Field(ge=0, le=1)
    citation_recall_mean: float = Field(ge=0, le=1)
    generation_calls: int = Field(ge=0)
    compiler_calls: int = Field(ge=0)
    generated_program_count: int = Field(ge=0)
    latency_ms_mean: float = Field(ge=0)
    latency_ms_p95: float = Field(ge=0)
    candidate_count_mean: float = Field(ge=0)
    failure_reason_counts: dict[str, int]


class FinQATypedPairedComparison(_StrictModel):
    baseline_arm_id: Literal["B0_FREE_LITERAL"]
    intervention_arm_id: Literal["B1_TYPED_SINGLE", "B2_TYPED_MULTI"]
    case_count: int = Field(ge=1)
    execution_accuracy_delta: float = Field(ge=-1, le=1)
    grounded_execution_accuracy_delta: float = Field(ge=-1, le=1)
    transition_counts: dict[str, int]
    wrong_to_correct_count: int = Field(ge=0)
    correct_to_wrong_count: int = Field(ge=0)
    prevented_operand_failure_count: int = Field(ge=0)
    new_refusal_count: int = Field(ge=0)
    mcnemar_exact_p_value: float = Field(ge=0, le=1)
    generation_call_multiplier: float | None = Field(default=None, ge=0)
    latency_mean_multiplier: float | None = Field(default=None, ge=0)


class FinQATypedRetrospectiveSummary(_StrictModel):
    claim_label: Literal[
        "RETROSPECTIVE_DEVELOPMENT_ONLY"
    ] = CLAIM_LABEL
    case_count: int = Field(ge=1)
    arm_summaries: dict[ArmId, FinQATypedArmSummary]
    paired_comparisons: list[FinQATypedPairedComparison]
    diagnostic_category_counts: dict[str, int]
    historical_b0_strict_reproduction_rate: float = Field(ge=0, le=1)
    historical_b0_grounded_reproduction_rate: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_summary_arms(self) -> FinQATypedRetrospectiveSummary:
        if set(self.arm_summaries) != set(_ARMS):
            raise ValueError("retrospective summary must contain all frozen arms")
        return self


class FinQATypedRetrospectiveRunManifest(_StrictModel):
    schema_version: Literal[
        "finqa_typed_retrospective_run_v1"
    ] = RUN_SCHEMA_VERSION
    claim_label: Literal[
        "RETROSPECTIVE_DEVELOPMENT_ONLY"
    ] = CLAIM_LABEL
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    protocol_sha256: str = Field(pattern=_SHA256_PATTERN)
    dataset_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    split: Literal["dev"]
    split_sha256: str = Field(pattern=_SHA256_PATTERN)
    selected_case_count: int = Field(ge=1)
    selected_case_ids_sha256: str = Field(pattern=_SHA256_PATTERN)
    retrieval_mode: Literal["hybrid"]
    top_k: Literal[10]
    answer_model: FrozenModelIdentity
    execution_code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    implementation_snapshot_sha256: str = Field(pattern=_SHA256_PATTERN)
    timeout_seconds: float = Field(gt=0, le=300)
    max_attempts: int = Field(ge=1, le=3)
    multi_program_count: int = Field(ge=2, le=4)
    summary: FinQATypedRetrospectiveSummary
    artifacts: dict[str, str] = Field(default_factory=dict)

    @field_validator("artifacts")
    @classmethod
    def validate_artifacts(cls, value: dict[str, str]) -> dict[str, str]:
        if value and (
            set(value) != _RUN_ARTIFACTS
            or any(
                len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
                for digest in value.values()
            )
        ):
            raise ValueError("retrospective run artifact set is invalid")
        return value


class FinQATypedRetrospectivePublicEvidence(_StrictModel):
    schema_version: Literal[
        "finqa_typed_retrospective_public_v1"
    ] = PUBLIC_EVIDENCE_SCHEMA_VERSION
    claim_label: Literal[
        "RETROSPECTIVE_DEVELOPMENT_ONLY"
    ] = CLAIM_LABEL
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    protocol_sha256: str = Field(pattern=_SHA256_PATTERN)
    private_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    private_details_sha256: str = Field(pattern=_SHA256_PATTERN)
    dataset_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    split: Literal["dev"]
    selected_case_count: int = Field(ge=1)
    selected_case_ids_sha256: str = Field(pattern=_SHA256_PATTERN)
    answer_model: FrozenModelIdentity
    implementation_snapshot_sha256: str = Field(pattern=_SHA256_PATTERN)
    summary: FinQATypedRetrospectiveSummary
    non_claims: tuple[str, ...] = Field(min_length=1)


def canonical_json_bytes(value: Any, *, newline: bool = False) -> bytes:
    content = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return content + (b"\n" if newline else b"")


def protocol_sha256(path: Path) -> str:
    payload = load_protocol(path)
    return hashlib.sha256(
        canonical_json_bytes(payload.model_dump(mode="json"))
    ).hexdigest()


def load_protocol(path: Path) -> FinQATypedRetrospectiveProtocol:
    try:
        payload = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("typed retrospective protocol is unreadable") from exc
    return FinQATypedRetrospectiveProtocol.model_validate(payload)


def implementation_snapshot_sha256(
    source_file_sha256: Mapping[str, str],
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(dict(sorted(source_file_sha256.items())))
    ).hexdigest()


def validate_frozen_source_files(
    protocol: FinQATypedRetrospectiveProtocol,
    *,
    repository_root: Path,
) -> None:
    root = Path(repository_root).resolve()
    for relative_path, expected_sha256 in protocol.source_file_sha256.items():
        path = (root / relative_path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("frozen source path escapes repository") from exc
        if not path.is_file():
            raise ValueError(f"frozen source file is missing: {relative_path}")
        actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(f"frozen source hash mismatch: {relative_path}")


def arm_evaluation_from_case(
    *,
    arm_id: ArmId,
    evaluation: FinQACaseEvaluation,
    compiler_calls: int,
    generated_program_count: int,
    candidate_count: int,
    selected_program_sha256: str | None = None,
    selected_support_count: int = 0,
    valid_program_count: int = 0,
    invalid_program_count: int = 0,
    duplicate_program_count: int = 0,
) -> FinQATypedArmEvaluation:
    status: ArmStatus = (
        "ANSWERED" if evaluation.answer_status == "ok" else "PROTOCOL_ERROR"
    )
    failure_reason = (
        None if status == "ANSWERED" else str(evaluation.answer_status)
    )
    return FinQATypedArmEvaluation(
        arm_id=arm_id,
        status=status,
        failure_reason=failure_reason,
        final_answer=evaluation.final_answer if status == "ANSWERED" else "",
        calculation=evaluation.calculation if status == "ANSWERED" else "",
        cited_unit_ids=(
            evaluation.cited_unit_ids if status == "ANSWERED" else []
        ),
        answer_parseable=(
            evaluation.answer_parseable if status == "ANSWERED" else False
        ),
        strict_execution_match=(
            evaluation.strict_execution_match if status == "ANSWERED" else False
        ),
        presentation_tolerance_match=bool(
            evaluation.presentation_tolerance_match
            if status == "ANSWERED"
            else False
        ),
        citation_precision=(
            evaluation.citation_precision if status == "ANSWERED" else 0.0
        ),
        citation_recall=(
            evaluation.citation_recall if status == "ANSWERED" else 0.0
        ),
        grounded_execution_match=(
            evaluation.grounded_execution_match if status == "ANSWERED" else False
        ),
        grounded_presentation_match=bool(
            evaluation.grounded_presentation_match
            if status == "ANSWERED"
            else False
        ),
        generation_calls=evaluation.generation_calls,
        compiler_calls=compiler_calls,
        generated_program_count=generated_program_count,
        latency_ms=evaluation.latency_ms,
        candidate_count=candidate_count,
        selected_program_sha256=selected_program_sha256,
        selected_support_count=selected_support_count,
        valid_program_count=valid_program_count,
        invalid_program_count=invalid_program_count,
        duplicate_program_count=duplicate_program_count,
    )


def refused_arm_evaluation(
    *,
    arm_id: ArmId,
    failure_reason: str,
    generation_calls: int,
    compiler_calls: int,
    generated_program_count: int,
    latency_ms: float,
    candidate_count: int,
    status: ArmStatus = "REFUSED",
    valid_program_count: int = 0,
    invalid_program_count: int = 0,
    duplicate_program_count: int = 0,
) -> FinQATypedArmEvaluation:
    return FinQATypedArmEvaluation(
        arm_id=arm_id,
        status=status,
        failure_reason=failure_reason[:128],
        final_answer="",
        calculation="",
        cited_unit_ids=[],
        answer_parseable=False,
        strict_execution_match=False,
        presentation_tolerance_match=False,
        citation_precision=0.0,
        citation_recall=0.0,
        grounded_execution_match=False,
        grounded_presentation_match=False,
        generation_calls=generation_calls,
        compiler_calls=compiler_calls,
        generated_program_count=generated_program_count,
        latency_ms=latency_ms,
        candidate_count=candidate_count,
        selected_support_count=0,
        valid_program_count=valid_program_count,
        invalid_program_count=invalid_program_count,
        duplicate_program_count=duplicate_program_count,
    )


def summarize_typed_retrospective(
    rows: Sequence[FinQATypedRetrospectiveCase],
) -> FinQATypedRetrospectiveSummary:
    values = list(rows)
    if not values:
        raise ValueError("typed retrospective summary requires at least one case")
    case_ids = [row.case_id for row in values]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("typed retrospective case IDs must be unique")
    by_arm = {
        "B0_FREE_LITERAL": [row.b0 for row in values],
        "B1_TYPED_SINGLE": [row.b1 for row in values],
        "B2_TYPED_MULTI": [row.b2 for row in values],
    }
    arm_summaries = {
        arm_id: _summarize_arm(arm_id, arm_rows)
        for arm_id, arm_rows in by_arm.items()
    }
    return FinQATypedRetrospectiveSummary(
        case_count=len(values),
        arm_summaries=arm_summaries,
        paired_comparisons=[
            _paired_comparison(values, "B1_TYPED_SINGLE"),
            _paired_comparison(values, "B2_TYPED_MULTI"),
        ],
        diagnostic_category_counts=dict(
            sorted(Counter(row.diagnostic_category for row in values).items())
        ),
        historical_b0_strict_reproduction_rate=(
            sum(
                row.historical_b0_strict_execution_match
                == row.b0.strict_execution_match
                for row in values
            )
            / len(values)
        ),
        historical_b0_grounded_reproduction_rate=(
            sum(
                row.historical_b0_grounded_execution_match
                == row.b0.grounded_execution_match
                for row in values
            )
            / len(values)
        ),
    )


def publish_typed_retrospective_run(
    *,
    root: Path,
    manifest: FinQATypedRetrospectiveRunManifest,
    details: Sequence[FinQATypedRetrospectiveCase],
) -> Path:
    rows = list(details)
    if manifest.artifacts:
        raise ValueError("artifacts are assigned during publication")
    if summarize_typed_retrospective(rows) != manifest.summary:
        raise ValueError("retrospective manifest summary does not match details")
    if len(rows) != manifest.selected_case_count:
        raise ValueError("retrospective detail count does not match manifest")
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    final = root / manifest.run_id
    if final.exists():
        raise FileExistsError(f"retrospective run already exists: {manifest.run_id}")
    staging = Path(
        tempfile.mkdtemp(prefix=f".{manifest.run_id}.staging-", dir=root)
    )
    try:
        details_bytes = b"".join(
            canonical_json_bytes(
                row.model_dump(mode="json"),
                newline=True,
            )
            for row in rows
        )
        summary_bytes = canonical_json_bytes(
            manifest.summary.model_dump(mode="json"),
            newline=True,
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
            canonical_json_bytes(
                final_manifest.model_dump(mode="json"),
                newline=True,
            )
        )
        verify_typed_retrospective_run(staging)
        atomic_directory_move(staging, final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    verify_typed_retrospective_run(final)
    return final


def verify_typed_retrospective_run(
    run_dir: Path,
) -> FinQATypedRetrospectiveRunManifest:
    run_dir = Path(run_dir).resolve()
    expected_files = {*_RUN_ARTIFACTS, "manifest.json"}
    actual_files = {path.name for path in run_dir.iterdir() if path.is_file()}
    if actual_files != expected_files:
        raise ValueError("retrospective run has an unexpected artifact set")
    manifest = FinQATypedRetrospectiveRunManifest.model_validate_json(
        (run_dir / "manifest.json").read_bytes()
    )
    if manifest.run_id != run_dir.name and ".staging-" not in run_dir.name:
        raise ValueError("retrospective run directory does not match manifest")
    for name, expected_sha256 in manifest.artifacts.items():
        if hashlib.sha256((run_dir / name).read_bytes()).hexdigest() != expected_sha256:
            raise ValueError(f"retrospective run artifact mismatch: {name}")
    rows = [
        FinQATypedRetrospectiveCase.model_validate(
            json.loads(line, object_pairs_hook=_unique_object)
        )
        for line in (run_dir / "details.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    summary = FinQATypedRetrospectiveSummary.model_validate_json(
        (run_dir / "summary.json").read_bytes()
    )
    if (
        len(rows) != manifest.selected_case_count
        or summary != manifest.summary
        or summarize_typed_retrospective(rows) != summary
    ):
        raise ValueError("retrospective run summary cannot be reproduced")
    return manifest


def build_public_evidence(
    *,
    run_dir: Path,
    protocol: FinQATypedRetrospectiveProtocol,
) -> FinQATypedRetrospectivePublicEvidence:
    run_dir = Path(run_dir).resolve()
    manifest = verify_typed_retrospective_run(run_dir)
    protocol_digest = hashlib.sha256(
        canonical_json_bytes(protocol.model_dump(mode="json"))
    ).hexdigest()
    if (
        manifest.protocol_id != protocol.protocol_id
        or manifest.protocol_sha256 != protocol_digest
    ):
        raise ValueError("public evidence protocol does not match private run")
    return FinQATypedRetrospectivePublicEvidence(
        run_id=manifest.run_id,
        protocol_id=manifest.protocol_id,
        protocol_sha256=protocol_digest,
        private_manifest_sha256=hashlib.sha256(
            (run_dir / "manifest.json").read_bytes()
        ).hexdigest(),
        private_details_sha256=hashlib.sha256(
            (run_dir / "details.jsonl").read_bytes()
        ).hexdigest(),
        dataset_revision=manifest.dataset_revision,
        split=manifest.split,
        selected_case_count=manifest.selected_case_count,
        selected_case_ids_sha256=manifest.selected_case_ids_sha256,
        answer_model=manifest.answer_model,
        implementation_snapshot_sha256=(
            manifest.implementation_snapshot_sha256
        ),
        summary=manifest.summary,
        non_claims=protocol.non_claims,
    )


def _summarize_arm(
    arm_id: ArmId,
    rows: Sequence[FinQATypedArmEvaluation],
) -> FinQATypedArmSummary:
    count = len(rows)
    answered = [row for row in rows if row.status == "ANSWERED"]
    latencies = sorted(row.latency_ms for row in rows)
    p95_index = max(0, math.ceil(count * 0.95) - 1)
    failures = Counter(
        row.failure_reason for row in rows if row.failure_reason is not None
    )
    return FinQATypedArmSummary(
        arm_id=arm_id,
        case_count=count,
        answered_count=len(answered),
        refusal_count=sum(row.status == "REFUSED" for row in rows),
        protocol_error_count=sum(
            row.status == "PROTOCOL_ERROR" for row in rows
        ),
        coverage=len(answered) / count,
        execution_accuracy=sum(row.strict_execution_match for row in rows) / count,
        execution_accuracy_on_answered=(
            sum(row.strict_execution_match for row in answered) / len(answered)
            if answered
            else None
        ),
        grounded_execution_accuracy=(
            sum(row.grounded_execution_match for row in rows) / count
        ),
        presentation_tolerance_accuracy=(
            sum(row.presentation_tolerance_match for row in rows) / count
        ),
        citation_precision_mean=sum(row.citation_precision for row in rows) / count,
        citation_recall_mean=sum(row.citation_recall for row in rows) / count,
        generation_calls=sum(row.generation_calls for row in rows),
        compiler_calls=sum(row.compiler_calls for row in rows),
        generated_program_count=sum(
            row.generated_program_count for row in rows
        ),
        latency_ms_mean=sum(latencies) / count,
        latency_ms_p95=latencies[p95_index],
        candidate_count_mean=sum(row.candidate_count for row in rows) / count,
        failure_reason_counts=dict(sorted(failures.items())),
    )


def _paired_comparison(
    rows: Sequence[FinQATypedRetrospectiveCase],
    intervention_arm_id: Literal["B1_TYPED_SINGLE", "B2_TYPED_MULTI"],
) -> FinQATypedPairedComparison:
    baseline = [row.b0 for row in rows]
    intervention = [
        row.b1 if intervention_arm_id == "B1_TYPED_SINGLE" else row.b2
        for row in rows
    ]
    transitions = Counter(
        _correctness_transition(before.strict_execution_match, after.strict_execution_match)
        for before, after in zip(baseline, intervention, strict=True)
    )
    baseline_calls = sum(row.generation_calls for row in baseline)
    baseline_latency = sum(row.latency_ms for row in baseline) / len(baseline)
    intervention_latency = (
        sum(row.latency_ms for row in intervention) / len(intervention)
    )
    correct_to_wrong = transitions["correct_to_wrong"]
    wrong_to_correct = transitions["wrong_to_correct"]
    return FinQATypedPairedComparison(
        baseline_arm_id="B0_FREE_LITERAL",
        intervention_arm_id=intervention_arm_id,
        case_count=len(rows),
        execution_accuracy_delta=(
            sum(row.strict_execution_match for row in intervention)
            - sum(row.strict_execution_match for row in baseline)
        )
        / len(rows),
        grounded_execution_accuracy_delta=(
            sum(row.grounded_execution_match for row in intervention)
            - sum(row.grounded_execution_match for row in baseline)
        )
        / len(rows),
        transition_counts={
            name: transitions[name]
            for name in (
                "correct_to_correct",
                "correct_to_wrong",
                "wrong_to_correct",
                "wrong_to_wrong",
            )
        },
        wrong_to_correct_count=wrong_to_correct,
        correct_to_wrong_count=correct_to_wrong,
        prevented_operand_failure_count=sum(
            row.diagnostic_category == "operand_selection_signal"
            and not row.b0.strict_execution_match
            and (
                row.b1.strict_execution_match
                if intervention_arm_id == "B1_TYPED_SINGLE"
                else row.b2.strict_execution_match
            )
            for row in rows
        ),
        new_refusal_count=sum(
            before.status == "ANSWERED" and after.status != "ANSWERED"
            for before, after in zip(baseline, intervention, strict=True)
        ),
        mcnemar_exact_p_value=_exact_mcnemar_p_value(
            correct_to_wrong=correct_to_wrong,
            wrong_to_correct=wrong_to_correct,
        ),
        generation_call_multiplier=(
            sum(row.generation_calls for row in intervention) / baseline_calls
            if baseline_calls
            else None
        ),
        latency_mean_multiplier=(
            intervention_latency / baseline_latency
            if baseline_latency
            else None
        ),
    )


def _correctness_transition(before: bool, after: bool) -> str:
    if before and after:
        return "correct_to_correct"
    if before:
        return "correct_to_wrong"
    if after:
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
        math.comb(discordant, index) for index in range(smaller + 1)
    ) / (2**discordant)
    return min(1.0, 2 * lower_tail)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


__all__ = [
    "CLAIM_LABEL",
    "FinQATypedArmEvaluation",
    "FinQATypedRetrospectiveCase",
    "FinQATypedRetrospectiveProtocol",
    "FinQATypedRetrospectivePublicEvidence",
    "FinQATypedRetrospectiveRunManifest",
    "FinQATypedRetrospectiveSummary",
    "FrozenModelIdentity",
    "arm_evaluation_from_case",
    "build_public_evidence",
    "canonical_json_bytes",
    "implementation_snapshot_sha256",
    "load_protocol",
    "protocol_sha256",
    "publish_typed_retrospective_run",
    "refused_arm_evaluation",
    "summarize_typed_retrospective",
    "validate_frozen_source_files",
    "verify_typed_retrospective_run",
]
