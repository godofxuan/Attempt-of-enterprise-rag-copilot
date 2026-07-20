from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.domain.agent import ToolError
from app.domain.queries import OpenResult, SearchRequest, UserContext
from app.domain.retrieved_security import GuardedSearchResult, ScannedContentUnit
from app.evaluation.indirect_injection_dataset import (
    LoadedSecurityBundle,
    load_security_bundle,
)
from app.evaluation.indirect_injection_contracts import (
    FixtureCase,
    IndirectInjectionCase,
)
from app.evaluation.indirect_injection_live_runner import LiveCaseObservation
from app.evaluation.indirect_injection_live_writer import (
    LiveSecurityRunManifest,
    LiveSecurityRunManifestV2,
    verify_live_security_run,
)
from app.evaluation.indirect_injection_runner import SecurityCaseResult, _search_hit
from app.retrieval.pipeline import RankedSearchCandidate, RankedSearchPool
from app.security.retrieved_admission import (
    GuardedAdmissionOutcome,
    RetrievedContentAdmission,
)
from app.security.retrieved_content import RetrievedContentGuard


SOURCE_RUN_ID = "r2-s2-s1-dev-20260719-01"
SOURCE_MANIFEST_SHA256 = (
    "3fe51ea7e404d7d1c09711b14f422b92b2474df7148e4f15df1e949081f5586e"
)
SOURCE_GIT_HEAD = "073d7356026954c26c1429fb9faddc5e9a5dcb87"
SOURCE_GUARD_SHA256 = (
    "78ed0509144820ccd05aff61c1509357dd8fe3dbfc8a0c6df30fc304a15e9cd2"
)
COUNTERFACTUAL_DEPTHS = (1, 2, 4)


ExposureLocation = Literal[
    "search_candidate",
    "open_result",
    "find_result",
]
ExposureSurface = Literal[
    "matched",
    "parent",
    "title",
    "source_path",
    "section",
    "version",
    "open",
    "find",
]
ReplayScanSurface = Literal[
    "matched",
    "parent",
    "metadata",
    "aggregate",
    "open",
    "find_preview",
]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class ExposureEvidenceError(ValueError):
    pass


class ExposureUnitLocation(_StrictFrozenModel):
    case_id: str
    unit_id: str
    location: ExposureLocation
    source_surface: ExposureSurface
    candidate_chunk_id: str | None = None
    actual_candidate_rank: int | None = Field(default=None, ge=1, le=4)
    candidate_pool_present: bool
    counterfactual_search_applicable: bool

    @model_validator(mode="after")
    def validate_location_state(self) -> ExposureUnitLocation:
        if self.location == "search_candidate":
            if self.source_surface not in {
                "matched",
                "parent",
                "title",
                "source_path",
                "section",
                "version",
            }:
                raise ValueError("search_candidate requires a search source surface")
            if not self.candidate_chunk_id:
                raise ValueError(
                    "search_candidate requires a non-empty candidate_chunk_id"
                )
            if self.actual_candidate_rank is None:
                raise ValueError("search_candidate requires actual_candidate_rank")
            if not self.candidate_pool_present:
                raise ValueError(
                    "search_candidate requires candidate_pool_present=True"
                )
            if not self.counterfactual_search_applicable:
                raise ValueError(
                    "search_candidate requires counterfactual_search_applicable=True"
                )
            return self

        required_surface = "open" if self.location == "open_result" else "find"
        if self.source_surface != required_surface:
            raise ValueError(
                f"{self.location} requires source_surface={required_surface}"
            )
        if self.candidate_chunk_id is not None:
            raise ValueError(f"{self.location} requires candidate_chunk_id=None")
        if self.actual_candidate_rank is not None:
            raise ValueError(f"{self.location} requires actual_candidate_rank=None")
        if self.candidate_pool_present:
            raise ValueError(f"{self.location} requires candidate_pool_present=False")
        if self.counterfactual_search_applicable:
            raise ValueError(
                f"{self.location} requires counterfactual_search_applicable=False"
            )
        return self


