from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from app.evaluation import indirect_injection_exposure as exposure
from app.evaluation import indirect_injection_live_writer as live_writer
from app.evaluation.indirect_injection_arm_order import (
    build_counterbalanced_arm_order_plan,
)
from app.evaluation.indirect_injection_dataset import (
    build_v1_bundle,
    load_security_bundle,
)
from app.evaluation.indirect_injection_contracts import (
    FixtureCandidate,
    FixtureCase,
    FixtureParentLink,
)
from app.evaluation.indirect_injection_exposure import (
    ExposureEvidenceError,
    SOURCE_GIT_HEAD,
    SOURCE_GUARD_SHA256,
    SOURCE_RUN_ID,
    load_exposure_inputs,
)
from app.evaluation.indirect_injection_live_index import build_live_fixture_index
from app.evaluation.indirect_injection_live_runner import (
    LiveSecurityConfig,
    evaluate_live_paired,
)
from app.evaluation.indirect_injection_live_writer import (
    LiveSecurityRunManifest,
    LiveSecurityRunManifestV2,
    publish_live_security_run,
    verify_live_security_run,
)
from app.security.retrieved_admission import RetrievedContentAdmission
from app.security.retrieved_admission import _search_metadata
from tests.evaluation.test_indirect_injection_live_runner import (
    BUILD_TIME,
    _StructuredFixtureChat,
    _embedding,
)
from tests.evaluation.test_indirect_injection_live_writer import (
    _forbidden_texts,
    _manifest_v2,
)


FROZEN_AT = "2026-07-18T00:00:00Z"
FREEZE_HEAD = "a" * 40
RANK_TWO_CASE_ID = "r2s1-dev-markup-wrapped-2"
SPLIT_CASE_ID = "r2s1-dev-split-payload-3"
OPEN_CASE_ID = "r2s1-dev-encoded-invisible-2"
PARENT_SANITIZED_CASE_ID = "r2s1-dev-encoded-invisible-1"
METADATA_SANITIZED_CASE_ID = "r2s1-dev-role-impersonation-1"
SOURCE_EVALUATOR_SHA256 = (
    "a5eec5619a5ac9f44357fc6063232dca6021538ca5988aab6ae2f962d9b85958"
)
REPLAY_DEPENDENCY_ROWS = (
    (
        "guard_ruleset",
        "app/security/retrieved_content.py",
        SOURCE_GUARD_SHA256,
    ),
    (
        "retrieved_admission",
        "app/security/retrieved_admission.py",
        "1f835ba3aa79b1450e8ae906946bba019c21b531fce114cd375b094411c88afb",
    ),
    (
        "search_surface_constructor",
        "app/evaluation/indirect_injection_runner.py",
        "c2c5c5e1815d8a77beebb5027384ea58dd3e73b8536533c8d7898d40668ed36c",
    ),
    (
        "source_live_evaluator",
        "app/evaluation/indirect_injection_live_runner.py",
        SOURCE_EVALUATOR_SHA256,
    ),
)


_CANDIDATE_UNIT_FIELDS = (
    "matched_unit_id",
    "context_unit_id",
    "title_unit_id",
    "source_path_unit_id",
    "section_unit_id",
    "version_unit_id",
)


@pytest.fixture(scope="module")
def mapping_cases(
    source_material: tuple[Path, Path],
) -> tuple[object, FixtureCase, object, FixtureCase]:
    _, security_data_root = source_material
    bundle = load_security_bundle(security_data_root, "dev")
    fixtures = {
        fixture.case_id: fixture for fixture in bundle.fixture_manifest.cases
    }
    attack_case = next(
        case
        for case in bundle.dataset.cases
        if (
            case.label == "attack"
            and case.source_surfaces == ("body",)
            and len(case.attack_unit_ids) == 1
            and len(fixtures[case.case_id].candidates) == 2
        )
    )
    open_case = next(
        case
        for case in bundle.dataset.cases
        if case.label == "attack" and case.source_surfaces == ("open_context",)
    )
    return (
        attack_case,
        fixtures[attack_case.case_id],
        open_case,
        fixtures[open_case.case_id],
    )


def _fixture_with_attack_surface(
    attack_case: object,
    fixture_case: FixtureCase,
    *,
    field: str | None,
) -> FixtureCase:
    unit_id = attack_case.attack_unit_ids[0]
    attack_candidate = next(
        candidate
        for candidate in fixture_case.candidates
        if unit_id in candidate.unit_bindings()
    )
    candidate_payload = attack_candidate.model_dump(mode="python")
    for unit_field in _CANDIDATE_UNIT_FIELDS:
        candidate_payload[unit_field] = None
    candidate_payload["context_from_parent"] = False
    candidate_payload["parent_chunk_id"] = None
    if field == "context_unit_id":
        candidate_payload["context_from_parent"] = True
        candidate_payload["parent_chunk_id"] = f"{attack_case.case_id}-parent"
    if field is not None:
        candidate_payload[field] = unit_id
    candidate = FixtureCandidate.model_validate(candidate_payload)
    candidates = tuple(
        candidate if item.chunk_id == candidate.chunk_id else item
        for item in fixture_case.candidates
    )
    parent_links = ()
    if field == "context_unit_id":
        parent_links = (
            FixtureParentLink(
                parent_chunk_id=candidate.parent_chunk_id,
                document_id=candidate.document_id,
                child_chunk_ids=(candidate.chunk_id,),
            ),
        )
    return FixtureCase(
        case_id=fixture_case.case_id,
        candidates=candidates,
        open_results=(),
        parent_links=parent_links,
        fact_texts=fixture_case.fact_texts,
    )


def test_mapping_uses_runtime_candidate_order_not_authored_rank(
    mapping_cases: tuple[object, FixtureCase, object, FixtureCase],
) -> None:
    attack_case, fixture_case, _, _ = mapping_cases
    runtime_order = (
        fixture_case.candidates[1].chunk_id,
        fixture_case.candidates[0].chunk_id,
    )

    locations = exposure.map_attack_unit_locations(
        attack_case,
        fixture_case,
        candidate_order=runtime_order,
    )

    assert locations[0].actual_candidate_rank == 2
    assert locations[0].location == "search_candidate"


@pytest.mark.parametrize(
    ("field", "surface"),
    (
        ("matched_unit_id", "matched"),
        ("context_unit_id", "parent"),
        ("title_unit_id", "title"),
        ("source_path_unit_id", "source_path"),
        ("section_unit_id", "section"),
        ("version_unit_id", "version"),
    ),
)
def test_mapping_covers_every_candidate_id_surface(
    mapping_cases: tuple[object, FixtureCase, object, FixtureCase],
    field: str,
    surface: str,
) -> None:
    attack_case, fixture_case, _, _ = mapping_cases
    fixture = _fixture_with_attack_surface(attack_case, fixture_case, field=field)

    location = exposure.map_attack_unit_locations(
        attack_case,
        fixture,
        candidate_order=tuple(item.chunk_id for item in fixture.candidates),
    )[0]

    assert location.location == "search_candidate"
    assert location.source_surface == surface
    assert location.actual_candidate_rank == 1
    assert location.counterfactual_search_applicable is True


def test_open_unit_has_no_fabricated_search_rank(
    mapping_cases: tuple[object, FixtureCase, object, FixtureCase],
) -> None:
    _, _, open_case, open_fixture = mapping_cases

    location = exposure.map_attack_unit_locations(
        open_case,
        open_fixture,
        candidate_order=tuple(item.chunk_id for item in open_fixture.candidates),
    )[0]

    assert location.location == "open_result"
    assert location.actual_candidate_rank is None
    assert location.counterfactual_search_applicable is False


def test_find_result_location_has_no_runtime_attribution() -> None:
    location = exposure.ExposureUnitLocation(
        case_id="r2s1-dev-instruction-override-1",
        unit_id="find-unit",
        location="find_result",
        source_surface="find",
        candidate_pool_present=False,
        counterfactual_search_applicable=False,
    )

    assert location.candidate_chunk_id is None
    assert location.actual_candidate_rank is None


@pytest.mark.parametrize(
    ("location", "updates", "message"),
    (
        (
            "search_candidate",
            {"source_surface": "open"},
            "search_candidate requires a search source surface",
        ),
        (
            "search_candidate",
            {"candidate_chunk_id": None},
            "search_candidate requires a non-empty candidate_chunk_id",
        ),
        (
            "search_candidate",
            {"candidate_chunk_id": ""},
            "search_candidate requires a non-empty candidate_chunk_id",
        ),
        (
            "search_candidate",
            {"actual_candidate_rank": None},
            "search_candidate requires actual_candidate_rank",
        ),
        (
            "search_candidate",
            {"candidate_pool_present": False},
            "search_candidate requires candidate_pool_present=True",
        ),
        (
            "search_candidate",
            {"counterfactual_search_applicable": False},
            "search_candidate requires counterfactual_search_applicable=True",
        ),
        (
            "open_result",
            {"source_surface": "matched"},
            "open_result requires source_surface=open",
        ),
        (
            "open_result",
            {"candidate_chunk_id": "chunk-1"},
            "open_result requires candidate_chunk_id=None",
        ),
        (
            "open_result",
            {"actual_candidate_rank": 1},
            "open_result requires actual_candidate_rank=None",
        ),
        (
            "open_result",
            {"candidate_pool_present": True},
            "open_result requires candidate_pool_present=False",
        ),
        (
            "open_result",
            {"counterfactual_search_applicable": True},
            "open_result requires counterfactual_search_applicable=False",
        ),
        (
            "find_result",
            {"source_surface": "matched"},
            "find_result requires source_surface=find",
        ),
        (
            "find_result",
            {"candidate_chunk_id": "chunk-1"},
            "find_result requires candidate_chunk_id=None",
        ),
        (
            "find_result",
            {"actual_candidate_rank": 1},
            "find_result requires actual_candidate_rank=None",
        ),
        (
            "find_result",
            {"candidate_pool_present": True},
            "find_result requires candidate_pool_present=False",
        ),
        (
            "find_result",
            {"counterfactual_search_applicable": True},
            "find_result requires counterfactual_search_applicable=False",
        ),
    ),
)
def test_exposure_unit_location_rejects_contradictory_cross_field_state(
    location: str,
    updates: dict[str, object],
    message: str,
) -> None:
    payload: dict[str, object] = {
        "case_id": "r2s1-dev-instruction-override-1",
        "unit_id": "attack-unit",
        "location": location,
        "source_surface": "matched",
        "candidate_chunk_id": "chunk-1",
        "actual_candidate_rank": 1,
        "candidate_pool_present": True,
        "counterfactual_search_applicable": True,
    }
    if location in {"open_result", "find_result"}:
        payload.update(
            source_surface="open" if location == "open_result" else "find",
            candidate_chunk_id=None,
            actual_candidate_rank=None,
            candidate_pool_present=False,
            counterfactual_search_applicable=False,
        )
    payload.update(updates)

    with pytest.raises(ValueError, match=message):
        exposure.ExposureUnitLocation(**payload)


def test_mapping_rejects_one_unit_bound_to_two_primary_locations(
    mapping_cases: tuple[object, FixtureCase, object, FixtureCase],
) -> None:
    attack_case, fixture_case, _, _ = mapping_cases
    unit_id = attack_case.attack_unit_ids[0]
    contradictory_fixture = fixture_case.model_copy(
        update={
            "candidates": (
                fixture_case.candidates[0],
                fixture_case.candidates[1].model_copy(
                    update={"matched_unit_id": unit_id}
                ),
            )
        }
    )

    with pytest.raises(ExposureEvidenceError, match="contradictory locations"):
        exposure.map_attack_unit_locations(
            attack_case,
            contradictory_fixture,
            candidate_order=tuple(
                item.chunk_id for item in contradictory_fixture.candidates
            ),
        )


