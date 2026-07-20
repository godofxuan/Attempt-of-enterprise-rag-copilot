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