class ReplayedUnitState(_StrictFrozenModel):
    location: ExposureUnitLocation
    replay_selected_for_evidence: bool
    replay_guard_reached: bool
    replay_guard_quarantined: bool
    replay_scan_surfaces: tuple[ReplayScanSurface, ...]

    @property
    def actual_candidate_rank(self) -> int | None:
        return self.location.actual_candidate_rank

    @model_validator(mode="after")
    def validate_replayed_unit(self) -> ReplayedUnitState:
        if len(self.replay_scan_surfaces) != len(set(self.replay_scan_surfaces)):
            raise ValueError("replay scan surfaces must be unique")
        if self.replay_guard_reached != bool(self.replay_scan_surfaces):
            raise ValueError("replay reach must exactly match scan provenance")
        if self.replay_guard_quarantined and not self.replay_guard_reached:
            raise ValueError("replay quarantine requires Guard reach")
        if (
            self.replay_selected_for_evidence
            and self.location.location != "search_candidate"
        ):
            raise ValueError("only search candidates can be selected evidence")
        return self


class ReplayedCaseState(_StrictFrozenModel):
    case_id: str
    recorded_tool_sequence: tuple[str, ...]
    replayed_content_operations: tuple[Literal["search", "find", "open"], ...]
    consumed_content_operation_count: int = Field(ge=0)
    guarded_content_operation_count: int = Field(ge=0)
    tool_path_guard_coverage: Literal[True]
    live_guard_reached_count: int = Field(ge=0)
    live_guard_quarantined_count: int = Field(ge=0)
    replay_guard_reached_count: int = Field(ge=0)
    replay_guard_quarantined_count: int = Field(ge=0)
    replay_live_aggregate_match: Literal[True]
    units: tuple[ReplayedUnitState, ...]
    replay_scanned_chars: int = Field(ge=0)
    replay_scanned_surface_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_replayed_case(self) -> ReplayedCaseState:
        if self.consumed_content_operation_count != len(
            self.replayed_content_operations
        ):
            raise ValueError("consumed operations must match replayed content")
        if (
            self.guarded_content_operation_count
            != self.consumed_content_operation_count
        ):
            raise ValueError("every consumed content operation must be guarded")
        unit_ids = tuple(unit.location.unit_id for unit in self.units)
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("replayed unit IDs must be unique")
        if any(unit.location.case_id != self.case_id for unit in self.units):
            raise ValueError("replayed units must belong to the replayed case")
        if self.replay_guard_reached_count != sum(
            unit.replay_guard_reached for unit in self.units
        ):
            raise ValueError("replay reached count must match replayed units")
        if self.replay_guard_quarantined_count != sum(
            unit.replay_guard_quarantined for unit in self.units
        ):
            raise ValueError("replay quarantined count must match replayed units")
        if (
            self.live_guard_reached_count != self.replay_guard_reached_count
            or self.live_guard_quarantined_count
            != self.replay_guard_quarantined_count
        ):
            raise ValueError("replay/live aggregate mismatch")
        return self


def map_attack_unit_locations(
    case: IndirectInjectionCase,
    fixture: FixtureCase,
    *,
    candidate_order: tuple[str, ...],
) -> tuple[ExposureUnitLocation, ...]:
    if case.case_id != fixture.case_id:
        raise ExposureEvidenceError("case and fixture IDs must match")
    bindings = _fixture_unit_bindings(fixture, candidate_order=candidate_order)
    locations: list[ExposureUnitLocation] = []
    for unit_id in case.attack_unit_ids:
        matches = bindings.get(unit_id, ())
        if len(matches) != 1:
            raise ExposureEvidenceError(
                "attack unit must map to exactly one non-contradictory location"
            )
        locations.append(matches[0])
    return tuple(locations)