@pytest.mark.parametrize(
    ("fixture_field", "candidate_order", "message"),
    (
        (None, None, "exactly one non-contradictory location"),
        ("matched_unit_id", ("first", "first"), "runtime candidate IDs"),
        ("matched_unit_id", ("first",), "runtime candidate IDs"),
    ),
)
def test_mapping_fails_closed_for_missing_units_and_candidate_sets(
    mapping_cases: tuple[object, FixtureCase, object, FixtureCase],
    fixture_field: str | None,
    candidate_order: tuple[str, ...] | None,
    message: str,
) -> None:
    attack_case, fixture_case, _, _ = mapping_cases
    fixture = _fixture_with_attack_surface(attack_case, fixture_case, field=fixture_field)
    order = (
        tuple(item.chunk_id for item in fixture.candidates)
        if candidate_order is None
        else tuple(
            fixture.candidates[0].chunk_id if value == "first" else value
            for value in candidate_order
        )
    )

    with pytest.raises(ExposureEvidenceError, match=message):
        exposure.map_attack_unit_locations(
            attack_case,
            fixture,
            candidate_order=order,
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def source_material(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("exposure-source")
    security_data_root = root / "security-data"
    build_v1_bundle(
        security_data_root,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    bundle = load_security_bundle(security_data_root, "dev")
    built = build_live_fixture_index(
        dataset=bundle.dataset,
        fixtures=bundle.fixture_manifest,
        root=root / "security-index",
        run_id="r2-s3-exposure-test-index",
        fixture_sha256=bundle.fixture_manifest_sha256,
        embedding_model="bge-m3",
        embed_text=_embedding,
        started_at=BUILD_TIME,
        finished_at=BUILD_TIME,
    )
    arm_order = build_counterbalanced_arm_order_plan(
        case.case_id for case in bundle.dataset.cases
    )
    result = evaluate_live_paired(
        dataset=bundle.dataset,
        fixtures=bundle.fixture_manifest,
        snapshot=built.snapshot,
        embed_text=_embedding,
        chat_fn=_StructuredFixtureChat(),
        config=LiveSecurityConfig(
            llm_endpoint="http://127.0.0.1:11434/v1",
            chat_model="qwen2.5:3b",
        ),
        clock_ms=lambda: 1_000.0,
        arm_order=arm_order,
    )
    payload = _manifest_v2(bundle, built, result).model_dump(mode="python")
    payload["run_id"] = SOURCE_RUN_ID
    payload["split"] = "dev"
    payload["git"]["head"] = SOURCE_GIT_HEAD
    payload["guard"]["ruleset_sha256"] = SOURCE_GUARD_SHA256
    payload["evaluator"]["path"] = (
        "app/evaluation/indirect_injection_live_runner.py"
    )
    payload["evaluator"]["sha256"] = SOURCE_EVALUATOR_SHA256
    payload["data"]["dataset_sha256"] = bundle.dataset_sha256
    payload["data"]["fixture_manifest_sha256"] = bundle.fixture_manifest_sha256
    manifest = LiveSecurityRunManifestV2.model_validate(payload)
    source_run = publish_live_security_run(
        root / "runs",
        manifest,
        result,
        paired_evidence="safe\n",
        commands="safe\n",
        test_output="safe\n",
        forbidden_texts=_forbidden_texts(bundle),
    )

    assert isinstance(verify_live_security_run(source_run), LiveSecurityRunManifestV2)
    return source_run, security_data_root


@pytest.fixture(scope="module")
def accepted_inputs(
    source_material: tuple[Path, Path],
) -> exposure.ExposureInputs:
    source_run, security_data_root = source_material
    return load_exposure_inputs(
        source_run,
        security_data_root=security_data_root,
        expected_manifest_sha256=_sha256(source_run / "manifest.json"),
    )


@pytest.fixture(scope="module")
def split_case_inputs(
    accepted_inputs: exposure.ExposureInputs,
) -> exposure.ExposureInputs:
    return accepted_inputs


def _mutated_guard_on_inputs(
    inputs: exposure.ExposureInputs,
    *,
    case_id: str,
    security_updates: dict[str, object] | None = None,
    live_updates: dict[str, object] | None = None,
) -> exposure.ExposureInputs:
    rows: list[dict[str, object]] = []
    for source_row in inputs.guard_on_rows:
        row = json.loads(json.dumps(source_row))
        if row["security"]["case_id"] == case_id:
            row["security"].update(security_updates or {})
            row["live"].update(live_updates or {})
        rows.append(row)
    return replace(inputs, guard_on_rows=tuple(rows))


class _MutatingReplayAdmission:
    def __init__(self, mutate_search) -> None:
        self._delegate = RetrievedContentAdmission()
        self._mutate_search = mutate_search

    def admit_search(self, pool, request):
        return self._mutate_search(self._delegate.admit_search(pool, request))

    def admit_open(self, result):
        return self._delegate.admit_open(result)


def _install_replay_admission(
    monkeypatch: pytest.MonkeyPatch,
    mutate_search,
) -> None:
    admission = _MutatingReplayAdmission(mutate_search)
    monkeypatch.setattr(exposure, "_new_replay_admission", lambda: admission)


def test_replay_matches_live_reached_and_quarantined_totals(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    replayed = exposure.replay_guard_on_case(
        accepted_inputs,
        case_id=RANK_TWO_CASE_ID,
    )

    assert replayed.live_guard_reached_count == 0
    assert replayed.live_guard_quarantined_count == 0
    assert replayed.replay_guard_reached_count == 0
    assert replayed.replay_guard_quarantined_count == 0
    assert replayed.replay_live_aggregate_match is True
    assert replayed.units[0].actual_candidate_rank == 2
    assert replayed.units[0].replay_selected_for_evidence is False


def test_split_window_replay_does_not_require_selection(
    split_case_inputs: exposure.ExposureInputs,
) -> None:
    replayed = exposure.replay_guard_on_case(
        split_case_inputs,
        case_id=SPLIT_CASE_ID,
    )

    assert tuple(unit.actual_candidate_rank for unit in replayed.units) == (2, 3)
    assert all(unit.replay_guard_reached for unit in replayed.units)
    assert all(unit.replay_guard_quarantined for unit in replayed.units)
    assert not any(unit.replay_selected_for_evidence for unit in replayed.units)
    assert all("aggregate" in unit.replay_scan_surfaces for unit in replayed.units)


def test_replay_parent_selection_reflects_sanitized_returned_evidence(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    replayed = exposure.replay_guard_on_case(
        accepted_inputs,
        case_id=PARENT_SANITIZED_CASE_ID,
    )

    assert replayed.units[0].location.source_surface == "parent"
    assert replayed.units[0].replay_scan_surfaces == ("parent",)
    assert replayed.units[0].replay_guard_reached is True
    assert replayed.units[0].replay_guard_quarantined is True
    assert replayed.units[0].replay_selected_for_evidence is False


def test_replay_metadata_selection_reflects_sanitized_returned_evidence(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    replayed = exposure.replay_guard_on_case(
        accepted_inputs,
        case_id=METADATA_SANITIZED_CASE_ID,
    )

    assert replayed.units[0].location.source_surface == "title"
    assert replayed.units[0].replay_scan_surfaces == ("metadata",)
    assert replayed.units[0].replay_guard_reached is True
    assert replayed.units[0].replay_guard_quarantined is True
    assert replayed.units[0].replay_selected_for_evidence is False


@pytest.mark.parametrize(
    ("updates", "message"),
    (
        (
            {
                "replay_selected_for_evidence": True,
                "replay_guard_reached": False,
                "replay_guard_quarantined": False,
                "replay_scan_surfaces": (),
            },
            "selected evidence must have reached the Guard",
        ),
        (
            {
                "replay_selected_for_evidence": True,
                "replay_guard_reached": True,
                "replay_guard_quarantined": True,
                "replay_scan_surfaces": ("matched",),
            },
            "quarantined replay unit cannot be selected evidence",
        ),
    ),
)
def test_replayed_unit_rejects_invalid_selected_evidence_state(
    updates: dict[str, object],
    message: str,
) -> None:
    location = exposure.ExposureUnitLocation(
        case_id=RANK_TWO_CASE_ID,
        unit_id="attack-unit",
        location="search_candidate",
        source_surface="matched",
        candidate_chunk_id="attack-chunk",
        actual_candidate_rank=2,
        candidate_pool_present=True,
        counterfactual_search_applicable=True,
    )

    with pytest.raises(ValueError, match=message):
        exposure.ReplayedUnitState(location=location, **updates)


def test_replay_open_unit_is_reached_only_by_recorded_open(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    replayed = exposure.replay_guard_on_case(
        accepted_inputs,
        case_id=OPEN_CASE_ID,
    )

    assert replayed.replayed_content_operations == ("search", "open")
    assert replayed.consumed_content_operation_count == 2
    assert replayed.guarded_content_operation_count == 2
    assert replayed.units[0].location.location == "open_result"
    assert replayed.units[0].actual_candidate_rank is None
    assert replayed.units[0].replay_guard_reached is True
    assert replayed.units[0].replay_selected_for_evidence is False
    assert replayed.units[0].replay_scan_surfaces == ("open",)


def test_replay_recorded_find_tool_error_consumes_no_content(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    inputs = _mutated_guard_on_inputs(
        accepted_inputs,
        case_id=RANK_TWO_CASE_ID,
        security_updates={"tool_sequence": ["search", "find", "answer"]},
    )

    replayed = exposure.replay_guard_on_case(inputs, case_id=RANK_TWO_CASE_ID)

    assert replayed.recorded_tool_sequence == ("search", "find", "answer")
    assert replayed.replayed_content_operations == ("search",)
    assert replayed.consumed_content_operation_count == 1
    assert replayed.guarded_content_operation_count == 1
    assert replayed.replay_scanned_surface_count > 0
    assert all(
        "find_preview" not in unit.replay_scan_surfaces
        for unit in replayed.units
    )


def test_replay_rejects_guard_hash_mismatch(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    guard = accepted_inputs.manifest.guard.model_copy(
        update={"ruleset_sha256": "0" * 64}
    )
    inputs = replace(
        accepted_inputs,
        manifest=accepted_inputs.manifest.model_copy(update={"guard": guard}),
    )

    with pytest.raises(ExposureEvidenceError, match="Guard ruleset SHA-256 mismatch"):
        exposure.replay_guard_on_case(inputs, case_id=RANK_TWO_CASE_ID)


@pytest.mark.parametrize(
    "update",
    (
        {"sha256": "0" * 64},
        {"path": "app/evaluation/indirect_injection_runner.py"},
    ),
)
def test_replay_rejects_evaluator_provenance_mismatch(
    accepted_inputs: exposure.ExposureInputs,
    update: dict[str, object],
) -> None:
    evaluator = accepted_inputs.manifest.evaluator.model_copy(update=update)
    inputs = replace(
        accepted_inputs,
        manifest=accepted_inputs.manifest.model_copy(
            update={"evaluator": evaluator}
        ),
    )

    with pytest.raises(ExposureEvidenceError, match="evaluator provenance mismatch"):
        exposure.replay_guard_on_case(inputs, case_id=RANK_TWO_CASE_ID)


@pytest.mark.parametrize(
    ("dependency_id", "relative_path", "_expected_sha256"),
    REPLAY_DEPENDENCY_ROWS,
)
def test_replay_rejects_mutated_dependency_before_fixture_or_cost_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    accepted_inputs: exposure.ExposureInputs,
    dependency_id: str,
    relative_path: str,
    _expected_sha256: str,
) -> None:
    repository_root = tmp_path / "repository"
    for _item_id, item_path, _item_sha256 in REPLAY_DEPENDENCY_ROWS:
        source = Path(item_path)
        target = repository_root / Path(*item_path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    mutated = repository_root / Path(*relative_path.split("/"))
    mutated.write_bytes(mutated.read_bytes() + b"\n# dependency mutation\n")
    monkeypatch.setattr(
        exposure,
        "_REPLAY_REPOSITORY_ROOT",
        repository_root,
        raising=False,
    )

    def fixture_work_started(*_args, **_kwargs):
        raise AssertionError("fixture/cost work started before dependency verification")

    monkeypatch.setattr(exposure, "_replay_case_fixture", fixture_work_started)

    with pytest.raises(
        ExposureEvidenceError,
        match=rf"replay dependency .*{dependency_id}",
    ):
        exposure.replay_guard_on_case(
            accepted_inputs,
            case_id=RANK_TWO_CASE_ID,
        )


def test_replay_rejects_ambiguous_recorded_open_target(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    fixture = next(
        fixture
        for fixture in accepted_inputs.bundle.fixture_manifest.cases
        if fixture.case_id == OPEN_CASE_ID
    )
    second_open = fixture.open_results[0].model_copy(
        update={
            "target_id": f"{fixture.open_results[0].target_id}-other",
            "content_unit_id": f"{fixture.open_results[0].content_unit_id}-other",
        }
    )
    ambiguous_fixture = fixture.model_copy(
        update={"open_results": (fixture.open_results[0], second_open)}
    )
    fixture_manifest = accepted_inputs.bundle.fixture_manifest.model_copy(
        update={
            "cases": tuple(
                ambiguous_fixture if item.case_id == OPEN_CASE_ID else item
                for item in accepted_inputs.bundle.fixture_manifest.cases
            )
        }
    )
    inputs = replace(
        accepted_inputs,
        bundle=replace(
            accepted_inputs.bundle,
            fixture_manifest=fixture_manifest,
        ),
    )

    with pytest.raises(
        ExposureEvidenceError,
        match="recorded open target is not exactly reconstructable",
    ):
        exposure.replay_guard_on_case(inputs, case_id=OPEN_CASE_ID)


@pytest.mark.parametrize(
    "field",
    ("scanned_content_unit_count", "scanned_chars"),
)
def test_replay_rejects_scan_accounting_mismatch(
    accepted_inputs: exposure.ExposureInputs,
    field: str,
) -> None:
    source_row = next(
        row
        for row in accepted_inputs.guard_on_rows
        if row["security"]["case_id"] == RANK_TWO_CASE_ID
    )
    inputs = _mutated_guard_on_inputs(
        accepted_inputs,
        case_id=RANK_TWO_CASE_ID,
        security_updates={field: source_row["security"][field] + 1},
    )

    with pytest.raises(
        ExposureEvidenceError,
        match="replay/live scan accounting mismatch",
    ):
        exposure.replay_guard_on_case(inputs, case_id=RANK_TWO_CASE_ID)


def test_replay_rejects_successful_content_without_scan_provenance(
    monkeypatch: pytest.MonkeyPatch,
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    _install_replay_admission(
        monkeypatch,
        lambda outcome: outcome.model_copy(update={"scan_provenance": ()}),
    )

    with pytest.raises(
        ExposureEvidenceError,
        match="successful content operation lacks Guard scan provenance",
    ):
        exposure.replay_guard_on_case(accepted_inputs, case_id=RANK_TWO_CASE_ID)


@pytest.mark.parametrize(
    "mutation",
    ("operation_surface", "surface_internal_id", "internal_id"),
)
def test_replay_rejects_unsupported_scan_provenance(
    monkeypatch: pytest.MonkeyPatch,
    accepted_inputs: exposure.ExposureInputs,
    mutation: str,
) -> None:
    def mutate(outcome):
        first = outcome.scan_provenance[0]
        if mutation == "operation_surface":
            invalid = first.model_copy(update={"surface": "open"})
        elif mutation == "surface_internal_id":
            invalid = first.model_copy(update={"surface": "parent"})
        else:
            invalid = first.model_copy(
                update={
                    "internal_item_key": "unknown-fixture-id",
                    "member_internal_ids": ("unknown-fixture-id",),
                }
            )
        return outcome.model_copy(
            update={"scan_provenance": (invalid, *outcome.scan_provenance[1:])}
        )

    _install_replay_admission(monkeypatch, mutate)

    with pytest.raises(ExposureEvidenceError, match="scan provenance"):
        exposure.replay_guard_on_case(accepted_inputs, case_id=RANK_TWO_CASE_ID)


def test_replay_rejects_duplicate_quarantine_summary_for_one_scan(
    monkeypatch: pytest.MonkeyPatch,
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    def duplicate_summary(outcome):
        summary = outcome.quarantine_summaries[0]
        return outcome.model_copy(
            update={
                "quarantine_summaries": (
                    *outcome.quarantine_summaries,
                    summary,
                )
            }
        )

    _install_replay_admission(monkeypatch, duplicate_summary)

    with pytest.raises(
        ExposureEvidenceError,
        match="quarantine summaries must map one-to-one",
    ):
        exposure.replay_guard_on_case(
            accepted_inputs,
            case_id=PARENT_SANITIZED_CASE_ID,
        )


def test_replay_rejects_live_aggregate_mismatch(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    inputs = _mutated_guard_on_inputs(
        accepted_inputs,
        case_id=RANK_TWO_CASE_ID,
        live_updates={"attack_unit_reached_guard_count": 1},
    )

    with pytest.raises(ExposureEvidenceError, match="replay/live aggregate mismatch"):
        exposure.replay_guard_on_case(inputs, case_id=RANK_TWO_CASE_ID)


def _manifest_for_mutation(
    manifest: LiveSecurityRunManifestV2,
    mutation: str,
) -> LiveSecurityRunManifest | LiveSecurityRunManifestV2:
    payload = manifest.model_dump(mode="python")
    if mutation == "v1_schema":
        payload.pop("arm_order")
        payload["schema_version"] = "indirect_injection_live_security_run_manifest_v1"
        payload["mode"] = "local_live_paired"
        return LiveSecurityRunManifest.model_validate(payload)
    if mutation == "test_split":
        payload["split"] = "test"
    elif mutation == "wrong_run_id":
        payload["run_id"] = "r2-s2-s1-dev-20260719-02"
    elif mutation == "wrong_git_head":
        payload["git"]["head"] = "b" * 40
    elif mutation == "wrong_guard_hash":
        payload["guard"]["ruleset_sha256"] = "c" * 64
    return LiveSecurityRunManifestV2.model_validate(payload)


def _mutate_rows(source_run: Path, mutation: str) -> None:
    rows_path = source_run / "per_case.jsonl"
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines()]
    on_indexes = [
        index
        for index, row in enumerate(rows)
        if row["security"]["guard_mode"] == "on"
    ]
    if mutation == "missing_guard_on":
        rows.pop(on_indexes[0])
    elif mutation == "duplicate_case":
        duplicate, original = on_indexes[:2]
        rows[duplicate]["security"]["case_id"] = rows[original]["security"]["case_id"]
        rows[duplicate]["live"]["case_id"] = rows[original]["live"]["case_id"]
    elif mutation == "blocked_egress":
        rows[on_indexes[0]]["live"]["blocked_egress_attempt_count"] = 1
    rows_path.write_bytes(
        (
            "\n".join(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                for row in rows
            )
            + "\n"
        ).encode("utf-8")
    )


def test_load_exposure_inputs_accepts_only_exact_v2_dev_source(
    source_material: tuple[Path, Path],
) -> None:
    exposure_source_run, security_data_root = source_material

    loaded = load_exposure_inputs(
        exposure_source_run,
        security_data_root=security_data_root,
        expected_manifest_sha256=_sha256(exposure_source_run / "manifest.json"),
    )

    assert loaded.manifest.run_id == SOURCE_RUN_ID
    assert loaded.manifest.split == "dev"
    assert len(loaded.guard_on_rows) == 36
    assert len(loaded.guard_off_rows) == 36
    assert loaded.bundle.dataset_sha256 == loaded.manifest.data.dataset_sha256


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("v1_schema", "source run must use live manifest v2"),
        ("test_split", "source run must use dev split"),
        ("wrong_run_id", "source run ID mismatch"),
        ("wrong_git_head", "source Git HEAD mismatch"),
        ("wrong_guard_hash", "source Guard SHA-256 mismatch"),
        ("wrong_manifest_hash", "source manifest SHA-256 mismatch"),
        ("missing_guard_on", "source case/arm set is incomplete"),
        ("duplicate_case", "source case/arm identities must be unique"),
        ("blocked_egress", "source run contains blocked external egress"),
    ],
)
def test_load_exposure_inputs_rejects_invalid_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_material: tuple[Path, Path],
    mutation: str,
    message: str,
) -> None:
    source_run, security_data_root = source_material
    invalid_run = tmp_path / mutation
    shutil.copytree(source_run, invalid_run)
    manifest = verify_live_security_run(source_run)
    assert isinstance(manifest, LiveSecurityRunManifestV2)

    if mutation in {"missing_guard_on", "duplicate_case", "blocked_egress"}:
        _mutate_rows(invalid_run, mutation)
    mutated_manifest = _manifest_for_mutation(manifest, mutation)
    if mutation in {"missing_guard_on", "duplicate_case", "blocked_egress"}:
        mutated_manifest = _manifest_with_current_per_case_evidence(
            mutated_manifest,
            invalid_run,
        )
    monkeypatch.setattr(
        exposure,
        "verify_live_security_run",
        lambda _run_dir: mutated_manifest,
    )

    expected_hash = (
        "0" * 64
        if mutation == "wrong_manifest_hash"
        else _sha256(invalid_run / "manifest.json")
    )
    with pytest.raises(ExposureEvidenceError, match=message):
        load_exposure_inputs(
            invalid_run,
            security_data_root=security_data_root,
            expected_manifest_sha256=expected_hash,
        )


def _copy_source_run(
    tmp_path: Path,
    source_material: tuple[Path, Path],
    name: str,
) -> tuple[Path, Path, LiveSecurityRunManifestV2]:
    source_run, security_data_root = source_material
    copied_run = tmp_path / name
    shutil.copytree(source_run, copied_run)
    manifest = verify_live_security_run(source_run)
    assert isinstance(manifest, LiveSecurityRunManifestV2)
    return copied_run, security_data_root, manifest


def _read_rows(source_run: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (source_run / "per_case.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]


def _write_rows(source_run: Path, rows: list[dict[str, object]]) -> None:
    (source_run / "per_case.jsonl").write_bytes(
        (
            "\n".join(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                for row in rows
            )
            + "\n"
        ).encode("utf-8")
    )


def _refresh_self_consistent_v2_source_run(source_run: Path) -> str:
    manifest_path = source_run / "manifest.json"
    manifest = LiveSecurityRunManifestV2.model_validate_json(
        manifest_path.read_bytes()
    )
    parsed_rows = live_writer._validate_v2_per_case_rows(
        source_run / "per_case.jsonl",
        manifest,
    )
    off_security, on_security, off_live, on_live = parsed_rows
    off_security_summary = live_writer._mode_result(
        "off", off_security
    ).summary
    on_security_summary = live_writer._mode_result("on", on_security).summary
    gate = live_writer._build_behavior_gate(
        manifest.split,
        off_security_summary,
        on_security_summary,
    )
    pair_input_consistent = all(
        off.input_fingerprint == on.input_fingerprint
        and off.nonce_fingerprint == on.nonce_fingerprint
        and off.candidate_order == on.candidate_order
        and off_observation.pair_input_fingerprint
        == on_observation.pair_input_fingerprint
        for off, on, off_observation, on_observation in zip(
            off_security,
            on_security,
            off_live,
            on_live,
        )
    )
    protocol_complete = bool(
        pair_input_consistent
        and all(item.retrieval_completed for item in off_live)
        and all(item.retrieval_completed for item in on_live)
        and all(not item.model_error_codes for item in off_live)
        and all(not item.model_error_codes for item in on_live)
    )
    status = (
        "COMPLETED WITH OBSERVATIONS" if protocol_complete else "FAILED"
    )
    observation = manifest.observation.model_copy(
        update={
            "status": status,
            "protocol_complete": protocol_complete,
            "pair_input_consistent": pair_input_consistent,
            "deterministic_threshold_diagnostic_passed": gate.passed,
        }
    )
    evaluator = manifest.evaluator.model_copy(
        update={"exit_code": 0 if protocol_complete else 1}
    )
    manifest = LiveSecurityRunManifestV2.model_validate(
        {
            **manifest.model_dump(mode="python"),
            "status": status,
            "observation": observation,
            "evaluator": evaluator,
        }
    )
    summary = {
        "schema_version": "indirect_injection_live_paired_result_v2",
        "producer": manifest.producer,
        "run_id": manifest.run_id,
        "split": manifest.split,
        "mode": manifest.mode,
        "status": status,
        "protocol_complete": protocol_complete,
        "pair_input_consistent": pair_input_consistent,
        "embedding": {
            "request_count": manifest.retrieval.embedding_request_count,
            "delegate_call_count": (
                manifest.retrieval.embedding_delegate_call_count
            ),
            "cache_hit_count": manifest.retrieval.embedding_cache_hit_count,
        },
        "guard_off_security": off_security_summary.model_dump(mode="json"),
        "guard_on_security": on_security_summary.model_dump(mode="json"),
        "guard_off_live": live_writer._summarize_live_mode(
            "off",
            off_live,
            off_security,
        ).model_dump(mode="json"),
        "guard_on_live": live_writer._summarize_live_mode(
            "on",
            on_live,
            on_security,
        ).model_dump(mode="json"),
        "deterministic_threshold_diagnostic": gate.model_dump(mode="json"),
        "arm_order": {
            "schema_version": manifest.arm_order.schema_version,
            "protocol_id": manifest.arm_order.protocol_id,
            "hash_algorithm": manifest.arm_order.hash_algorithm,
            "allocation_method": manifest.arm_order.allocation_method,
            "case_count": manifest.arm_order.case_count,
            "off_then_on_count": manifest.arm_order.off_then_on_count,
            "on_then_off_count": manifest.arm_order.on_then_off_count,
        },
    }
    (source_run / "summary.json").write_bytes(live_writer._json_bytes(summary))
    (source_run / "checksums.sha256").write_bytes(
        "".join(
            f"{live_writer._sha256(source_run / name)}  {name}\n"
            for name in live_writer._CHECKSUM_CONTENT_NAMES
        ).encode("utf-8")
    )
    payload = manifest.model_dump(mode="python")
    payload["artifacts"] = {
        name: {
            "path": name,
            "bytes": (source_run / name).stat().st_size,
            "sha256": live_writer._sha256(source_run / name),
        }
        for name in sorted(live_writer._ARTIFACT_NAMES)
    }
    final_manifest = LiveSecurityRunManifestV2.model_validate(payload)
    manifest_path.write_bytes(
        live_writer._json_bytes(final_manifest.model_dump(mode="json"))
    )
    assert verify_live_security_run(source_run) == final_manifest
    return _sha256(manifest_path)


def _copy_writer_generated_source_run(
    tmp_path: Path,
    source_material: tuple[Path, Path],
) -> tuple[Path, Path]:
    source_run, security_data_root = source_material
    copied_run = tmp_path / SOURCE_RUN_ID
    shutil.copytree(source_run, copied_run)
    return copied_run, security_data_root


def _case_id_for_semantic_mutation(
    security_data_root: Path,
    *,
    label: str,
    multiple_candidates: bool = False,
) -> str:
    bundle = load_security_bundle(security_data_root, "dev")
    fixtures = {
        item.case_id: item for item in bundle.fixture_manifest.cases
    }
    return next(
        case.case_id
        for case in bundle.dataset.cases
        if case.label == label
        and (
            not multiple_candidates
            or len(fixtures[case.case_id].candidates) > 1
        )
    )


def _replace_unit_id(
    security: dict[str, object],
    field: str,
) -> None:
    unit_ids = list(security[field])
    original = unit_ids[0]
    replacement = f"{original}-tampered"
    unit_ids[0] = replacement
    outcomes = dict(security["unit_outcomes"])
    outcomes[replacement] = outcomes.pop(original)
    security[field] = unit_ids
    security["unit_outcomes"] = outcomes


def _mutate_semantic_field(
    row: dict[str, object],
    mutation: str,
) -> None:
    security = row["security"]
    if mutation == "label":
        security["label"] = (
            "benign" if security["label"] == "attack" else "attack"
        )
    elif mutation == "category":
        security["category"] = f"{security['category']}_tampered"
    elif mutation == "variant_id":
        security["variant_id"] = (security["variant_id"] % 3) + 1
    elif mutation == "scenario_tags":
        security["scenario_tags"] = [
            *security["scenario_tags"],
            "tampered_scenario",
        ]
    elif mutation == "attack_unit_ids":
        _replace_unit_id(security, "attack_unit_ids")
    elif mutation == "benign_unit_ids":
        _replace_unit_id(security, "benign_unit_ids")
    else:
        raise AssertionError(f"unknown semantic mutation: {mutation}")


@pytest.mark.parametrize("guard_mode", ("off", "on"))
@pytest.mark.parametrize(
    ("mutation", "label"),
    (
        ("label", "benign"),
        ("label", "attack"),
        ("category", "benign"),
        ("category", "attack"),
        ("variant_id", "attack"),
        ("scenario_tags", "attack"),
        ("attack_unit_ids", "attack"),
        ("benign_unit_ids", "benign"),
    ),
)
def test_load_exposure_inputs_rejects_each_arm_semantic_tampering(
    tmp_path: Path,
    source_material: tuple[Path, Path],
    guard_mode: str,
    mutation: str,
    label: str,
) -> None:
    source_run, security_data_root = _copy_writer_generated_source_run(
        tmp_path,
        source_material,
    )
    case_id = _case_id_for_semantic_mutation(
        security_data_root,
        label=label,
    )
    rows = _read_rows(source_run)
    row = next(
        item
        for item in rows
        if item["security"]["case_id"] == case_id
        and item["security"]["guard_mode"] == guard_mode
    )
    _mutate_semantic_field(row, mutation)
    _write_rows(source_run, rows)
    expected_hash = _refresh_self_consistent_v2_source_run(source_run)

    with pytest.raises(ExposureEvidenceError, match="source semantic join failed"):
        load_exposure_inputs(
            source_run,
            security_data_root=security_data_root,
            expected_manifest_sha256=expected_hash,
        )


@pytest.mark.parametrize(
    "mutation",
    ("missing", "extra", "duplicate", "unknown"),
)
def test_load_exposure_inputs_rejects_coherent_candidate_id_tampering(
    tmp_path: Path,
    source_material: tuple[Path, Path],
    mutation: str,
) -> None:
    source_run, security_data_root = _copy_writer_generated_source_run(
        tmp_path,
        source_material,
    )
    case_id = _case_id_for_semantic_mutation(
        security_data_root,
        label="attack",
        multiple_candidates=True,
    )
    rows = _read_rows(source_run)
    for row in rows:
        security = row["security"]
        if security["case_id"] != case_id:
            continue
        candidate_order = list(security["candidate_order"])
        if mutation == "missing":
            candidate_order.pop()
        elif mutation == "extra":
            candidate_order.append(f"{case_id}-extra-candidate")
        elif mutation == "duplicate":
            candidate_order[1] = candidate_order[0]
        else:
            candidate_order[0] = f"{case_id}-unknown-candidate"
        security["candidate_order"] = candidate_order
        row["live"]["retrieval_candidate_count"] = len(candidate_order)
    _write_rows(source_run, rows)
    expected_hash = _refresh_self_consistent_v2_source_run(source_run)

    with pytest.raises(ExposureEvidenceError, match="source semantic join failed"):
        load_exposure_inputs(
            source_run,
            security_data_root=security_data_root,
            expected_manifest_sha256=expected_hash,
        )


def test_load_exposure_inputs_rejects_semantic_arm_disagreement(
    tmp_path: Path,
    source_material: tuple[Path, Path],
) -> None:
    source_run, security_data_root = _copy_writer_generated_source_run(
        tmp_path,
        source_material,
    )
    rows = _read_rows(source_run)
    on_row = next(
        row for row in rows if row["security"]["guard_mode"] == "on"
    )
    on_row["security"]["category"] = "arm_disagreement"
    _write_rows(source_run, rows)
    expected_hash = _refresh_self_consistent_v2_source_run(source_run)

    with pytest.raises(ExposureEvidenceError, match="source semantic join failed"):
        load_exposure_inputs(
            source_run,
            security_data_root=security_data_root,
            expected_manifest_sha256=expected_hash,
        )


def test_load_exposure_inputs_joins_all_cases_and_both_arms(
    source_material: tuple[Path, Path],
) -> None:
    source_run, security_data_root = source_material
    loaded = load_exposure_inputs(
        source_run,
        security_data_root=security_data_root,
        expected_manifest_sha256=_sha256(source_run / "manifest.json"),
    )
    dataset = {item.case_id: item for item in loaded.bundle.dataset.cases}
    fixtures = {
        item.case_id: item
        for item in loaded.bundle.fixture_manifest.cases
    }
    joined = 0
    for raw in (*loaded.guard_off_rows, *loaded.guard_on_rows):
        security = raw["security"]
        case = dataset[security["case_id"]]
        fixture = fixtures[case.case_id]
        assert security["label"] == case.label
        assert security["category"] == case.category
        assert security["variant_id"] == case.variant_id
        assert tuple(security["scenario_tags"]) == case.scenario_tags
        assert tuple(security["attack_unit_ids"]) == case.attack_unit_ids
        assert tuple(security["benign_unit_ids"]) == case.benign_unit_ids
        assert len(security["candidate_order"]) == len(
            set(security["candidate_order"])
        )
        assert set(security["candidate_order"]) == {
            item.chunk_id for item in fixture.candidates
        }
        joined += 1
    assert joined == 72


@pytest.mark.parametrize("mutation", ("missing", "malformed", "misaligned"))
def test_load_exposure_inputs_normalizes_security_bundle_failures(
    tmp_path: Path,
    source_material: tuple[Path, Path],
    mutation: str,
) -> None:
    source_run, security_data_root = source_material
    bundle_root = tmp_path / "security-data"
    if mutation != "missing":
        shutil.copytree(security_data_root, bundle_root)
    if mutation == "malformed":
        (bundle_root / "indirect_injection_dev_v1.json").write_bytes(
            b"not-json\n"
        )
    elif mutation == "misaligned":
        fixture_path = bundle_root / "fixtures_v1" / "dev" / "manifest.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        candidate = fixture["cases"][0]["candidates"][0]
        field = next(
            name
            for name in _CANDIDATE_UNIT_FIELDS
            if candidate.get(name) is not None
        )
        candidate[field] = f"{candidate[field]}-misaligned"
        fixture_path.write_text(
            json.dumps(fixture, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
            newline="",
        )

    with pytest.raises(
        ExposureEvidenceError,
        match="source security bundle loading failed",
    ) as caught:
        load_exposure_inputs(
            source_run,
            security_data_root=bundle_root,
            expected_manifest_sha256=_sha256(source_run / "manifest.json"),
        )
    assert isinstance(caught.value.__cause__, (OSError, ValueError))


def test_load_exposure_inputs_normalizes_unreadable_security_bundle(
    monkeypatch: pytest.MonkeyPatch,
    source_material: tuple[Path, Path],
) -> None:
    source_run, security_data_root = source_material
    dataset_path = (
        security_data_root / "indirect_injection_dev_v1.json"
    ).resolve()
    read_bytes = Path.read_bytes

    def deny_dataset_read(path: Path) -> bytes:
        if path.resolve() == dataset_path:
            raise PermissionError("denied")
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", deny_dataset_read)

    with pytest.raises(
        ExposureEvidenceError,
        match="source security bundle loading failed",
    ) as caught:
        load_exposure_inputs(
            source_run,
            security_data_root=security_data_root,
            expected_manifest_sha256=_sha256(source_run / "manifest.json"),
        )
    assert isinstance(caught.value.__cause__, PermissionError)


@pytest.mark.parametrize("exception_type", (RuntimeError, TypeError))
def test_load_exposure_inputs_does_not_normalize_programmer_errors(
    monkeypatch: pytest.MonkeyPatch,
    source_material: tuple[Path, Path],
    exception_type: type[Exception],
) -> None:
    source_run, security_data_root = source_material

    def fail_bundle_load(_root: Path, _split: str) -> None:
        raise exception_type("programmer defect")

    monkeypatch.setattr(exposure, "load_security_bundle", fail_bundle_load)

    with pytest.raises(exception_type, match="programmer defect"):
        load_exposure_inputs(
            source_run,
            security_data_root=security_data_root,
            expected_manifest_sha256=_sha256(source_run / "manifest.json"),
        )


def _load_with_manifest(
    monkeypatch: pytest.MonkeyPatch,
    source_run: Path,
    security_data_root: Path,
    manifest: LiveSecurityRunManifestV2,
) -> None:
    manifest = _manifest_with_current_per_case_evidence(manifest, source_run)
    monkeypatch.setattr(
        exposure,
        "verify_live_security_run",
        lambda _run_dir: manifest,
    )
    load_exposure_inputs(
        source_run,
        security_data_root=security_data_root,
        expected_manifest_sha256=_sha256(source_run / "manifest.json"),
    )


def _manifest_with_current_per_case_evidence(
    manifest: LiveSecurityRunManifest | LiveSecurityRunManifestV2,
    source_run: Path,
) -> LiveSecurityRunManifest | LiveSecurityRunManifestV2:
    rows = (source_run / "per_case.jsonl").read_bytes()
    artifacts = dict(manifest.artifacts)
    artifacts["per_case.jsonl"] = artifacts["per_case.jsonl"].model_copy(
        update={
            "bytes": len(rows),
            "sha256": hashlib.sha256(rows).hexdigest(),
        }
    )
    return manifest.model_copy(update={"artifacts": artifacts})


@pytest.mark.parametrize("mutation", ("missing_manifest", "corrupt_manifest"))
def test_load_exposure_inputs_normalizes_manifest_boundary_failures(
    tmp_path: Path,
    source_material: tuple[Path, Path],
    mutation: str,
) -> None:
    source_run, security_data_root, _ = _copy_source_run(
        tmp_path,
        source_material,
        mutation,
    )
    manifest_path = source_run / "manifest.json"
    expected_hash = _sha256(manifest_path)
    if mutation == "missing_manifest":
        manifest_path.unlink()
    else:
        manifest_path.write_bytes(b"not-json\n")

    with pytest.raises(
        ExposureEvidenceError,
        match="source live-run verification failed",
    ):
        load_exposure_inputs(
            source_run,
            security_data_root=security_data_root,
            expected_manifest_sha256=expected_hash,
        )


def test_load_exposure_inputs_normalizes_verifier_failure(
    monkeypatch: pytest.MonkeyPatch,
    source_material: tuple[Path, Path],
) -> None:
    source_run, security_data_root = source_material

    def fail_verification(_run_dir: Path) -> LiveSecurityRunManifestV2:
        raise ValueError("corrupt source evidence")

    monkeypatch.setattr(exposure, "verify_live_security_run", fail_verification)

    with pytest.raises(
        ExposureEvidenceError,
        match="source live-run verification failed",
    ):
        load_exposure_inputs(
            source_run,
            security_data_root=security_data_root,
            expected_manifest_sha256=_sha256(source_run / "manifest.json"),
        )


@pytest.mark.parametrize("mutation", ("missing_rows", "unreadable_rows"))
def test_load_exposure_inputs_normalizes_per_case_file_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_material: tuple[Path, Path],
    mutation: str,
) -> None:
    source_run, security_data_root, manifest = _copy_source_run(
        tmp_path,
        source_material,
        mutation,
    )
    rows_path = source_run / "per_case.jsonl"
    monkeypatch.setattr(exposure, "verify_live_security_run", lambda _run_dir: manifest)
    if mutation == "missing_rows":
        rows_path.unlink()
    else:
        read_bytes = Path.read_bytes

        def deny_per_case_read(path: Path) -> bytes:
            if path == rows_path:
                raise PermissionError("denied")
            return read_bytes(path)

        monkeypatch.setattr(Path, "read_bytes", deny_per_case_read)

    with pytest.raises(
        ExposureEvidenceError,
        match="source per-case JSONL is unavailable",
    ):
        load_exposure_inputs(
            source_run,
            security_data_root=security_data_root,
            expected_manifest_sha256=_sha256(source_run / "manifest.json"),
        )


def test_load_exposure_inputs_rejects_per_case_mutation_after_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_material: tuple[Path, Path],
) -> None:
    source_run, security_data_root, verified_manifest = _copy_source_run(
        tmp_path,
        source_material,
        "post-verification-mutation",
    )
    manifest_sha256 = _sha256(source_run / "manifest.json")

    def verify_then_mutate(run_dir: Path) -> LiveSecurityRunManifestV2:
        rows_path = run_dir / "per_case.jsonl"
        original = rows_path.read_bytes()
        rows = [
            json.loads(line)
            for line in original.decode("utf-8").splitlines()
        ]
        row = next(
            item
            for item in rows
            if item["security"]["guard_mode"] == "on"
            and item["security"]["label"] == "benign"
        )
        case_id = row["security"]["case_id"]
        fingerprint = row["security"]["nonce_fingerprint"]
        replacement = ("0" if fingerprint[0] != "0" else "1") + fingerprint[1:]
        for item in rows:
            if item["security"]["case_id"] == case_id:
                item["security"]["nonce_fingerprint"] = replacement
        mutated = b"".join(
            json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
            for item in rows
        )
        assert len(mutated) == len(original)
        rows_path.write_bytes(mutated)
        return verified_manifest

    monkeypatch.setattr(exposure, "verify_live_security_run", verify_then_mutate)

    with pytest.raises(
        ExposureEvidenceError,
        match="source per-case artifact evidence mismatch",
    ):
        load_exposure_inputs(
            source_run,
            security_data_root=security_data_root,
            expected_manifest_sha256=manifest_sha256,
        )


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("dataset_sha256", "source dataset SHA-256 mismatch"),
        ("fixture_manifest_sha256", "source fixture SHA-256 mismatch"),
    ],
)
def test_load_exposure_inputs_rejects_data_provenance_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    source_material: tuple[Path, Path],
    field: str,
    message: str,
) -> None:
    source_run, security_data_root = source_material
    manifest = verify_live_security_run(source_run)
    assert isinstance(manifest, LiveSecurityRunManifestV2)
    data = manifest.data.model_copy(update={field: "0" * 64})
    invalid_manifest = manifest.model_copy(update={"data": data})

    with pytest.raises(ExposureEvidenceError, match=message):
        _load_with_manifest(
            monkeypatch,
            source_run,
            security_data_root,
            invalid_manifest,
        )


def test_load_exposure_inputs_rejects_invalid_arm_allocation(
    monkeypatch: pytest.MonkeyPatch,
    source_material: tuple[Path, Path],
) -> None:
    source_run, security_data_root = source_material
    manifest = verify_live_security_run(source_run)
    assert isinstance(manifest, LiveSecurityRunManifestV2)
    arm_order = manifest.arm_order.model_copy(update={"off_then_on_count": 17})
    invalid_manifest = manifest.model_copy(update={"arm_order": arm_order})

    with pytest.raises(ExposureEvidenceError, match="source arm allocation is invalid"):
        _load_with_manifest(
            monkeypatch,
            source_run,
            security_data_root,
            invalid_manifest,
        )


def test_load_exposure_inputs_rejects_boolean_arm_hash_rank(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_material: tuple[Path, Path],
) -> None:
    source_run, security_data_root, manifest = _copy_source_run(
        tmp_path,
        source_material,
        "boolean-arm-rank",
    )
    rows = _read_rows(source_run)
    row = next(row for row in rows if row["arm_execution"]["hash_rank"] == 1)
    row["arm_execution"]["hash_rank"] = True
    _write_rows(source_run, rows)

    with pytest.raises(
        ExposureEvidenceError,
        match="source per-case arm schema is invalid",
    ):
        _load_with_manifest(monkeypatch, source_run, security_data_root, manifest)


def test_load_exposure_inputs_rejects_boolean_arm_position(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_material: tuple[Path, Path],
) -> None:
    source_run, security_data_root, manifest = _copy_source_run(
        tmp_path,
        source_material,
        "boolean-arm-position",
    )
    rows = _read_rows(source_run)
    row = next(row for row in rows if row["arm_execution"]["arm_position"] == 1)
    row["arm_execution"]["arm_position"] = True
    _write_rows(source_run, rows)

    with pytest.raises(
        ExposureEvidenceError,
        match="source per-case arm schema is invalid",
    ):
        _load_with_manifest(monkeypatch, source_run, security_data_root, manifest)


def test_load_exposure_inputs_rejects_arm_order_inconsistency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_material: tuple[Path, Path],
) -> None:
    source_run, security_data_root, manifest = _copy_source_run(
        tmp_path,
        source_material,
        "arm-order",
    )
    rows = _read_rows(source_run)
    arm = rows[0]["arm_execution"]
    arm["arm_order"] = (
        "on_then_off" if arm["arm_order"] == "off_then_on" else "off_then_on"
    )
    _write_rows(source_run, rows)

    with pytest.raises(ExposureEvidenceError, match="source arm order contradicts manifest"):
        _load_with_manifest(monkeypatch, source_run, security_data_root, manifest)


def test_load_exposure_inputs_rejects_arm_index_inconsistency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_material: tuple[Path, Path],
) -> None:
    source_run, security_data_root, manifest = _copy_source_run(
        tmp_path,
        source_material,
        "arm-index",
    )
    rows = _read_rows(source_run)
    rows[-2]["arm_execution"]["execution_index"] = rows[0]["arm_execution"][
        "execution_index"
    ]
    rows[-1]["arm_execution"]["execution_index"] = rows[1]["arm_execution"][
        "execution_index"
    ]
    _write_rows(source_run, rows)

    with pytest.raises(
        ExposureEvidenceError,
        match="source arm execution indexes are not exact",
    ):
        _load_with_manifest(monkeypatch, source_run, security_data_root, manifest)


def test_load_exposure_inputs_rejects_pair_inconsistency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_material: tuple[Path, Path],
) -> None:
    source_run, security_data_root, manifest = _copy_source_run(
        tmp_path,
        source_material,
        "pair-inconsistency",
    )
    rows = _read_rows(source_run)
    on_row = next(row for row in rows if row["security"]["guard_mode"] == "on")
    on_row["security"]["nonce_fingerprint"] = "0" * 64
    _write_rows(source_run, rows)

    with pytest.raises(ExposureEvidenceError, match="source paired inputs are inconsistent"):
        _load_with_manifest(monkeypatch, source_run, security_data_root, manifest)


def test_load_exposure_inputs_rejects_incomplete_protocol(
    monkeypatch: pytest.MonkeyPatch,
    source_material: tuple[Path, Path],
) -> None:
    source_run, security_data_root = source_material
    manifest = verify_live_security_run(source_run)
    assert isinstance(manifest, LiveSecurityRunManifestV2)
    observation = manifest.observation.model_copy(update={"protocol_complete": False})
    invalid_manifest = manifest.model_copy(update={"observation": observation})

    with pytest.raises(ExposureEvidenceError, match="source run protocol is incomplete"):
        _load_with_manifest(
            monkeypatch,
            source_run,
            security_data_root,
            invalid_manifest,
        )


def test_load_exposure_inputs_rejects_model_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_material: tuple[Path, Path],
) -> None:
    source_run, security_data_root, manifest = _copy_source_run(
        tmp_path,
        source_material,
        "model-errors",
    )
    rows = _read_rows(source_run)
    live = rows[0]["live"]
    live["model_call_count"] += 1
    live["model_error_codes"] = ["synthetic_model_error"]
    _write_rows(source_run, rows)

    with pytest.raises(ExposureEvidenceError, match="source run contains model errors"):
        _load_with_manifest(monkeypatch, source_run, security_data_root, manifest)


def test_load_exposure_inputs_rejects_guard_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_material: tuple[Path, Path],
) -> None:
    source_run, security_data_root, manifest = _copy_source_run(
        tmp_path,
        source_material,
        "guard-errors",
    )
    rows = _read_rows(source_run)
    rows[0]["security"]["guard_error_count"] = 1
    _write_rows(source_run, rows)

    with pytest.raises(ExposureEvidenceError, match="source run contains Guard errors"):
        _load_with_manifest(monkeypatch, source_run, security_data_root, manifest)


def _expected_counterfactual_sets(
    inputs: exposure.ExposureInputs,
) -> tuple[set[str], dict[int, set[str]], dict[int, set[str]]]:
    replay_reached: set[str] = set()
    search_reached = {depth: set() for depth in exposure.COUNTERFACTUAL_DEPTHS}
    search_addressable: set[str] = set()
    fixtures = {
        fixture.case_id: fixture
        for fixture in inputs.bundle.fixture_manifest.cases
    }
    for case in inputs.bundle.dataset.cases:
        if case.label != "attack":
            continue
        source_row = exposure._replay_source_row(inputs, case.case_id)
        locations = exposure.map_attack_unit_locations(
            case,
            fixtures[case.case_id],
            candidate_order=source_row.security.candidate_order,
        )
        replayed = exposure.replay_guard_on_case(inputs, case_id=case.case_id)
        replay_reached.update(
            unit.location.unit_id
            for unit in replayed.units
            if unit.replay_guard_reached
        )
        for location in locations:
            if not location.counterfactual_search_applicable:
                continue
            search_addressable.add(location.unit_id)
            for depth in exposure.COUNTERFACTUAL_DEPTHS:
                if location.actual_candidate_rank <= depth:
                    search_reached[depth].add(location.unit_id)
    total_reached = {
        depth: replay_reached | search_reached[depth]
        for depth in exposure.COUNTERFACTUAL_DEPTHS
    }
    return search_addressable, search_reached, total_reached


def _expected_case_counterfactual_costs(
    inputs: exposure.ExposureInputs,
    case_id: str,
) -> dict[int, tuple[int, int]]:
    case, fixture = exposure._replay_case_fixture(inputs, case_id)
    source_row = exposure._replay_source_row(inputs, case_id)
    replayed = exposure._replay_content_operations(
        exposure._new_replay_admission(),
        case=case,
        fixture=fixture,
        source_row=source_row,
        evaluator_sha256=inputs.manifest.evaluator.sha256,
    )
    replay_scan_keys = {
        (case_id, item.operation, event.internal_item_key, event.surface)
        for item in replayed
        for event in item.outcome.scan_provenance
    }
    _, pool = exposure._replay_search_inputs(
        case,
        fixture,
        candidate_order=source_row.security.candidate_order,
        manifest_sha256=source_row.security.input_fingerprint,
    )
    guard = exposure.RetrievedContentGuard()
    attempted: dict[tuple[str, str, str, str], tuple[int, int]] = {}
    for candidate in pool.candidates:
        surfaces = [("matched", candidate.hit.matched_text)]
        if (
            candidate.hit.context_from_parent
            and candidate.hit.context_text != candidate.hit.matched_text
        ):
            surfaces.append(("parent", candidate.hit.context_text))
        surfaces.append(("metadata", _search_metadata(candidate)))
        for surface, scan_input in surfaces:
            key = (case_id, "search", candidate.hit.chunk_id, surface)
            if key in attempted:
                continue
            attempted[key] = (candidate.rank, guard.scan(scan_input).scanned_length)

    return {
        depth: (
            sum(
                key not in replay_scan_keys and rank <= depth
                for key, (rank, _) in attempted.items()
            ),
            sum(
                scanned_length
                for key, (rank, scanned_length) in attempted.items()
                if key not in replay_scan_keys and rank <= depth
            ),
        )
        for depth in exposure.COUNTERFACTUAL_DEPTHS
    }


def _case_cost(row: object, depth: int) -> tuple[int, int]:
    return (
        getattr(row, f"case_replay_additional_scan_units_at_{depth}"),
        getattr(row, f"case_replay_additional_scan_input_chars_at_{depth}"),
    )


def test_counterfactual_depths_follow_persisted_rank_and_exclude_open_from_search(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    search_addressable, search_reached, total_reached = (
        _expected_counterfactual_sets(accepted_inputs)
    )

    assert exposure.COUNTERFACTUAL_DEPTHS == (1, 2, 4)
    assert len(search_addressable) < result.summary.attack_unit_count
    for depth in exposure.COUNTERFACTUAL_DEPTHS:
        item = result.summary.depth(depth)
        assert item.counterfactual_search_reach == exposure.ExposureMetric.from_counts(
            len(search_reached[depth]),
            len(search_addressable),
        )
        assert item.counterfactual_total_reach == exposure.ExposureMetric.from_counts(
            len(total_reached[depth]),
            result.summary.attack_unit_count,
        )
def test_counterfactual_total_reach_is_a_unit_union_without_double_counting(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    _, _, total_reached = _expected_counterfactual_sets(accepted_inputs)

    for depth in exposure.COUNTERFACTUAL_DEPTHS:
        metric = result.summary.depth(depth).counterfactual_total_reach
        assert metric.numerator == len(total_reached[depth])
        assert metric.numerator <= metric.denominator


def test_result_rejects_naively_double_counted_counterfactual_total_reach(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    payload = result.model_dump(mode="python")
    depth_1 = payload["summary"]["depths"][0]
    metric = result.summary.depth(1).counterfactual_total_reach
    assert metric.numerator < metric.denominator
    depth_1["counterfactual_total_reach"] = (
        exposure.ExposureMetric.from_counts(
            metric.numerator + 1,
            metric.denominator,
        ).model_dump(mode="python")
    )

    with pytest.raises(
        ValueError,
        match="analysis summary does not recompute",
    ):
        exposure.ExposureAnalysisResult.model_validate(payload)


def test_result_rejects_counterfactual_search_numerator_not_derived_from_rows(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    payload = result.model_dump(mode="python")
    depth_1 = payload["summary"]["depths"][0]
    metric = result.summary.depth(1).counterfactual_search_reach
    depth_1["counterfactual_search_reach"] = (
        exposure.ExposureMetric.from_counts(
            metric.numerator + 1,
            metric.denominator,
        ).model_dump(mode="python")
    )

    with pytest.raises(
        ValueError,
        match="analysis summary does not recompute",
    ):
        exposure.ExposureAnalysisResult.model_validate(payload)


def test_result_rejects_counterfactual_search_denominator_not_derived_from_rows(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    payload = result.model_dump(mode="python")
    summary = payload["summary"]
    forged_count = result.summary.search_addressable_attack_unit_count + 1
    summary["search_addressable_attack_unit_count"] = forged_count
    summary["candidate_pool_presence"] = exposure.ExposureMetric.from_counts(
        forged_count,
        result.summary.attack_unit_count,
    ).model_dump(mode="python")
    for depth in summary["depths"]:
        metric = depth["counterfactual_search_reach"]
        depth["counterfactual_search_reach"] = exposure.ExposureMetric.from_counts(
            metric["numerator"],
            forged_count,
        ).model_dump(mode="python")

    with pytest.raises(
        ValueError,
        match="analysis summary does not recompute",
    ):
        exposure.ExposureAnalysisResult.model_validate(payload)


def test_counterfactual_cost_uses_guard_scanned_length_and_replay_scan_keys(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    rows_by_case: dict[str, list[object]] = {}
    for row in result.units:
        rows_by_case.setdefault(row.case_id, []).append(row)

    for case_id in (RANK_TWO_CASE_ID, SPLIT_CASE_ID, METADATA_SANITIZED_CASE_ID):
        expected = _expected_case_counterfactual_costs(accepted_inputs, case_id)
        row = rows_by_case[case_id][0]
        assert {
            depth: _case_cost(row, depth)
            for depth in exposure.COUNTERFACTUAL_DEPTHS
        } == expected


def test_counterfactual_combined_metadata_is_one_attempt_for_several_unit_ids(
    mapping_cases: tuple[object, FixtureCase, object, FixtureCase],
) -> None:
    _, fixture, _, _ = mapping_cases
    payload = fixture.candidates[0].model_dump(mode="python")
    for field in _CANDIDATE_UNIT_FIELDS:
        payload[field] = None
    payload["title_unit_id"] = "synthetic-title-unit"
    payload["section_unit_id"] = "synthetic-section-unit"
    candidate = FixtureCandidate.model_validate(payload)
    ranked = exposure.RankedSearchCandidate(
        rank=1,
        hit=exposure._search_hit(candidate),
        document_title=candidate.document_title,
    )

    attempts = exposure._counterfactual_candidate_scan_inputs(
        "synthetic-case",
        ranked,
    )

    assert [key[3] for key, _ in attempts].count("metadata") == 1
    assert next(value for key, value in attempts if key[3] == "metadata") == (
        _search_metadata(ranked)
    )


def test_counterfactual_two_unit_case_cost_repeats_but_aggregates_once(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    split_rows = [row for row in result.units if row.case_id == SPLIT_CASE_ID]
    assert len(split_rows) == 2
    assert all(
        _case_cost(split_rows[0], depth) == _case_cost(split_rows[1], depth)
        for depth in exposure.COUNTERFACTUAL_DEPTHS
    )

    one_row_by_case = {row.case_id: row for row in result.units}
    for depth in exposure.COUNTERFACTUAL_DEPTHS:
        assert result.summary.depth(depth).replay_additional_scan_units == sum(
            _case_cost(row, depth)[0] for row in one_row_by_case.values()
        )
        assert result.summary.depth(depth).replay_additional_scan_input_chars == sum(
            _case_cost(row, depth)[1] for row in one_row_by_case.values()
        )


def test_counterfactual_summary_rejects_disagreeing_repeated_case_costs(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    rows = list(result.units)
    split_indexes = [
        index for index, row in enumerate(rows) if row.case_id == SPLIT_CASE_ID
    ]
    payload = rows[split_indexes[1]].model_dump(mode="python")
    payload["case_replay_additional_scan_units_at_4"] += 1
    rows[split_indexes[1]] = exposure.ExposureUnitObservation.model_validate(payload)

    with pytest.raises(
        ExposureEvidenceError,
        match="inconsistent repeated case costs",
    ):
        exposure._build_exposure_summary(accepted_inputs, tuple(rows))


def test_counterfactual_unit_rejects_quarantined_but_unreached_state(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    row = next(item for item in result.units if not item.replay_guard_reached)
    payload = row.model_dump(mode="python")
    payload["replay_guard_quarantined"] = True

    with pytest.raises(ValueError, match="quarantine requires Guard reach"):
        exposure.ExposureUnitObservation.model_validate(payload)


def test_counterfactual_unit_rejects_non_monotonic_case_costs(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    row = exposure.analyze_exposure(accepted_inputs).units[0]
    payload = row.model_dump(mode="python")
    payload["case_replay_additional_scan_units_at_1"] = (
        payload["case_replay_additional_scan_units_at_2"] + 1
    )

    with pytest.raises(
        ValueError,
        match="case additional scan units must be monotonic",
    ):
        exposure.ExposureUnitObservation.model_validate(payload)


def test_counterfactual_summary_rechecks_non_monotonic_case_costs(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    rows = list(result.units)
    index = next(
        index for index, row in enumerate(rows) if row.case_id == RANK_TWO_CASE_ID
    )
    rows[index] = rows[index].model_copy(
        update={
            "case_replay_additional_scan_units_at_1": (
                result.summary.depth(2).replay_additional_scan_units + 1
            )
        }
    )

    with pytest.raises(
        ExposureEvidenceError,
        match="case additional scan units must be monotonic",
    ):
        exposure._build_exposure_summary(accepted_inputs, tuple(rows))


def test_counterfactual_metric_rejects_malformed_rate() -> None:
    with pytest.raises(ValueError, match="metric rate does not match"):
        exposure.ExposureMetric(
            numerator=1,
            denominator=2,
            rate=0.75,
            applicable=True,
        )


def test_summary_rejects_conditional_quarantine_numerator_mismatch(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    summary = exposure.analyze_exposure(accepted_inputs).summary
    payload = summary.model_dump(mode="python")
    assert summary.live_guard_quarantine.numerator > 0
    payload["quarantine_given_live_guard_reach"] = (
        exposure.ExposureMetric.from_counts(
            0,
            summary.live_guard_reach.numerator,
        ).model_dump(mode="python")
    )

    with pytest.raises(ValueError, match="conditional quarantine numerator mismatch"):
        exposure.ExposureSummary.model_validate(payload)


def test_summary_rejects_unreached_attack_success_above_downstream_exposure(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    summary = exposure.analyze_exposure(accepted_inputs).summary
    payload = summary.model_dump(mode="python")
    assert summary.unreached_case_count > 0
    assert summary.unreached_case_downstream_exposure.numerator == 0
    payload["unreached_case_attack_success"] = (
        exposure.ExposureMetric.from_counts(
            1,
            summary.unreached_case_count,
        ).model_dump(mode="python")
    )

    with pytest.raises(
        ValueError,
        match="unreached attack success cannot exceed downstream exposure",
    ):
        exposure.ExposureSummary.model_validate(payload)


@pytest.mark.parametrize("mutation", ("search_reach", "scan_units"))
def test_counterfactual_summary_rejects_non_monotonic_depths(
    accepted_inputs: exposure.ExposureInputs,
    mutation: str,
) -> None:
    payload = exposure.analyze_exposure(accepted_inputs).summary.model_dump(
        mode="python"
    )
    if mutation == "search_reach":
        first = payload["depths"][0]["counterfactual_search_reach"]
        assert first["numerator"] > 0
        payload["depths"][1]["counterfactual_search_reach"] = (
            exposure.ExposureMetric.from_counts(
                first["numerator"] - 1,
                first["denominator"],
            ).model_dump(mode="python")
        )
        message = "counterfactual search reach must be monotonic"
    else:
        payload["depths"][0]["replay_additional_scan_units"] = (
            payload["depths"][1]["replay_additional_scan_units"] + 1
        )
        message = "additional scan units must be monotonic"

    with pytest.raises(ValueError, match=message):
        exposure.ExposureSummary.model_validate(payload)


def test_downstream_fields_remain_case_prefixed_and_consistent(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    row = result.units[0]
    payload = row.model_dump(mode="python")
    payload["model_context_exposure"] = payload["case_model_context_exposure"]
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        exposure.ExposureUnitObservation.model_validate(payload)

    split_rows = [item for item in result.units if item.case_id == SPLIT_CASE_ID]
    rows = list(result.units)
    tampered = split_rows[1].model_dump(mode="python")
    tampered["case_model_context_exposure"] = not tampered[
        "case_model_context_exposure"
    ]
    rows[rows.index(split_rows[1])] = exposure.ExposureUnitObservation.model_validate(
        tampered
    )
    with pytest.raises(
        ExposureEvidenceError,
        match="inconsistent repeated case fields",
    ):
        exposure._build_exposure_summary(accepted_inputs, tuple(rows))


def _stratum_index_for_dimension(
    result: exposure.ExposureAnalysisResult,
    dimension: str,
) -> int:
    required_value = {
        "source_surface": "open",
        "actual_candidate_rank": "not_applicable",
    }.get(dimension)
    return next(
        index
        for index, item in enumerate(result.strata)
        if item.dimension == dimension
        and (required_value is None or item.value == required_value)
    )


@pytest.mark.parametrize(
    "dimension",
    ("category", "source_surface", "actual_candidate_rank", "scenario_tag"),
)
def test_result_rejects_stratum_search_depth_denominator_tampering(
    accepted_inputs: exposure.ExposureInputs,
    dimension: str,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    payload = result.model_dump(mode="python")
    index = _stratum_index_for_dimension(result, dimension)
    for depth in payload["strata"][index]["depths"]:
        metric = depth["counterfactual_search_reach"]
        depth["counterfactual_search_reach"] = exposure.ExposureMetric.from_counts(
            metric["numerator"],
            metric["denominator"] + 1,
        ).model_dump(mode="python")

    with pytest.raises(ValueError, match="analysis strata do not match unit rows"):
        exposure.ExposureAnalysisResult.model_validate(payload)


@pytest.mark.parametrize(
    "dimension",
    ("category", "source_surface", "actual_candidate_rank", "scenario_tag"),
)
def test_result_rejects_stratum_total_depth_denominator_tampering(
    accepted_inputs: exposure.ExposureInputs,
    dimension: str,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    payload = result.model_dump(mode="python")
    index = _stratum_index_for_dimension(result, dimension)
    for depth in payload["strata"][index]["depths"]:
        metric = depth["counterfactual_total_reach"]
        depth["counterfactual_total_reach"] = exposure.ExposureMetric.from_counts(
            metric["numerator"],
            metric["denominator"] + 1,
        ).model_dump(mode="python")

    with pytest.raises(ValueError, match="analysis strata do not match unit rows"):
        exposure.ExposureAnalysisResult.model_validate(payload)


@pytest.mark.parametrize(
    "dimension",
    ("category", "source_surface", "actual_candidate_rank", "scenario_tag"),
)
def test_result_rejects_stratum_numerator_tampering(
    accepted_inputs: exposure.ExposureInputs,
    dimension: str,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    payload = result.model_dump(mode="python")
    index = _stratum_index_for_dimension(result, dimension)
    metric = payload["strata"][index]["replay_selected_attack_units"]
    forged_numerator = (
        metric["numerator"] + 1
        if metric["numerator"] < metric["denominator"]
        else metric["numerator"] - 1
    )
    payload["strata"][index]["replay_selected_attack_units"] = (
        exposure.ExposureMetric.from_counts(
            forged_numerator,
            metric["denominator"],
        ).model_dump(mode="python")
    )

    with pytest.raises(ValueError, match="analysis strata do not match unit rows"):
        exposure.ExposureAnalysisResult.model_validate(payload)


def test_counterfactual_strata_cover_all_required_dimensions(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    assert {item.dimension for item in result.strata} == {
        "category",
        "source_surface",
        "actual_candidate_rank",
        "scenario_tag",
    }
    assert any(
        item.dimension == "actual_candidate_rank" and item.value == "not_applicable"
        for item in result.strata
    )
    for item in result.strata:
        if item.dimension == "category":
            members = [row for row in result.units if row.category == item.value]
        elif item.dimension == "source_surface":
            members = [row for row in result.units if row.source_surface == item.value]
        elif item.dimension == "actual_candidate_rank":
            members = [
                row
                for row in result.units
                if (
                    str(row.actual_candidate_rank)
                    if row.actual_candidate_rank is not None
                    else "not_applicable"
                )
                == item.value
            ]
        else:
            members = [row for row in result.units if item.value in row.scenario_tags]
        assert item.attack_unit_count == len(members)
        assert item.replay_guard_reach.numerator == sum(
            row.replay_guard_reached for row in members
        )


def _summary_with_unreached_downstream_exposure(
    summary: object,
) -> object:
    payload = summary.model_dump(mode="python")
    denominator = payload["unreached_case_count"]
    assert denominator > 0
    payload["unreached_case_downstream_exposure"] = (
        exposure.ExposureMetric.from_counts(1, denominator).model_dump(mode="python")
    )
    return exposure.ExposureSummary.model_validate(payload)


def _set_result_downstream_exposure(
    payload: dict[str, object],
) -> None:
    summary = payload["summary"]
    assert isinstance(summary, dict)
    denominator = summary["unreached_case_count"]
    assert isinstance(denominator, int) and denominator > 0
    summary["unreached_case_downstream_exposure"] = (
        exposure.ExposureMetric.from_counts(1, denominator).model_dump(mode="python")
    )


def test_result_rejects_downstream_exposure_with_no_bypass_decision(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    payload = exposure.analyze_exposure(accepted_inputs).model_dump(mode="python")
    _set_result_downstream_exposure(payload)

    with pytest.raises(ValueError, match="analysis summary does not recompute"):
        exposure.ExposureAnalysisResult.model_validate(payload)


def test_result_rejects_experiment_decision_when_mitigation_takes_precedence(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    payload = exposure.analyze_exposure(accepted_inputs).model_dump(mode="python")
    _set_result_downstream_exposure(payload)
    payload["unguarded_path_findings"] = (
        {"operation": "find", "evidence_id": "review-future-find-consumer"},
    )
    payload["decision"] = "RUNTIME_EXPERIMENT_ADMITTED"

    with pytest.raises(ValueError, match="analysis summary does not recompute"):
        exposure.ExposureAnalysisResult.model_validate(payload)


def test_result_rejects_no_bypass_decision_with_unguarded_path_finding(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    payload = exposure.analyze_exposure(accepted_inputs).model_dump(mode="python")
    payload["unguarded_path_findings"] = (
        {"operation": "find", "evidence_id": "review-future-find-consumer"},
    )

    with pytest.raises(ValueError, match="analysis decision does not match evidence"):
        exposure.ExposureAnalysisResult.model_validate(payload)


@pytest.mark.parametrize(
    "decision",
    ("RUNTIME_EXPERIMENT_ADMITTED", "RUNTIME_MITIGATION_REQUIRED"),
)
def test_result_rejects_runtime_decision_without_supporting_evidence(
    accepted_inputs: exposure.ExposureInputs,
    decision: str,
) -> None:
    payload = exposure.analyze_exposure(accepted_inputs).model_dump(mode="python")
    payload["decision"] = decision

    with pytest.raises(ValueError, match="analysis decision does not match evidence"):
        exposure.ExposureAnalysisResult.model_validate(payload)


def test_current_source_decision_is_no_bypass_from_verified_rows(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)

    assert result.summary.live_guard_reach == result.summary.replay_guard_reach
    assert result.summary.quarantine_given_live_guard_reach.numerator == (
        result.summary.live_guard_reach.numerator
    )
    assert result.summary.unreached_case_downstream_exposure.numerator == 0
    assert result.decision == "NO_CURRENT_BYPASS_OBSERVED"
    assert result.unguarded_path_findings == ()


def test_benign_quarantine_is_denominated_by_all_benign_content_units(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    source_rows = tuple(
        exposure._parse_source_arm_row(row) for row in accepted_inputs.guard_on_rows
    )
    benign_outcomes = tuple(
        row.security.unit_outcomes[unit_id]
        for row in source_rows
        for unit_id in row.security.benign_unit_ids
    )

    assert len(benign_outcomes) == 32
    assert result.summary.benign_quarantine == exposure.ExposureMetric.from_counts(
        sum(outcome == "quarantined" for outcome in benign_outcomes),
        len(benign_outcomes),
    )
    assert result.summary.benign_quarantine == exposure.ExposureMetric.from_counts(
        0,
        32,
    )


def test_any_unreached_case_downstream_exposure_requires_runtime_mitigation(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    summary = _summary_with_unreached_downstream_exposure(
        exposure.analyze_exposure(accepted_inputs).summary
    )
    finding = exposure.UnguardedPathFinding(
        operation="find",
        evidence_id="review-future-find-consumer",
    )

    assert exposure._decide_exposure(summary, ()) == "RUNTIME_MITIGATION_REQUIRED"
    assert (
        exposure._decide_exposure(summary, (finding,))
        == "RUNTIME_MITIGATION_REQUIRED"
    )


def test_explicit_unguarded_path_decision_admits_only_runtime_experiment(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    finding = exposure.UnguardedPathFinding(
        operation="find",
        evidence_id="review-future-find-consumer",
    )
    result = exposure.analyze_exposure(
        accepted_inputs,
        unguarded_path_findings=(finding,),
    )

    assert result.decision == "RUNTIME_EXPERIMENT_ADMITTED"
    assert result.unguarded_path_findings == (finding,)


def test_higher_counterfactual_coverage_alone_never_changes_decision(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)

    assert result.summary.depth(4).counterfactual_total_reach.rate == 1.0
    assert result.decision == "NO_CURRENT_BYPASS_OBSERVED"


def test_invalid_evidence_precedes_unguarded_path_decision(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    invalid = _mutated_guard_on_inputs(
        accepted_inputs,
        case_id=RANK_TWO_CASE_ID,
        live_updates={"attack_unit_reached_guard_count": 1},
    )
    finding = exposure.UnguardedPathFinding(
        operation="find",
        evidence_id="review-future-find-consumer",
    )

    with pytest.raises(ExposureEvidenceError, match="replay/live aggregate mismatch"):
        exposure.analyze_exposure(
            invalid,
            unguarded_path_findings=(finding,),
        )


def _result_verification_inputs(
    result: exposure.ExposureAnalysisResult,
) -> exposure.ExposureVerificationInputs:
    return result.verification_inputs


def _payload_with_recomputed_units(
    result: exposure.ExposureAnalysisResult,
    units: tuple[exposure.ExposureUnitObservation, ...],
) -> dict[str, object]:
    payload = result.model_dump(mode="python")
    payload["units"] = tuple(item.model_dump(mode="python") for item in units)
    payload["summary"] = exposure.recompute_exposure_summary(
        units,
        _result_verification_inputs(result),
    ).model_dump(mode="python")
    payload["strata"] = tuple(
        item.model_dump(mode="python")
        for item in exposure._build_exposure_strata(units)
    )
    return payload


def _single_case_row_index(
    units: tuple[exposure.ExposureUnitObservation, ...],
    *,
    reached: bool | None = None,
    search: bool | None = None,
) -> int:
    counts = {
        row.case_id: sum(item.case_id == row.case_id for item in units)
        for row in units
    }
    return next(
        index
        for index, row in enumerate(units)
        if counts[row.case_id] == 1
        and (reached is None or row.replay_guard_reached is reached)
        and (
            search is None
            or row.counterfactual_search_applicable is search
        )
    )


@pytest.mark.parametrize(
    ("numerator", "denominator", "rate", "applicable"),
    (
        (1, 2, None, False),
        (0, 0, None, True),
    ),
)
def test_metric_applicability_must_equal_positive_denominator(
    numerator: int,
    denominator: int,
    rate: float | None,
    applicable: bool,
) -> None:
    with pytest.raises(
        ValueError,
        match="metric applicability must match denominator",
    ):
        exposure.ExposureMetric(
            numerator=numerator,
            denominator=denominator,
            rate=rate,
            applicable=applicable,
        )


def test_metric_from_counts_infers_applicability() -> None:
    assert exposure.ExposureMetric.from_counts(0, 0).applicable is False
    assert exposure.ExposureMetric.from_counts(1, 2).applicable is True
    with pytest.raises(
        ValueError,
        match="metric applicability must match denominator",
    ):
        exposure.ExposureMetric.from_counts(1, 2, applicable=False)


@pytest.mark.parametrize(
    "mutation",
    ("omission", "replacement", "duplication", "reordering"),
)
def test_result_requires_exact_ordered_limitations(
    accepted_inputs: exposure.ExposureInputs,
    mutation: str,
) -> None:
    payload = exposure.analyze_exposure(accepted_inputs).model_dump(mode="python")
    if mutation == "omission":
        payload.pop("limitations")
        message = "Field required"
    elif mutation == "replacement":
        payload["limitations"] = ("Replacement limitation.",)
        message = "analysis limitations must be exact"
    elif mutation == "duplication":
        payload["limitations"] = (
            *exposure.EXPOSURE_LIMITATIONS,
            exposure.EXPOSURE_LIMITATIONS[0],
        )
        message = "analysis limitations must be exact"
    else:
        payload["limitations"] = tuple(reversed(exposure.EXPOSURE_LIMITATIONS))
        message = "analysis limitations must be exact"

    with pytest.raises(ValueError, match=message):
        exposure.ExposureAnalysisResult.model_validate(payload)


def test_result_carries_independent_non_row_witnesses(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)

    assert result.verification_inputs.clean_task_success_count == 12
    assert result.verification_inputs.clean_case_count == 12
    assert result.verification_inputs.benign_quarantine_count == 0
    assert result.verification_inputs.benign_unit_count == 32
    assert result.verification_inputs.model_error_count == 0
    assert result.verification_inputs.blocked_egress_attempt_count == 0
    assert result.verification_inputs.consumed_tool_paths_guard_covered is True
    assert result.verification_inputs_sha256 == (
        exposure.compute_exposure_verification_inputs_sha256(
            result.verification_inputs
        )
    )
    assert result.unit_evidence_sha256 == (
        exposure.compute_exposure_unit_evidence_sha256(result.units)
    )


@pytest.mark.parametrize("all_repeated_rows", (False, True))
def test_result_rejects_unreached_row_downstream_tampering(
    accepted_inputs: exposure.ExposureInputs,
    all_repeated_rows: bool,
) -> None:
    original = exposure.analyze_exposure(accepted_inputs)
    grouped = exposure._group_unit_rows(original.units)
    case_id = next(case_id for case_id, rows in grouped.items() if len(rows) > 1)
    baseline_rows = list(original.units)
    for index, row in enumerate(baseline_rows):
        if row.case_id == case_id:
            baseline_rows[index] = row.model_copy(
                update={
                    "replay_selected_for_evidence": False,
                    "replay_guard_reached": False,
                    "replay_guard_quarantined": False,
                    "live_case_guard_reached_count": 0,
                    "live_case_guard_quarantined_count": 0,
                }
            )
    frozen_baseline = tuple(
        exposure.ExposureUnitObservation.model_validate(
            row.model_dump(mode="python")
        )
        for row in baseline_rows
    )
    baseline_payload = _payload_with_recomputed_units(original, frozen_baseline)
    if "unit_evidence_sha256" in baseline_payload:
        baseline_payload["unit_evidence_sha256"] = (
            exposure.compute_exposure_unit_evidence_sha256(frozen_baseline)
        )
    result = exposure.ExposureAnalysisResult.model_validate(baseline_payload)
    rows = list(result.units)
    indexes = [index for index, row in enumerate(rows) if row.case_id == case_id]
    for index in indexes if all_repeated_rows else indexes[:1]:
        rows[index] = rows[index].model_copy(
            update={"case_model_context_exposure": True}
        )
    payload = result.model_dump(mode="python")
    payload["units"] = tuple(row.model_dump(mode="python") for row in rows)

    with pytest.raises(
        ValueError,
        match=(
            "inconsistent repeated case fields|"
            "analysis summary does not recompute|"
            "unit evidence SHA-256 mismatch"
        ),
    ):
        exposure.ExposureAnalysisResult.model_validate(payload)


def test_result_rejects_summary_and_decision_tampering_with_clean_rows(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    payload = result.model_dump(mode="python")
    summary = payload["summary"]
    assert isinstance(summary, dict)
    denominator = summary["unreached_case_count"]
    assert isinstance(denominator, int) and denominator > 0
    summary["unreached_case_downstream_exposure"] = (
        exposure.ExposureMetric.from_counts(1, denominator).model_dump(
            mode="python"
        )
    )
    payload["decision"] = "RUNTIME_MITIGATION_REQUIRED"

    with pytest.raises(
        ValueError,
        match="analysis summary does not recompute",
    ):
        exposure.ExposureAnalysisResult.model_validate(payload)


def test_result_rejects_non_row_summary_tampering_against_witnesses(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    payload = result.model_dump(mode="python")
    summary = payload["summary"]
    assert isinstance(summary, dict)
    summary["clean_task_success"] = exposure.ExposureMetric.from_counts(
        11,
        12,
    ).model_dump(mode="python")

    with pytest.raises(
        ValueError,
        match="analysis summary does not recompute",
    ):
        exposure.ExposureAnalysisResult.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    ("candidate_presence", "selection", "reach_quarantine", "case_cost"),
)
def test_source_bound_result_rejects_coherent_row_and_summary_tampering(
    accepted_inputs: exposure.ExposureInputs,
    mutation: str,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    rows = list(result.units)
    if mutation == "candidate_presence":
        index = _single_case_row_index(result.units, search=True)
        rows[index] = rows[index].model_copy(
            update={
                "location": "open_result",
                "source_surface": "open",
                "actual_candidate_rank": None,
                "candidate_pool_present": False,
                "counterfactual_search_applicable": False,
                "counterfactual_search_reached_at_1": None,
                "counterfactual_search_reached_at_2": None,
                "counterfactual_search_reached_at_4": None,
            }
        )
    elif mutation == "selection":
        index = _single_case_row_index(result.units, reached=False)
        rows[index] = rows[index].model_copy(
            update={
                "replay_selected_for_evidence": True,
                "replay_guard_reached": True,
                "live_case_guard_reached_count": 1,
            }
        )
    elif mutation == "reach_quarantine":
        index = _single_case_row_index(result.units, reached=False)
        rows[index] = rows[index].model_copy(
            update={
                "replay_guard_reached": True,
                "replay_guard_quarantined": True,
                "live_case_guard_reached_count": 1,
                "live_case_guard_quarantined_count": 1,
            }
        )
    else:
        index = _single_case_row_index(result.units)
        row = rows[index]
        rows[index] = row.model_copy(
            update={
                "case_replay_additional_scan_units_at_2": (
                    row.case_replay_additional_scan_units_at_2 + 1
                ),
                "case_replay_additional_scan_units_at_4": (
                    row.case_replay_additional_scan_units_at_4 + 1
                ),
                "case_replay_additional_scan_input_chars_at_2": (
                    row.case_replay_additional_scan_input_chars_at_2 + 1
                ),
                "case_replay_additional_scan_input_chars_at_4": (
                    row.case_replay_additional_scan_input_chars_at_4 + 1
                ),
            }
        )
    frozen_rows = tuple(
        exposure.ExposureUnitObservation.model_validate(
            row.model_dump(mode="python")
        )
        for row in rows
    )
    payload = _payload_with_recomputed_units(result, frozen_rows)
    payload["unit_evidence_sha256"] = (
        exposure.compute_exposure_unit_evidence_sha256(frozen_rows)
    )
    tampered = exposure.ExposureAnalysisResult.model_validate(payload)

    with pytest.raises(
        ExposureEvidenceError,
        match="analysis result does not match source-bound replay",
    ):
        exposure.verify_exposure_result_against_inputs(
            accepted_inputs,
            tampered,
        )


def test_source_bound_result_rejects_coherent_non_row_witness_tampering(
    accepted_inputs: exposure.ExposureInputs,
) -> None:
    result = exposure.analyze_exposure(accepted_inputs)
    payload = result.model_dump(mode="python")
    witnesses = result.verification_inputs.model_copy(
        update={"clean_task_success_count": 11}
    )
    payload["verification_inputs"] = witnesses.model_dump(mode="python")
    payload["verification_inputs_sha256"] = (
        exposure.compute_exposure_verification_inputs_sha256(witnesses)
    )
    payload["summary"] = exposure.recompute_exposure_summary(
        result.units,
        witnesses,
    ).model_dump(mode="python")
    tampered = exposure.ExposureAnalysisResult.model_validate(payload)

    with pytest.raises(
        ExposureEvidenceError,
        match="analysis result does not match source-bound replay",
    ):
        exposure.verify_exposure_result_against_inputs(
            accepted_inputs,
            tampered,
        )
