from __future__ import annotations

import hashlib
import json
import shutil
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