def _fixture_unit_bindings(
    fixture: FixtureCase,
    *,
    candidate_order: tuple[str, ...],
) -> dict[str, tuple[ExposureUnitLocation, ...]]:
    fixture_chunk_ids = tuple(candidate.chunk_id for candidate in fixture.candidates)
    if len(fixture_chunk_ids) != len(set(fixture_chunk_ids)):
        raise ExposureEvidenceError("fixture candidate IDs must be unique")
    if (
        len(candidate_order) != len(fixture_chunk_ids)
        or len(candidate_order) != len(set(candidate_order))
        or set(candidate_order) != set(fixture_chunk_ids)
    ):
        raise ExposureEvidenceError(
            "runtime candidate IDs must exactly match fixture candidates"
        )

    runtime_ranks = {
        chunk_id: candidate_order.index(chunk_id) + 1
        for chunk_id in fixture_chunk_ids
    }
    bindings: dict[str, list[ExposureUnitLocation]] = {}
    candidate_fields: tuple[tuple[str, ExposureSurface], ...] = (
        ("matched_unit_id", "matched"),
        ("context_unit_id", "parent"),
        ("title_unit_id", "title"),
        ("source_path_unit_id", "source_path"),
        ("section_unit_id", "section"),
        ("version_unit_id", "version"),
    )
    for candidate in fixture.candidates:
        for field_name, source_surface in candidate_fields:
            unit_id = getattr(candidate, field_name)
            if unit_id is None:
                continue
            bindings.setdefault(unit_id, []).append(
                ExposureUnitLocation(
                    case_id=fixture.case_id,
                    unit_id=unit_id,
                    location="search_candidate",
                    source_surface=source_surface,
                    candidate_chunk_id=candidate.chunk_id,
                    actual_candidate_rank=runtime_ranks[candidate.chunk_id],
                    candidate_pool_present=True,
                    counterfactual_search_applicable=True,
                )
            )
    for opened in fixture.open_results:
        bindings.setdefault(opened.content_unit_id, []).append(
            ExposureUnitLocation(
                case_id=fixture.case_id,
                unit_id=opened.content_unit_id,
                location="open_result",
                source_surface="open",
                candidate_pool_present=False,
                counterfactual_search_applicable=False,
            )
        )

    frozen_bindings = {
        unit_id: tuple(locations) for unit_id, locations in bindings.items()
    }
    if any(len(locations) != 1 for locations in frozen_bindings.values()):
        raise ExposureEvidenceError("fixture unit has contradictory locations")
    return frozen_bindings


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


class _SourceArmExecution(_StrictFrozenModel):
    protocol_id: Literal["stable_case_hash_rank_counterbalanced_v1"]
    case_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    hash_rank: int = Field(ge=0)
    arm_order: Literal["off_then_on", "on_then_off"]
    execution_index: int = Field(ge=1)
    arm_position: int = Field(strict=True, ge=1, le=2)


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
    arm_execution: _SourceArmExecution
    security: SecurityCaseResult
    live: LiveCaseObservation


@dataclass(frozen=True)
class _ReplayedAdmission:
    operation: Literal["search", "find", "open"]
    outcome: GuardedAdmissionOutcome


@dataclass(frozen=True)
class _RecordedScan:
    operation: Literal["search", "find", "open"]
    event: ScannedContentUnit
    quarantined: bool


