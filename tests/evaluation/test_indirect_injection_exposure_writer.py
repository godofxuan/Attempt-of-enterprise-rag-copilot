from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.evaluation import indirect_injection_exposure as exposure
from app.evaluation import indirect_injection_exposure_writer as exposure_writer
from app.evaluation.indirect_injection_exposure import (
    COUNTERFACTUAL_DEPTHS,
    EXPOSURE_LIMITATIONS,
    ExposureAnalysisResult,
    ExposureSourceEvidence,
    ExposureUnitObservation,
    ExposureVerificationInputs,
    UnguardedPathFinding,
    _build_exposure_strata,
    compute_exposure_unit_evidence_sha256,
    compute_exposure_verification_inputs_sha256,
    recompute_exposure_summary,
)
from app.evaluation.indirect_injection_exposure_writer import (
    PRIVATE_EXPOSURE_ARTIFACT_FILES,
    ExposureRunManifest,
    publish_exposure_run,
    verify_exposure_run,
)


SOURCE_GUARD_SHA256 = (
    "78ed0509144820ccd05aff61c1509357dd8fe3dbfc8a0c6df30fc304a15e9cd2"
)
CONTENT_NAMES = (
    "commands.txt",
    "failures.csv",
    "per_unit.jsonl",
    "summary.json",
    "test_output.txt",
)
ARTIFACT_NAMES = (*CONTENT_NAMES, "checksums.sha256")
REPLAY_DEPENDENCY_PAYLOADS = (
    {
        "dependency_id": "guard_ruleset",
        "path": "app/security/retrieved_content.py",
        "sha256": SOURCE_GUARD_SHA256,
    },
    {
        "dependency_id": "retrieved_admission",
        "path": "app/security/retrieved_admission.py",
        "sha256": (
            "1f835ba3aa79b1450e8ae906946bba019c21b531fce114cd375b094411c88afb"
        ),
    },
    {
        "dependency_id": "search_surface_constructor",
        "path": "app/evaluation/indirect_injection_runner.py",
        "sha256": (
            "c2c5c5e1815d8a77beebb5027384ea58dd3e73b8536533c8d7898d40668ed36c"
        ),
    },
    {
        "dependency_id": "source_live_evaluator",
        "path": "app/evaluation/indirect_injection_live_runner.py",
        "sha256": (
            "a5eec5619a5ac9f44357fc6063232dca6021538ca5988aab6ae2f962d9b85958"
        ),
    },
)


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source() -> ExposureSourceEvidence:
    return ExposureSourceEvidence(
        run_id="r2-s2-s1-dev-20260719-01",
        manifest_sha256="a" * 64,
        source_git_head="073d7356026954c26c1429fb9faddc5e9a5dcb87",
        dataset_sha256="b" * 64,
        fixture_manifest_sha256="c" * 64,
        guard_ruleset_sha256=SOURCE_GUARD_SHA256,
        case_count=36,
        arm_event_count=72,
        off_then_on_count=18,
        on_then_off_count=18,
    )


def _units() -> tuple[ExposureUnitObservation, ...]:
    raw: list[dict[str, object]] = []
    for index in range(28):
        case_index = index if index < 24 else index - 24
        search = index < 26
        rank = 1 if index < 6 else 2 if index < 22 else 4
        raw.append(
            {
                "case_id": f"synthetic-case-{case_index:02d}",
                "unit_id": f"synthetic-unit-{index:03d}",
                "category": "instruction_override",
                "scenario_tags": ("synthetic",),
                "location": "search_candidate" if search else "open_result",
                "source_surface": "matched" if search else "open",
                "actual_candidate_rank": rank if search else None,
                "candidate_pool_present": search,
                "counterfactual_search_applicable": search,
                "replay_selected_for_evidence": False,
                "replay_guard_reached": index < 15,
                "replay_guard_quarantined": index < 15,
                "case_controller_exposure": False,
                "case_ledger_exposure": False,
                "case_model_context_exposure": False,
                "case_verifier_exposure": False,
                "case_response_exposure": False,
                "case_forbidden_action_followed": False,
                "case_forbidden_tool_attempt": False,
                "case_external_egress_attempt": False,
                "case_blocked_egress_attempt_count": 0,
                "case_attack_success": False,
                "counterfactual_search_reached_at_1": (
                    rank <= 1 if search else None
                ),
                "counterfactual_search_reached_at_2": (
                    rank <= 2 if search else None
                ),
                "counterfactual_search_reached_at_4": (
                    rank <= 4 if search else None
                ),
                "case_replay_additional_scan_units_at_1": 0,
                "case_replay_additional_scan_units_at_2": 0,
                "case_replay_additional_scan_units_at_4": 0,
                "case_replay_additional_scan_input_chars_at_1": 0,
                "case_replay_additional_scan_input_chars_at_2": 0,
                "case_replay_additional_scan_input_chars_at_4": 0,
            }
        )
    reached_by_case: dict[str, int] = {}
    for item in raw:
        reached_by_case[item["case_id"]] = reached_by_case.get(
            item["case_id"], 0
        ) + int(item["replay_guard_reached"])
    return tuple(
        ExposureUnitObservation(
            **item,
            live_case_guard_reached_count=reached_by_case[item["case_id"]],
            live_case_guard_quarantined_count=reached_by_case[item["case_id"]],
        )
        for item in raw
    )


