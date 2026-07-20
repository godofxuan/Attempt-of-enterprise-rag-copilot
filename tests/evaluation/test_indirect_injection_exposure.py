from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from app.evaluation import indirect_injection_exposure as exposure
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
    monkeypatch.setattr(
        exposure,
        "verify_live_security_run",
        lambda _run_dir: _manifest_for_mutation(manifest, mutation),
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


def _load_with_manifest(
    monkeypatch: pytest.MonkeyPatch,
    source_run: Path,
    security_data_root: Path,
    manifest: LiveSecurityRunManifestV2,
) -> None:
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