def replay_guard_on_case(
    inputs: ExposureInputs,
    *,
    case_id: str,
) -> ReplayedCaseState:
    _verify_replay_guard_ruleset(inputs)
    case, fixture = _replay_case_fixture(inputs, case_id)
    source_row = _replay_source_row(inputs, case_id)
    _validate_replay_source_case(source_row, case)
    locations = map_attack_unit_locations(
        case,
        fixture,
        candidate_order=source_row.security.candidate_order,
    )

    admission = RetrievedContentAdmission(guard=RetrievedContentGuard())
    replayed = _replay_content_operations(
        admission,
        case=case,
        fixture=fixture,
        source_row=source_row,
    )
    if not replayed:
        raise ExposureEvidenceError("replay has no successful content operation")
    if any(not item.outcome.scan_provenance for item in replayed):
        raise ExposureEvidenceError(
            "successful content operation lacks Guard scan provenance"
        )

    scans = _recorded_replay_scans(replayed)
    selected_chunk_ids = {
        item.hit.chunk_id
        for replay in replayed
        if replay.operation == "search"
        and isinstance(replay.outcome.result, GuardedSearchResult)
        for item in replay.outcome.result.hits
    }
    reached_surfaces: dict[str, list[ReplayScanSurface]] = {}
    quarantined_unit_ids: set[str] = set()
    for scan in scans:
        unit_ids = _fixture_units_for_scan(fixture, scan)
        for unit_id in unit_ids:
            surfaces = reached_surfaces.setdefault(unit_id, [])
            if scan.event.surface not in surfaces:
                surfaces.append(scan.event.surface)
            if scan.quarantined:
                quarantined_unit_ids.add(unit_id)

    units = tuple(
        ReplayedUnitState(
            location=location,
            replay_selected_for_evidence=(
                location.location == "search_candidate"
                and location.candidate_chunk_id in selected_chunk_ids
            ),
            replay_guard_reached=location.unit_id in reached_surfaces,
            replay_guard_quarantined=location.unit_id in quarantined_unit_ids,
            replay_scan_surfaces=tuple(reached_surfaces.get(location.unit_id, ())),
        )
        for location in locations
    )
    replay_reached = sum(unit.replay_guard_reached for unit in units)
    replay_quarantined = sum(unit.replay_guard_quarantined for unit in units)
    live_reached = source_row.live.attack_unit_reached_guard_count
    live_quarantined = source_row.live.attack_unit_quarantined_count
    if (replay_reached, replay_quarantined) != (live_reached, live_quarantined):
        raise ExposureEvidenceError("replay/live aggregate mismatch")

    replayed_operations = tuple(item.operation for item in replayed)
    guarded_operation_count = sum(
        bool(item.outcome.scan_provenance) for item in replayed
    )
    if guarded_operation_count != len(replayed_operations):
        raise ExposureEvidenceError("replayed content tool path lacks Guard coverage")
    return ReplayedCaseState(
        case_id=case_id,
        recorded_tool_sequence=source_row.security.tool_sequence,
        replayed_content_operations=replayed_operations,
        consumed_content_operation_count=len(replayed_operations),
        guarded_content_operation_count=guarded_operation_count,
        tool_path_guard_coverage=True,
        live_guard_reached_count=live_reached,
        live_guard_quarantined_count=live_quarantined,
        replay_guard_reached_count=replay_reached,
        replay_guard_quarantined_count=replay_quarantined,
        replay_live_aggregate_match=True,
        units=units,
        replay_scanned_chars=sum(
            item.outcome.security_counters.scanned_chars for item in replayed
        ),
        replay_scanned_surface_count=len(scans),
    )


def _verify_replay_guard_ruleset(inputs: ExposureInputs) -> None:
    guard_path = (
        Path(__file__).resolve().parents[1] / "security" / "retrieved_content.py"
    )
    try:
        actual_sha256 = _sha256(guard_path)
    except OSError as exc:
        raise ExposureEvidenceError("Guard ruleset bytes are unavailable") from exc
    if actual_sha256 != inputs.manifest.guard.ruleset_sha256:
        raise ExposureEvidenceError("Guard ruleset SHA-256 mismatch")


def _replay_case_fixture(
    inputs: ExposureInputs,
    case_id: str,
) -> tuple[IndirectInjectionCase, FixtureCase]:
    cases = tuple(
        case for case in inputs.bundle.dataset.cases if case.case_id == case_id
    )
    fixtures = tuple(
        fixture
        for fixture in inputs.bundle.fixture_manifest.cases
        if fixture.case_id == case_id
    )
    if len(cases) != 1 or len(fixtures) != 1:
        raise ExposureEvidenceError("replay case and fixture must exist exactly once")
    return cases[0], fixtures[0]


