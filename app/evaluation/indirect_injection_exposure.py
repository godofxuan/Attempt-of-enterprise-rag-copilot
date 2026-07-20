from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.evaluation.indirect_injection_dataset import (
    LoadedSecurityBundle,
    load_security_bundle,
)
from app.evaluation.indirect_injection_live_runner import LiveCaseObservation
from app.evaluation.indirect_injection_live_writer import (
    LiveSecurityRunManifest,
    LiveSecurityRunManifestV2,
    verify_live_security_run,
)
from app.evaluation.indirect_injection_runner import SecurityCaseResult


SOURCE_RUN_ID = "r2-s2-s1-dev-20260719-01"
SOURCE_MANIFEST_SHA256 = (
    "3fe51ea7e404d7d1c09711b14f422b92b2474df7148e4f15df1e949081f5586e"
)
SOURCE_GIT_HEAD = "073d7356026954c26c1429fb9faddc5e9a5dcb87"
SOURCE_GUARD_SHA256 = (
    "78ed0509144820ccd05aff61c1509357dd8fe3dbfc8a0c6df30fc304a15e9cd2"
)
COUNTERFACTUAL_DEPTHS = (1, 2, 4)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class ExposureEvidenceError(ValueError):
    pass


class ExposureSourceEvidence(_StrictFrozenModel):
    run_id: Literal["r2-s2-s1-dev-20260719-01"]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_git_head: Literal["073d7356026954c26c1429fb9faddc5e9a5dcb87"]
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    guard_ruleset_sha256: Literal[
        "78ed0509144820ccd05aff61c1509357dd8fe3dbfc8a0c6df30fc304a15e9cd2"
    ]
    case_count: Literal[36]
    arm_event_count: Literal[72]
    off_then_on_count: Literal[18]
    on_then_off_count: Literal[18]


@dataclass(frozen=True)
class ExposureInputs:
    source_run_dir: Path
    manifest: LiveSecurityRunManifestV2
    bundle: LoadedSecurityBundle
    guard_on_rows: Sequence[Mapping[str, object]]
    guard_off_rows: Sequence[Mapping[str, object]]
    source: ExposureSourceEvidence


@dataclass(frozen=True)
class _SourceArmRow:
    raw: Mapping[str, object]
    security: SecurityCaseResult
    live: LiveCaseObservation


def load_exposure_inputs(
    source_run_dir: Path,
    *,
    security_data_root: Path,
    expected_manifest_sha256: str,
) -> ExposureInputs:
    source_run_dir = Path(source_run_dir).resolve()
    manifest = verify_live_security_run(source_run_dir)
    if not isinstance(manifest, LiveSecurityRunManifestV2):
        raise ExposureEvidenceError("source run must use live manifest v2")
    if manifest.split != "dev":
        raise ExposureEvidenceError("source run must use dev split")
    if manifest.run_id != SOURCE_RUN_ID:
        raise ExposureEvidenceError("source run ID mismatch")
    if manifest.git.head != SOURCE_GIT_HEAD:
        raise ExposureEvidenceError("source Git HEAD mismatch")
    if manifest.guard.ruleset_sha256 != SOURCE_GUARD_SHA256:
        raise ExposureEvidenceError("source Guard SHA-256 mismatch")
    manifest_sha256 = _sha256(source_run_dir / "manifest.json")
    if manifest_sha256 != expected_manifest_sha256:
        raise ExposureEvidenceError("source manifest SHA-256 mismatch")
    bundle = load_security_bundle(security_data_root, "dev")
    if bundle.dataset_sha256 != manifest.data.dataset_sha256:
        raise ExposureEvidenceError("source dataset SHA-256 mismatch")
    if bundle.fixture_manifest_sha256 != manifest.data.fixture_manifest_sha256:
        raise ExposureEvidenceError("source fixture SHA-256 mismatch")
    rows = _load_source_rows(source_run_dir / "per_case.jsonl")
    guard_off_rows, guard_on_rows = _validate_source_arm_rows(
        rows,
        manifest=manifest,
        dataset_case_ids=tuple(case.case_id for case in bundle.dataset.cases),
    )
    source = _source_evidence(manifest, manifest_sha256)
    return ExposureInputs(
        source_run_dir=source_run_dir,
        manifest=manifest,
        bundle=bundle,
        guard_on_rows=guard_on_rows,
        guard_off_rows=guard_off_rows,
        source=source,
    )