@pytest.fixture(scope="module")
def verification_inputs() -> ExposureVerificationInputs:
    return ExposureVerificationInputs(
        clean_task_success_count=12,
        clean_case_count=12,
        benign_quarantine_count=0,
        benign_unit_count=32,
        model_error_count=0,
        blocked_egress_attempt_count=0,
        consumed_tool_paths_guard_covered=True,
    )


@pytest.fixture(scope="module")
def exposure_result(
    verification_inputs: ExposureVerificationInputs,
) -> ExposureAnalysisResult:
    units = _units()
    summary = recompute_exposure_summary(units, verification_inputs)
    return ExposureAnalysisResult(
        schema_version="indirect_injection_exposure_analysis_v2",
        source=_source(),
        units=units,
        unit_evidence_sha256=compute_exposure_unit_evidence_sha256(units),
        verification_inputs=verification_inputs,
        verification_inputs_sha256=(
            compute_exposure_verification_inputs_sha256(verification_inputs)
        ),
        summary=summary,
        strata=_build_exposure_strata(units),
        decision="NO_CURRENT_BYPASS_OBSERVED",
        unguarded_path_findings=(),
        limitations=EXPOSURE_LIMITATIONS,
    )


@pytest.fixture(autouse=True)
def _stub_source_bound_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        exposure_writer,
        "verify_exposure_result_against_inputs",
        lambda _inputs, _result: None,
    )


def _manifest(
    result: ExposureAnalysisResult,
    *,
    run_id: str = "r2-s3-writer-test",
) -> ExposureRunManifest:
    return ExposureRunManifest(
        schema_version="indirect_injection_exposure_run_manifest_v2",
        producer="enterprise_agentic_rag_v2",
        run_id=run_id,
        created_at_utc=datetime(2026, 7, 21, tzinfo=timezone.utc),
        source=result.source,
        guard_ruleset_path="app/security/retrieved_content.py",
        guard_ruleset_sha256=result.source.guard_ruleset_sha256,
        evaluator_path="app/evaluation/indirect_injection_exposure.py",
        evaluator_sha256=_sha256(
            Path("app/evaluation/indirect_injection_exposure.py")
        ),
        replay_dependencies=exposure.REPLAY_IMPLEMENTATION_DEPENDENCIES,
        unit_evidence_sha256=result.unit_evidence_sha256,
        verification_inputs_sha256=result.verification_inputs_sha256,
        counterfactual_depths=COUNTERFACTUAL_DEPTHS,
        decision=result.decision,
        case_count=36,
        attack_case_count=24,
        benign_case_count=12,
        attack_unit_count=28,
        benign_unit_count=32,
        unguarded_path_findings=result.unguarded_path_findings,
        artifacts={},
        limitations=result.limitations,
    )


def _publish(
    root: Path,
    result: ExposureAnalysisResult,
    *,
    forbidden_texts: tuple[str, ...] = ("raw question", "raw attack"),
) -> Path:
    return exposure_writer._publish_exposure_run(
        root,
        manifest=_manifest(result),
        result=result,
        commands="python -m scripts.eval_indirect_injection_exposure\n",
        test_output="source verified\n",
        forbidden_texts=forbidden_texts,
    )


def _copy_replay_dependency_tree(root: Path) -> None:
    for dependency in REPLAY_DEPENDENCY_PAYLOADS:
        relative_path = str(dependency["path"])
        target = root / Path(*relative_path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(relative_path).read_bytes())