def _replay_source_row(inputs: ExposureInputs, case_id: str) -> _SourceArmRow:
    matching_rows: list[Mapping[str, object]] = []
    for row in inputs.guard_on_rows:
        security = row.get("security")
        if isinstance(security, Mapping) and security.get("case_id") == case_id:
            matching_rows.append(row)
    if len(matching_rows) != 1:
        raise ExposureEvidenceError("replay requires exactly one Guard ON source row")
    parsed = _parse_source_arm_row(matching_rows[0])
    if parsed.security.guard_mode != "on" or parsed.live.guard_mode != "on":
        raise ExposureEvidenceError("replay source row must be Guard ON")
    return parsed


def _validate_replay_source_case(
    source_row: _SourceArmRow,
    case: IndirectInjectionCase,
) -> None:
    security = source_row.security
    live = source_row.live
    if (
        security.case_id != case.case_id
        or live.case_id != case.case_id
        or security.attack_unit_ids != case.attack_unit_ids
        or security.benign_unit_ids != case.benign_unit_ids
        or live.attack_unit_count != len(case.attack_unit_ids)
    ):
        raise ExposureEvidenceError("replay source case evidence is inconsistent")


def _replay_content_operations(
    admission: RetrievedContentAdmission,
    *,
    case: IndirectInjectionCase,
    fixture: FixtureCase,
    source_row: _SourceArmRow,
) -> tuple[_ReplayedAdmission, ...]:
    replayed: list[_ReplayedAdmission] = []
    search_count = 0
    open_count = 0
    allowed_non_content = {"answer", "refuse", "stop"}
    for tool in source_row.security.tool_sequence:
        if tool == "search":
            search_count += 1
            if search_count != 1:
                raise ExposureEvidenceError(
                    "multiple recorded searches are not exactly reconstructable"
                )
            request, pool = _replay_search_inputs(
                case,
                fixture,
                candidate_order=source_row.security.candidate_order,
                manifest_sha256=source_row.security.input_fingerprint,
            )
            replayed.append(
                _ReplayedAdmission(
                    operation="search",
                    outcome=admission.admit_search(pool, request),
                )
            )
        elif tool == "open":
            open_count += 1
            if open_count != 1 or len(fixture.open_results) != 1:
                raise ExposureEvidenceError(
                    "recorded open target is not exactly reconstructable"
                )
            replayed.append(
                _ReplayedAdmission(
                    operation="open",
                    outcome=admission.admit_open(
                        _fixture_open_result(fixture, case_id=case.case_id)
                    ),
                )
            )
        elif tool == "find":
            find_result = _fixture_find_error(fixture)
            if not isinstance(find_result, ToolError):
                raise ExposureEvidenceError(
                    "successful find content lacks an exact fixture contract"
                )
        elif tool not in allowed_non_content:
            raise ExposureEvidenceError("recorded tool operation is unsupported")
    if search_count != 1:
        raise ExposureEvidenceError("replay requires one recorded successful search")
    return tuple(replayed)


def _replay_search_inputs(
    case: IndirectInjectionCase,
    fixture: FixtureCase,
    *,
    candidate_order: tuple[str, ...],
    manifest_sha256: str,
) -> tuple[SearchRequest, RankedSearchPool]:
    candidates_by_id = {item.chunk_id: item for item in fixture.candidates}
    if (
        len(candidate_order) != len(candidates_by_id)
        or len(candidate_order) != len(set(candidate_order))
        or set(candidate_order) != set(candidates_by_id)
    ):
        raise ExposureEvidenceError(
            "runtime candidate IDs must exactly match fixture candidates"
        )
    ranked = tuple(
        RankedSearchCandidate(
            rank=runtime_index,
            hit=_search_hit(candidates_by_id[chunk_id]),
            document_title=candidates_by_id[chunk_id].document_title,
        )
        for runtime_index, chunk_id in enumerate(candidate_order, start=1)
    )
    request = SearchRequest(
        request_id=f"{case.case_id}-admission-replay",
        query=case.question,
        purpose="Source-bound deterministic admission replay",
        user=UserContext(
            user_id="synthetic-evaluator",
            tenant_id="synthetic-tenant",
            region="global",
            groups=["synthetic-employees"],
            roles=["knowledge-reader"],
        ),
        top_k=1,
        candidate_k=4,
    )
    candidate_count = len(ranked)
    pool = RankedSearchPool(
        request_id=request.request_id,
        query=request.query,
        mode=request.mode,
        index_run_id="r2-s1-d6-synthetic",
        manifest_sha256=manifest_sha256,
        candidates=ranked,
        visible_candidate_count=candidate_count,
        internal_denied_count=0,
        stage_counts={
            "acl_visible": candidate_count,
            "metadata_visible": candidate_count,
            "bm25_candidates": candidate_count,
            "dense_candidates": candidate_count,
            "fused_candidates": candidate_count,
            "returned": 0,
        },
        stop_reason="ok",
    )
    return request, pool