def _load_source_rows(path: Path) -> tuple[Mapping[str, object], ...]:
    payload = path.read_bytes()
    if not payload or not payload.endswith(b"\n") or b"\r" in payload:
        raise ExposureEvidenceError("source per-case JSONL is not canonical")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExposureEvidenceError("source per-case JSONL is not UTF-8") from exc

    rows: list[Mapping[str, object]] = []
    for line in text.splitlines():
        try:
            parsed = json.loads(line, object_pairs_hook=_unique_object)
        except _DuplicateJsonKey as exc:
            raise ExposureEvidenceError("source per-case JSON contains duplicate keys") from exc
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ExposureEvidenceError("source per-case JSONL is invalid") from exc
        if not isinstance(parsed, dict):
            raise ExposureEvidenceError("source per-case row must be an object")
        try:
            canonical = json.dumps(
                parsed,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ExposureEvidenceError("source per-case JSONL is invalid") from exc
        if line != canonical:
            raise ExposureEvidenceError("source per-case JSONL is not canonical")
        rows.append(parsed)
    return tuple(rows)


def _validate_source_arm_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    manifest: LiveSecurityRunManifestV2,
    dataset_case_ids: tuple[str, ...],
) -> tuple[tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]:
    if (
        len(dataset_case_ids) != 36
        or len(set(dataset_case_ids)) != 36
        or len(rows) != 72
    ):
        raise ExposureEvidenceError("source case/arm set is incomplete")
    if (
        manifest.arm_order.case_count != 36
        or manifest.arm_order.off_then_on_count != 18
        or manifest.arm_order.on_then_off_count != 18
        or len(manifest.arm_order.assignments) != 36
        or set(manifest.arm_order.case_ids()) != set(dataset_case_ids)
    ):
        raise ExposureEvidenceError("source arm allocation is invalid")

    typed_rows = tuple(_parse_source_arm_row(row) for row in rows)
    row_by_identity: dict[tuple[str, str], _SourceArmRow] = {}
    for row in typed_rows:
        if row.security.case_id != row.live.case_id:
            raise ExposureEvidenceError("source case/arm row case IDs disagree")
        if row.security.guard_mode != row.live.guard_mode:
            raise ExposureEvidenceError("source case/arm row Guard modes disagree")
        identity = (row.security.case_id, row.security.guard_mode)
        if identity in row_by_identity:
            raise ExposureEvidenceError("source case/arm identities must be unique")
        row_by_identity[identity] = row

    expected_case_ids = set(dataset_case_ids)
    off_case_ids = {
        case_id for case_id, guard_mode in row_by_identity if guard_mode == "off"
    }
    on_case_ids = {
        case_id for case_id, guard_mode in row_by_identity if guard_mode == "on"
    }
    if off_case_ids != expected_case_ids or on_case_ids != expected_case_ids:
        raise ExposureEvidenceError("source case/arm set is incomplete")

    _validate_arm_order(typed_rows, manifest)
    _validate_pair_evidence(row_by_identity, dataset_case_ids)
    _validate_protocol_evidence(row_by_identity.values(), manifest)

    return (
        tuple(row_by_identity[(case_id, "off")].raw for case_id in dataset_case_ids),
        tuple(row_by_identity[(case_id, "on")].raw for case_id in dataset_case_ids),
    )


def _parse_source_arm_row(row: Mapping[str, object]) -> _SourceArmRow:
    if set(row) != {"arm_execution", "security", "live"}:
        raise ExposureEvidenceError("source per-case row schema is invalid")
    arm_execution = row["arm_execution"]
    security = row["security"]
    live = row["live"]
    if not isinstance(arm_execution, Mapping) or set(arm_execution) != {
        "protocol_id",
        "case_hash",
        "hash_rank",
        "arm_order",
        "execution_index",
        "arm_position",
    }:
        raise ExposureEvidenceError("source per-case arm schema is invalid")
    if not isinstance(security, Mapping) or not isinstance(live, Mapping):
        raise ExposureEvidenceError("source per-case row schema is invalid")
    try:
        return _SourceArmRow(
            raw=row,
            security=SecurityCaseResult.model_validate_json(
                json.dumps(security, ensure_ascii=False)
            ),
            live=LiveCaseObservation.model_validate_json(
                json.dumps(live, ensure_ascii=False)
            ),
        )
    except ValidationError as exc:
        raise ExposureEvidenceError("source per-case row schema is invalid") from exc