def test_private_v2_manifest_requires_replay_dependencies(
    exposure_result: ExposureAnalysisResult,
) -> None:
    payload = _manifest(exposure_result).model_dump(mode="python")
    payload.pop("replay_dependencies")

    with pytest.raises(
        ValidationError,
        match="v2 manifest requires replay dependencies",
    ):
        ExposureRunManifest.model_validate(payload)


def test_private_v2_manifest_accepts_exact_replay_dependencies(
    exposure_result: ExposureAnalysisResult,
) -> None:
    payload = _manifest(exposure_result).model_dump(mode="python")
    payload["replay_dependencies"] = REPLAY_DEPENDENCY_PAYLOADS

    manifest = ExposureRunManifest.model_validate(payload)

    assert tuple(
        item.model_dump(mode="json") for item in manifest.replay_dependencies
    ) == REPLAY_DEPENDENCY_PAYLOADS


@pytest.mark.parametrize("dependency_index", range(4))
@pytest.mark.parametrize("field", ("path", "sha256"))
def test_private_v2_manifest_rejects_dependency_substitution(
    exposure_result: ExposureAnalysisResult,
    dependency_index: int,
    field: str,
) -> None:
    payload = _manifest(exposure_result).model_dump(mode="python")
    dependencies = [dict(item) for item in REPLAY_DEPENDENCY_PAYLOADS]
    dependencies[dependency_index][field] = (
        "app/evaluation/substituted.py" if field == "path" else "0" * 64
    )
    payload["replay_dependencies"] = tuple(dependencies)

    with pytest.raises(
        ValidationError,
        match="v2 manifest replay dependencies must be exact",
    ):
        ExposureRunManifest.model_validate(payload)


def test_private_v1_manifest_keeps_legacy_dependency_schema(
    exposure_result: ExposureAnalysisResult,
) -> None:
    payload = _manifest(exposure_result).model_dump(mode="python")
    payload["schema_version"] = "indirect_injection_exposure_run_manifest_v1"
    payload["unit_evidence_sha256"] = None
    payload["verification_inputs_sha256"] = None
    payload.pop("replay_dependencies")

    manifest = ExposureRunManifest.model_validate(payload)

    assert manifest.replay_dependencies is None


@pytest.mark.parametrize("dependency_index", range(4))
def test_trusted_private_verifier_rejects_mutated_dependency_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
    dependency_index: int,
) -> None:
    target = _publish(tmp_path / "runs", exposure_result)
    repository_root = tmp_path / "repository"
    _copy_replay_dependency_tree(repository_root)
    dependency = REPLAY_DEPENDENCY_PAYLOADS[dependency_index]
    dependency_path = repository_root / Path(
        *str(dependency["path"]).split("/")
    )
    dependency_path.write_bytes(
        dependency_path.read_bytes() + b"\n# dependency mutation\n"
    )
    monkeypatch.setattr(
        exposure,
        "_REPLAY_REPOSITORY_ROOT",
        repository_root,
        raising=False,
    )

    with pytest.raises(
        ValueError,
        match=rf"replay dependency .*{dependency['dependency_id']}",
    ):
        verify_exposure_run(target)


def _refresh_checksums_and_manifest(run_dir: Path) -> None:
    checksum_payload = "".join(
        f"{_sha256(run_dir / name)}  {name}\n" for name in CONTENT_NAMES
    ).encode("utf-8")
    (run_dir / "checksums.sha256").write_bytes(checksum_payload)
    payload = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    payload["artifacts"] = {
        name: {
            "bytes": (run_dir / name).stat().st_size,
            "path": name,
            "sha256": _sha256(run_dir / name),
        }
        for name in ARTIFACT_NAMES
    }
    (run_dir / "manifest.json").write_bytes(_canonical_json(payload))