def _fixture_open_result(fixture: FixtureCase, *, case_id: str) -> OpenResult:
    item = fixture.open_results[0]
    candidate_ids = {candidate.chunk_id for candidate in fixture.candidates}
    parent_ids = {link.parent_chunk_id for link in fixture.parent_links}
    if item.target_id == item.document_id:
        target_type: Literal["chunk", "parent", "document"] = "document"
    elif item.target_id in candidate_ids:
        target_type = "chunk"
    elif item.target_id in parent_ids:
        target_type = "parent"
    else:
        raise ExposureEvidenceError("fixture open target type is not reconstructable")
    return OpenResult(
        request_id=f"{case_id}-admission-replay-open",
        target_type=target_type,
        target_id=item.target_id,
        doc_id=item.document_id,
        content=item.content,
        truncated=False,
        source_path=item.source_path,
        section_path=list(item.section_path),
    )


def _fixture_find_error(fixture: FixtureCase) -> ToolError:
    if getattr(fixture, "find_results", ()):
        raise ExposureEvidenceError(
            "successful find content lacks an exact fixture contract"
        )
    return ToolError(
        code="not_found",
        retryable=False,
        safe_message="Synthetic fixture has no find result.",
    )


def _recorded_replay_scans(
    replayed: tuple[_ReplayedAdmission, ...],
) -> tuple[_RecordedScan, ...]:
    records: list[_RecordedScan] = []
    for replay in replayed:
        events = replay.outcome.scan_provenance
        if any(event.operation != replay.operation for event in events):
            raise ExposureEvidenceError(
                "scan provenance operation does not match replayed operation"
            )
        quarantined_indexes: set[int] = set()
        for summary in replay.outcome.quarantine_summaries:
            matching_indexes = tuple(
                index
                for index, event in enumerate(events)
                if event.internal_item_key == summary.internal_item_key
                and event.surface == summary.field_kind
                and event.disposition == "QUARANTINE"
            )
            if len(matching_indexes) != 1:
                raise ExposureEvidenceError(
                    "quarantine summary lacks exact scan provenance"
                )
            quarantined_indexes.add(matching_indexes[0])
        if any(
            event.disposition == "QUARANTINE" and index not in quarantined_indexes
            for index, event in enumerate(events)
        ):
            raise ExposureEvidenceError(
                "quarantined scan lacks exact quarantine summary"
            )
        records.extend(
            _RecordedScan(
                operation=replay.operation,
                event=event,
                quarantined=index in quarantined_indexes,
            )
            for index, event in enumerate(events)
        )
    return tuple(records)


def _fixture_units_for_scan(
    fixture: FixtureCase,
    scan: _RecordedScan,
) -> tuple[str, ...]:
    candidates = {candidate.chunk_id: candidate for candidate in fixture.candidates}
    opened = {item.target_id: item for item in fixture.open_results}
    unit_ids: list[str] = []
    for internal_id in scan.event.member_internal_ids:
        if scan.operation in {"search", "find"}:
            candidate = candidates.get(internal_id)
            if candidate is None:
                raise ExposureEvidenceError(
                    "scan provenance references an unknown fixture candidate"
                )
            unit_ids.extend(
                _candidate_unit_ids_for_surface(
                    candidate,
                    operation=scan.operation,
                    surface=scan.event.surface,
                )
            )
        elif scan.operation == "open":
            item = opened.get(internal_id)
            if item is None:
                raise ExposureEvidenceError(
                    "scan provenance references an unknown fixture open target"
                )
            if scan.event.surface == "open":
                unit_ids.append(item.content_unit_id)
    return tuple(dict.fromkeys(unit_ids))