def _validate_arm_order(
    rows: Sequence[_SourceArmRow],
    manifest: LiveSecurityRunManifestV2,
) -> None:
    execution_indexes: list[int] = []
    for pair_index, assignment in enumerate(manifest.arm_order.assignments):
        pair_rows = rows[pair_index * 2 : pair_index * 2 + 2]
        pair_indexes: list[int] = []
        for arm_position, (guard_mode, row) in enumerate(
            zip(assignment.modes(), pair_rows), start=1
        ):
            arm = row.raw["arm_execution"]
            assert isinstance(arm, Mapping)
            execution_index = arm["execution_index"]
            if (
                not isinstance(execution_index, int)
                or isinstance(execution_index, bool)
                or execution_index < 1
            ):
                raise ExposureEvidenceError("source arm execution index is invalid")
            expected_arm = {
                "protocol_id": manifest.arm_order.protocol_id,
                "case_hash": assignment.case_hash,
                "hash_rank": assignment.hash_rank,
                "arm_order": assignment.arm_order,
                "execution_index": execution_index,
                "arm_position": arm_position,
            }
            if (
                arm != expected_arm
                or row.security.case_id != assignment.case_id
                or row.live.case_id != assignment.case_id
                or row.security.guard_mode != guard_mode
                or row.live.guard_mode != guard_mode
            ):
                raise ExposureEvidenceError("source arm order contradicts manifest")
            execution_indexes.append(execution_index)
            pair_indexes.append(execution_index)
        if pair_indexes[1] != pair_indexes[0] + 1:
            raise ExposureEvidenceError("source paired arm execution is not adjacent")
    if sorted(execution_indexes) != list(range(1, 73)):
        raise ExposureEvidenceError("source arm execution indexes are not exact")


def _validate_pair_evidence(
    rows: Mapping[tuple[str, str], _SourceArmRow],
    dataset_case_ids: Sequence[str],
) -> None:
    for case_id in dataset_case_ids:
        off = rows[(case_id, "off")]
        on = rows[(case_id, "on")]
        if (
            off.security.input_fingerprint != on.security.input_fingerprint
            or off.security.nonce_fingerprint != on.security.nonce_fingerprint
            or off.security.candidate_order != on.security.candidate_order
            or off.live.pair_input_fingerprint != on.live.pair_input_fingerprint
        ):
            raise ExposureEvidenceError("source paired inputs are inconsistent")


def _validate_protocol_evidence(
    rows: Sequence[_SourceArmRow],
    manifest: LiveSecurityRunManifestV2,
) -> None:
    if not manifest.observation.protocol_complete:
        raise ExposureEvidenceError("source run protocol is incomplete")
    if not manifest.observation.pair_input_consistent:
        raise ExposureEvidenceError("source paired inputs are inconsistent")
    if any(not row.live.retrieval_completed for row in rows):
        raise ExposureEvidenceError("source run protocol is incomplete")
    if any(row.live.model_error_codes for row in rows):
        raise ExposureEvidenceError("source run contains model errors")
    if any(row.security.guard_error_count for row in rows):
        raise ExposureEvidenceError("source run contains Guard errors")
    if any(row.live.blocked_egress_attempt_count for row in rows):
        raise ExposureEvidenceError("source run contains blocked external egress")


def _source_evidence(
    manifest: LiveSecurityRunManifestV2,
    manifest_sha256: str,
) -> ExposureSourceEvidence:
    return ExposureSourceEvidence(
        run_id=manifest.run_id,
        manifest_sha256=manifest_sha256,
        source_git_head=manifest.git.head,
        dataset_sha256=manifest.data.dataset_sha256,
        fixture_manifest_sha256=manifest.data.fixture_manifest_sha256,
        guard_ruleset_sha256=manifest.guard.ruleset_sha256,
        case_count=manifest.arm_order.case_count,
        arm_event_count=manifest.arm_order.case_count * 2,
        off_then_on_count=manifest.arm_order.off_then_on_count,
        on_then_off_count=manifest.arm_order.on_then_off_count,
    )


class _DuplicateJsonKey(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "COUNTERFACTUAL_DEPTHS",
    "ExposureEvidenceError",
    "ExposureInputs",
    "ExposureSourceEvidence",
    "SOURCE_GIT_HEAD",
    "SOURCE_GUARD_SHA256",
    "SOURCE_MANIFEST_SHA256",
    "SOURCE_RUN_ID",
    "load_exposure_inputs",
]