def _refresh_unit_evidence_binding(run_dir: Path) -> None:
    units = tuple(
        ExposureUnitObservation.model_validate_json(line)
        for line in (run_dir / "per_unit.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    digest = compute_exposure_unit_evidence_sha256(units)
    for name in ("manifest.json", "summary.json"):
        path = run_dir / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["unit_evidence_sha256"] = digest
        path.write_bytes(_canonical_json(payload))


def test_private_writer_is_immutable_canonical_and_recomputable(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
) -> None:
    target = _publish(tmp_path / "runs", exposure_result)

    assert {item.name for item in target.iterdir()} == set(
        PRIVATE_EXPOSURE_ARTIFACT_FILES
    )
    manifest = verify_exposure_run(target)
    assert manifest.run_id == target.name
    assert set(manifest.artifacts) == set(ARTIFACT_NAMES)
    assert all(
        evidence.path == name
        and evidence.bytes == (target / name).stat().st_size
        and evidence.sha256 == _sha256(target / name)
        for name, evidence in manifest.artifacts.items()
    )
    assert (target / "summary.json").read_bytes() == _canonical_json(
        json.loads((target / "summary.json").read_text(encoding="utf-8"))
    )
    rows = (target / "per_unit.jsonl").read_text(encoding="utf-8").splitlines()
    identities = tuple(
        (json.loads(row)["case_id"], json.loads(row)["unit_id"])
        for row in rows
    )
    assert identities == tuple(sorted(identities))
    assert len(identities) == 28
    assert len(set(identities)) == 28
    assert (target / "failures.csv").read_text(encoding="utf-8") == (
        "scope,case_id,unit_id,primary_failure,all_failures\n"
    )
    checksum_names = tuple(
        line.split("  ", 1)[1]
        for line in (target / "checksums.sha256")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert checksum_names == CONTENT_NAMES

    with pytest.raises(FileExistsError):
        _publish(tmp_path / "runs", exposure_result)


def test_failure_rows_attribute_risk_once_per_case(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
    verification_inputs: ExposureVerificationInputs,
) -> None:
    units: list[ExposureUnitObservation] = []
    for item in exposure_result.units:
        payload = item.model_dump(mode="python")
        if item.case_id == "synthetic-case-00":
            payload.update(
                replay_guard_reached=False,
                replay_guard_quarantined=False,
                live_case_guard_reached_count=0,
                live_case_guard_quarantined_count=0,
                case_controller_exposure=True,
            )
        units.append(ExposureUnitObservation.model_validate(payload))
    frozen_units = tuple(units)
    finding = UnguardedPathFinding(
        operation="find", evidence_id="future-find-consumer"
    )
    result = ExposureAnalysisResult(
        schema_version="indirect_injection_exposure_analysis_v2",
        source=exposure_result.source,
        units=frozen_units,
        unit_evidence_sha256=compute_exposure_unit_evidence_sha256(
            frozen_units
        ),
        verification_inputs=verification_inputs,
        verification_inputs_sha256=(
            compute_exposure_verification_inputs_sha256(verification_inputs)
        ),
        summary=recompute_exposure_summary(frozen_units, verification_inputs),
        strata=_build_exposure_strata(frozen_units),
        decision="RUNTIME_MITIGATION_REQUIRED",
        unguarded_path_findings=(finding,),
        limitations=exposure_result.limitations,
    )

    target = _publish(tmp_path / "runs", result)
    rows = list(
        csv.DictReader(
            (target / "failures.csv").read_text(encoding="utf-8").splitlines()
        )
    )

    assert rows == [
        {
            "scope": "case",
            "case_id": "synthetic-case-00",
            "unit_id": "",
            "primary_failure": "unreached_downstream_exposure",
            "all_failures": "controller_exposure",
        },
        {
            "scope": "tool_path",
            "case_id": "",
            "unit_id": "",
            "primary_failure": "unguarded_find_path",
            "all_failures": "future-find-consumer",
        },
    ]


def test_verifier_refuses_coherently_tampered_summary(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
) -> None:
    target = _publish(tmp_path / "runs", exposure_result)
    payload = json.loads((target / "summary.json").read_text(encoding="utf-8"))
    payload["summary"]["clean_task_success"]["numerator"] = 11
    payload["summary"]["clean_task_success"]["rate"] = 11 / 12
    (target / "summary.json").write_bytes(_canonical_json(payload))
    _refresh_checksums_and_manifest(target)

    with pytest.raises(ValueError, match="summary does not recompute"):
        verify_exposure_run(target)


def test_verifier_refuses_coherently_tampered_unit_row(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
) -> None:
    target = _publish(tmp_path / "runs", exposure_result)
    rows = (target / "per_unit.jsonl").read_text(encoding="utf-8").splitlines()
    row_index = next(
        index
        for index, row in enumerate(rows)
        if json.loads(row)["case_id"] == "synthetic-case-23"
    )
    payload = json.loads(rows[row_index])
    payload["case_attack_success"] = True
    rows[row_index] = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    (target / "per_unit.jsonl").write_text(
        "\n".join(rows) + "\n", encoding="utf-8", newline=""
    )
    _refresh_unit_evidence_binding(target)
    _refresh_checksums_and_manifest(target)

    with pytest.raises(ValueError, match="summary does not recompute"):
        verify_exposure_run(target)


def test_verifier_rejects_per_case_live_count_redistribution(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
) -> None:
    target = _publish(tmp_path / "runs", exposure_result)
    rows = (target / "per_unit.jsonl").read_text(encoding="utf-8").splitlines()
    rewritten: list[str] = []
    for row in rows:
        payload = json.loads(row)
        if payload["case_id"] == "synthetic-case-00":
            payload["live_case_guard_reached_count"] = 2
            payload["live_case_guard_quarantined_count"] = 2
        elif payload["case_id"] == "synthetic-case-01":
            payload["live_case_guard_reached_count"] = 0
            payload["live_case_guard_quarantined_count"] = 0
        rewritten.append(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    (target / "per_unit.jsonl").write_text(
        "\n".join(rewritten) + "\n", encoding="utf-8", newline=""
    )
    _refresh_unit_evidence_binding(target)
    _refresh_checksums_and_manifest(target)

    with pytest.raises(ValueError, match="replay/live case mismatch"):
        verify_exposure_run(target)


def test_writer_refuses_forbidden_content_and_cleans_stage(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
) -> None:
    root = tmp_path / "runs"
    with pytest.raises(ValueError, match="forbidden content"):
        _publish(root, exposure_result, forbidden_texts=("synthetic-unit-000",))

    assert not (root / "r2-s3-writer-test").exists()
    assert not tuple(root.glob(".*.staging-*"))


def test_writer_refuses_escaped_forbidden_content_in_structured_value(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
) -> None:
    forbidden = 'raw "attack" \\ path\n\u653b\u51fb'
    units = list(exposure_result.units)
    units[0] = units[0].model_copy(update={"category": forbidden})
    frozen_units = tuple(units)
    result = exposure_result.model_copy(
        update={
            "units": frozen_units,
            "unit_evidence_sha256": compute_exposure_unit_evidence_sha256(
                frozen_units
            ),
            "strata": _build_exposure_strata(frozen_units),
        }
    )
    root = tmp_path / "runs"

    with pytest.raises(ValueError, match="forbidden content"):
        _publish(root, result, forbidden_texts=(forbidden,))

    assert not (root / "r2-s3-writer-test").exists()
    assert not tuple(root.glob(".*.staging-*"))


@pytest.mark.parametrize(
    "run_id",
    ("..", "../escape", "nested/run", r"nested\\run", "CON", "name."),
)
def test_manifest_rejects_unsafe_run_ids(
    exposure_result: ExposureAnalysisResult,
    run_id: str,
) -> None:
    with pytest.raises(ValidationError):
        _manifest(exposure_result, run_id=run_id)


def test_manifest_requires_exact_artifact_map_when_nonempty(
    exposure_result: ExposureAnalysisResult,
) -> None:
    payload = _manifest(exposure_result).model_dump(mode="python")
    payload["artifacts"] = {
        "summary.json": {
            "path": "summary.json",
            "bytes": 1,
            "sha256": "e" * 64,
        }
    }
    with pytest.raises(ValidationError, match="exact artifact set"):
        ExposureRunManifest.model_validate(payload)


def test_manifest_cannot_represent_invalid_evidence(
    exposure_result: ExposureAnalysisResult,
) -> None:
    payload = _manifest(exposure_result).model_dump(mode="python")
    payload["decision"] = "INVALID_EVIDENCE"
    with pytest.raises(ValidationError):
        ExposureRunManifest.model_validate(payload)


@pytest.mark.parametrize("mutation", ("missing", "extra"))
def test_verifier_requires_exact_file_set(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
    mutation: str,
) -> None:
    target = _publish(tmp_path / "runs", exposure_result)
    if mutation == "missing":
        (target / "commands.txt").unlink()
    else:
        (target / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unexpected artifact set"):
        verify_exposure_run(target)


def test_verifier_rejects_noncanonical_and_duplicate_key_json(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
) -> None:
    first = _publish(tmp_path / "first", exposure_result)
    summary = json.loads((first / "summary.json").read_text(encoding="utf-8"))
    (first / "summary.json").write_text(
        json.dumps(summary, sort_keys=True), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="not canonical"):
        verify_exposure_run(first)

    second = _publish(tmp_path / "second", exposure_result)
    raw = (second / "manifest.json").read_text(encoding="utf-8")
    duplicate = raw.replace("{", '{"schema_version":"duplicate",', 1)
    (second / "manifest.json").write_text(duplicate, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        verify_exposure_run(second)


def test_publish_rejects_manifest_result_mismatch_before_target_creation(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
) -> None:
    finding = UnguardedPathFinding(
        operation="find", evidence_id="future-find-consumer"
    )
    payload = exposure_result.model_dump(mode="python")
    payload["unguarded_path_findings"] = (finding,)
    payload["decision"] = "RUNTIME_EXPERIMENT_ADMITTED"
    changed = ExposureAnalysisResult.model_validate(payload)
    root = tmp_path / "runs"

    with pytest.raises(ValueError, match="manifest decision"):
        publish_exposure_run(
            root,
            manifest=_manifest(exposure_result),
            result=changed,
            source_inputs=object(),
            commands="command\n",
            test_output="output\n",
            forbidden_texts=("raw",),
        )
    assert not (root / "r2-s3-writer-test").exists()


def test_publish_rejects_source_binding_mismatch_before_target_creation(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
) -> None:
    payload = _manifest(exposure_result).model_dump(mode="python")
    payload["source"] = exposure_result.source.model_copy(
        update={"dataset_sha256": "f" * 64}
    )
    manifest = ExposureRunManifest.model_validate(payload)
    root = tmp_path / "runs"

    with pytest.raises(ValueError, match="manifest source"):
        publish_exposure_run(
            root,
            manifest=manifest,
            result=exposure_result,
            source_inputs=object(),
            commands="command\n",
            test_output="output\n",
            forbidden_texts=("raw",),
        )
    assert not (root / "r2-s3-writer-test").exists()


def test_supported_publish_requires_canonical_executed_evaluator_before_output(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
) -> None:
    payload = _manifest(exposure_result).model_dump(mode="python")
    payload["evaluator_path"] = "app/evaluation/substituted_exposure.py"
    manifest = ExposureRunManifest.model_validate(payload)
    root = tmp_path / "runs"

    with pytest.raises(ValueError, match="canonical exposure evaluator path"):
        publish_exposure_run(
            root,
            manifest=manifest,
            result=exposure_result,
            source_inputs=object(),
            commands="command\n",
            test_output="output\n",
            forbidden_texts=("raw",),
        )

    assert not root.exists()


def test_supported_publish_authenticates_executed_evaluator_bytes_before_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exposure_result: ExposureAnalysisResult,
) -> None:
    evaluator_path = Path("app/evaluation/indirect_injection_exposure.py").resolve()
    payload = _manifest(exposure_result).model_dump(mode="python")
    payload["evaluator_sha256"] = _sha256(evaluator_path)
    manifest = ExposureRunManifest.model_validate(payload)
    root = tmp_path / "runs"
    real_read_bytes = Path.read_bytes

    def mutated_evaluator_bytes(path: Path) -> bytes:
        if path.resolve() == evaluator_path:
            return b"mutated evaluator bytes\n"
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", mutated_evaluator_bytes)

    with pytest.raises(ValueError, match="exposure evaluator SHA-256 mismatch"):
        publish_exposure_run(
            root,
            manifest=manifest,
            result=exposure_result,
            source_inputs=object(),
            commands="command\n",
            test_output="output\n",
            forbidden_texts=("raw",),
        )

    assert not root.exists()


def test_supported_publish_rechecks_evaluator_identity_before_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exposure_result: ExposureAnalysisResult,
) -> None:
    evaluator_path = Path("app/evaluation/indirect_injection_exposure.py").resolve()
    root = tmp_path / "runs"
    real_stat = Path.stat
    real_validate_analysis = exposure_writer._validate_analysis
    validation_count = 0
    identity_changed = False

    def validate_then_change_identity(*args, **kwargs) -> None:
        nonlocal validation_count, identity_changed
        real_validate_analysis(*args, **kwargs)
        validation_count += 1
        if validation_count == 2:
            identity_changed = True

    def change_identity_before_output(path: Path, *args, **kwargs):
        observed = real_stat(path, *args, **kwargs)
        if path != evaluator_path or not identity_changed:
            return observed
        return SimpleNamespace(
            st_dev=observed.st_dev,
            st_ino=observed.st_ino,
            st_mode=observed.st_mode,
            st_size=observed.st_size,
            st_mtime_ns=observed.st_mtime_ns + 1,
            st_ctime_ns=observed.st_ctime_ns,
        )

    monkeypatch.setattr(
        exposure_writer,
        "_validate_analysis",
        validate_then_change_identity,
    )
    monkeypatch.setattr(Path, "stat", change_identity_before_output)

    with pytest.raises(ValueError, match="changed during publication"):
        publish_exposure_run(
            root,
            manifest=_manifest(exposure_result),
            result=exposure_result,
            source_inputs=object(),
            commands="command\n",
            test_output="output\n",
            forbidden_texts=("raw",),
        )

    assert validation_count == 2
    assert not root.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("guard_ruleset_path", "../retrieved_content.py"),
        ("guard_ruleset_path", r"app\\security\\retrieved_content.py"),
        ("evaluator_path", "C:/private/evaluator.py"),
    ),
)
def test_manifest_rejects_unsafe_repository_paths(
    exposure_result: ExposureAnalysisResult,
    field: str,
    value: str,
) -> None:
    payload = _manifest(exposure_result).model_dump(mode="python")
    payload[field] = value
    with pytest.raises(ValidationError):
        ExposureRunManifest.model_validate(payload)


def test_publish_cleans_stage_when_final_validation_fails(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "runs"

    def fail_validation(_stage: Path, _manifest: ExposureRunManifest) -> None:
        raise ValueError("injected final validation failure")

    monkeypatch.setattr(exposure_writer, "_validate_stage", fail_validation)
    with pytest.raises(ValueError, match="injected final validation failure"):
        _publish(root, exposure_result)
    assert not (root / "r2-s3-writer-test").exists()
    assert not tuple(root.glob(".*.staging-*"))


def test_publish_final_handoff_never_replaces_raced_target(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "runs"
    target = root / "r2-s3-writer-test"
    real_handoff = exposure_writer._atomic_publish_no_replace

    def race_at_handoff(stage: Path, destination: Path) -> None:
        destination.mkdir()
        real_handoff(stage, destination)

    monkeypatch.setattr(
        exposure_writer,
        "_atomic_publish_no_replace",
        race_at_handoff,
        raising=False,
    )

    with pytest.raises(FileExistsError):
        _publish(root, exposure_result)

    assert target.is_dir()
    assert not tuple(target.iterdir())
    assert not tuple(root.glob(".*.staging-*"))


def test_publish_rejects_lexical_final_target_before_resolve(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "runs"
    root.mkdir()
    target = root / "r2-s3-writer-test"
    is_symlink = Path.is_symlink

    def mark_target_as_symlink(path: Path) -> bool:
        if path == target:
            return True
        return is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", mark_target_as_symlink)

    with pytest.raises(FileExistsError, match="already exists"):
        _publish(root, exposure_result)

    assert not target.exists()
    assert not tuple(root.glob(".*.staging-*"))


def test_publish_rejects_dangling_final_run_symlink_when_supported(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
) -> None:
    root = tmp_path / "runs"
    root.mkdir()
    target = root / "r2-s3-writer-test"
    referent = root / "redirected"
    try:
        target.symlink_to(referent.name, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    assert target.is_symlink() and not target.exists()

    with pytest.raises(FileExistsError, match="already exists"):
        _publish(root, exposure_result)

    assert target.is_symlink()
    assert not referent.exists()
    assert not tuple(root.glob(".*.staging-*"))


def test_verifier_rejects_checksum_and_noncanonical_jsonl_tampering(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
) -> None:
    first = _publish(tmp_path / "first", exposure_result)
    (first / "commands.txt").write_bytes(b"changed\n")
    with pytest.raises(ValueError, match="artifact evidence mismatch"):
        verify_exposure_run(first)

    second = _publish(tmp_path / "second", exposure_result)
    rows = (second / "per_unit.jsonl").read_text(encoding="utf-8").splitlines()
    rows[0] = json.dumps(json.loads(rows[0]), sort_keys=True)
    (second / "per_unit.jsonl").write_text(
        "\n".join(rows) + "\n", encoding="utf-8", newline=""
    )
    with pytest.raises(ValueError, match="not canonical JSON"):
        verify_exposure_run(second)


def test_verifier_rejects_symlinked_artifact_when_supported(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
) -> None:
    target = _publish(tmp_path / "runs", exposure_result)
    summary = target / "summary.json"
    backup = tmp_path / "summary.backup"
    summary.rename(backup)
    try:
        summary.symlink_to(backup.name)
    except OSError:
        backup.rename(summary)
        pytest.skip("symlinks are unavailable in this Windows environment")

    with pytest.raises(ValueError, match="regular files"):
        verify_exposure_run(target)


def test_verifier_rejects_lexical_top_level_symlink_before_resolve(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _publish(tmp_path / "runs", exposure_result)
    is_symlink = Path.is_symlink

    def mark_target_as_symlink(path: Path) -> bool:
        if path == target:
            return True
        return is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", mark_target_as_symlink)

    with pytest.raises(ValueError, match="run directory cannot be a symlink"):
        verify_exposure_run(target)


def test_verifier_rejects_top_level_run_symlink_when_supported(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
) -> None:
    target = _publish(tmp_path / "runs", exposure_result)
    alias = tmp_path / "run-alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(ValueError, match="run directory cannot be a symlink"):
        verify_exposure_run(alias)

    assert alias.is_symlink()
    assert target.is_dir()


def test_writer_rejects_coherent_row_and_summary_tampering_before_output(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
    verification_inputs: ExposureVerificationInputs,
) -> None:
    units = list(exposure_result.units)
    index = next(
        index
        for index, item in enumerate(units)
        if item.case_id == "synthetic-case-23"
    )
    row = units[index]
    units[index] = row.model_copy(
        update={
            "case_replay_additional_scan_units_at_2": 1,
            "case_replay_additional_scan_units_at_4": 1,
            "case_replay_additional_scan_input_chars_at_2": 1,
            "case_replay_additional_scan_input_chars_at_4": 1,
        }
    )
    frozen_units = tuple(
        ExposureUnitObservation.model_validate(item.model_dump(mode="python"))
        for item in units
    )
    tampered = exposure_result.model_copy(
        update={
            "units": frozen_units,
            "summary": recompute_exposure_summary(
                frozen_units,
                verification_inputs,
            ),
        }
    )
    root = tmp_path / "runs"

    with pytest.raises(ValueError, match="unit evidence SHA-256 mismatch"):
        publish_exposure_run(
            root,
            manifest=_manifest(tampered),
            result=tampered,
            source_inputs=object(),
            commands="safe\n",
            test_output="safe\n",
            forbidden_texts=("raw question",),
        )

    assert not (root / "r2-s3-writer-test").exists()


def test_writer_requires_source_bound_replay_before_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exposure_result: ExposureAnalysisResult,
) -> None:
    def reject_unbound_result(_inputs: object, _result: object) -> None:
        raise exposure.ExposureEvidenceError(
            "analysis result does not match source-bound replay"
        )

    monkeypatch.setattr(
        exposure_writer,
        "verify_exposure_result_against_inputs",
        reject_unbound_result,
        raising=False,
    )
    root = tmp_path / "runs"

    with pytest.raises(
        exposure.ExposureEvidenceError,
        match="analysis result does not match source-bound replay",
    ):
        publish_exposure_run(
            root,
            manifest=_manifest(exposure_result),
            result=exposure_result,
            source_inputs=object(),
            commands="safe\n",
            test_output="safe\n",
            forbidden_texts=("raw question",),
        )

    assert not (root / "r2-s3-writer-test").exists()


def test_writer_does_not_derive_non_row_witnesses_from_tampered_summary(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
) -> None:
    payload = exposure_result.summary.model_dump(mode="python")
    payload["clean_task_success"] = {
        "numerator": 11,
        "denominator": 12,
        "rate": 11 / 12,
        "applicable": True,
    }
    summary = exposure_result.summary.model_validate(payload)
    tampered = exposure_result.model_copy(update={"summary": summary})
    root = tmp_path / "runs"

    with pytest.raises(ValueError, match="analysis summary does not recompute"):
        publish_exposure_run(
            root,
            manifest=_manifest(tampered),
            result=tampered,
            source_inputs=object(),
            commands="safe\n",
            test_output="safe\n",
            forbidden_texts=("raw question",),
        )

    assert not (root / "r2-s3-writer-test").exists()


def test_writer_requires_exact_ordered_limitations(
    tmp_path: Path,
    exposure_result: ExposureAnalysisResult,
) -> None:
    tampered = exposure_result.model_copy(
        update={"limitations": ("Replacement limitation.",)}
    )
    manifest = _manifest(exposure_result).model_copy(
        update={"limitations": tampered.limitations}
    )
    root = tmp_path / "runs"

    with pytest.raises(ValueError, match="limitations must be exact"):
        publish_exposure_run(
            root,
            manifest=manifest,
            result=tampered,
            source_inputs=object(),
            commands="safe\n",
            test_output="safe\n",
            forbidden_texts=("raw question",),
        )

    assert not (root / "r2-s3-writer-test").exists()