def _candidate_unit_ids_for_surface(
    candidate: object,
    *,
    operation: Literal["search", "find"],
    surface: ReplayScanSurface,
) -> tuple[str, ...]:
    if surface in {"matched", "aggregate", "find_preview"}:
        values = (getattr(candidate, "matched_unit_id", None),)
    elif surface == "parent":
        values = (getattr(candidate, "context_unit_id", None),)
    elif surface == "metadata" and operation == "search":
        values = (
            getattr(candidate, "title_unit_id", None),
            getattr(candidate, "source_path_unit_id", None),
            getattr(candidate, "section_unit_id", None),
            getattr(candidate, "version_unit_id", None),
        )
    elif surface == "metadata" and operation == "find":
        values = (getattr(candidate, "section_unit_id", None),)
    else:
        values = ()
    return tuple(value for value in values if isinstance(value, str))


def load_exposure_inputs(
    source_run_dir: Path,
    *,
    security_data_root: Path,
    expected_manifest_sha256: str,
) -> ExposureInputs:
    source_run_dir = Path(source_run_dir).resolve()
    manifest = _verify_source_run(source_run_dir)
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
    try:
        manifest_sha256 = _sha256(source_run_dir / "manifest.json")
    except OSError as exc:
        raise ExposureEvidenceError("source manifest SHA-256 is unavailable") from exc
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
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ExposureEvidenceError("source per-case JSONL is unavailable") from exc
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
        typed_arm_execution = _SourceArmExecution.model_validate(arm_execution)
    except ValidationError as exc:
        raise ExposureEvidenceError("source per-case arm schema is invalid") from exc
    try:
        typed_security = SecurityCaseResult.model_validate_json(
            json.dumps(security, ensure_ascii=False)
        )
        typed_live = LiveCaseObservation.model_validate_json(
            json.dumps(live, ensure_ascii=False)
        )
    except ValidationError as exc:
        raise ExposureEvidenceError("source per-case row schema is invalid") from exc
    return _SourceArmRow(
        raw=row,
        arm_execution=typed_arm_execution,
        security=typed_security,
        live=typed_live,
    )


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
            arm = row.arm_execution
            if (
                arm.protocol_id != manifest.arm_order.protocol_id
                or arm.case_hash != assignment.case_hash
                or arm.hash_rank != assignment.hash_rank
                or arm.arm_order != assignment.arm_order
                or arm.arm_position != arm_position
                or row.security.case_id != assignment.case_id
                or row.live.case_id != assignment.case_id
                or row.security.guard_mode != guard_mode
                or row.live.guard_mode != guard_mode
            ):
                raise ExposureEvidenceError("source arm order contradicts manifest")
            execution_indexes.append(arm.execution_index)
            pair_indexes.append(arm.execution_index)
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


def _verify_source_run(source_run_dir: Path) -> LiveSecurityRunManifest:
    try:
        return verify_live_security_run(source_run_dir)
    except (OSError, ValidationError, ValueError) as exc:
        raise ExposureEvidenceError("source live-run verification failed") from exc


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
    "ExposureLocation",
    "ExposureSourceEvidence",
    "ExposureSurface",
    "ExposureUnitLocation",
    "ReplayScanSurface",
    "SOURCE_GIT_HEAD",
    "SOURCE_GUARD_SHA256",
    "SOURCE_MANIFEST_SHA256",
    "SOURCE_RUN_ID",
    "load_exposure_inputs",
    "map_attack_unit_locations",
]
