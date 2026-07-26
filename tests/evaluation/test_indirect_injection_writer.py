from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation import indirect_injection_writer as writer_module
from app.domain.retrieved_security import DETECTOR_VERSION
from app.evaluation.indirect_injection_dataset import (
    build_v1_bundle,
    load_security_bundle,
)
from app.evaluation.indirect_injection_runner import evaluate_paired
from app.evaluation.indirect_injection_writer import (
    SecurityRunManifest,
    build_release_gate,
    publish_security_run,
)


FROZEN_AT = "2026-07-18T00:00:00Z"
FREEZE_HEAD = "a" * 40


@pytest.fixture(scope="module")
def evaluated_bundle(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("security-writer") / "security"
    build_v1_bundle(
        root,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    bundle = load_security_bundle(root, "test")
    return bundle, evaluate_paired(bundle.dataset, bundle.fixture_manifest)


def _manifest(result, *, run_id: str = "r2-s1-d6-test-unit") -> SecurityRunManifest:
    now = datetime(2026, 7, 18, tzinfo=timezone.utc)
    release = build_release_gate(
        result,
        r1_hash_mismatch_count=0,
        r1_regression_failure_count=0,
    )
    return SecurityRunManifest.model_validate(
        {
            "schema_version": "indirect_injection_security_run_manifest_v1",
            "producer": "enterprise_agentic_rag_v2",
            "run_id": run_id,
            "suite": "retrieved_content_indirect_injection",
            "split": result.split,
            "mode": "deterministic_paired",
            "started_at_utc": now,
            "completed_at_utc": now,
            "status": release.status,
            "git": {
                "head": "a" * 40,
                "branch": "codex/test",
                "dirty": True,
                "status_entry_count": 1,
                "dirty_state_sha256": "b" * 64,
            },
            "environment": {
                "python_version": "3.11.9",
                "platform": "test-platform",
                "dependency_snapshot_path": "requirements.txt",
                "dependency_snapshot_sha256": "c" * 64,
                "dependency_snapshot_kind": "pinned-direct-requirements",
                "installed_snapshot_command": (
                    "python",
                    "-m",
                    "pip",
                    "freeze",
                    "--all",
                ),
                "installed_snapshot_sha256": "1" * 64,
                "installed_package_count": 20,
                "ollama_version": "NOT_QUERIED_D6_DETERMINISTIC",
            },
            "models": {
                "embedding_model": "NOT_USED_D6_DETERMINISTIC",
                "chat_model": "d6-deterministic-fake-chat",
                "evidence_model": "NOT_USED_D6_DETERMINISTIC",
                "temperature": 0.0,
                "structured_output_variant": "generation-v2-json-schema",
            },
            "guard": {
                "detector_version": DETECTOR_VERSION,
                "ruleset_path": "app/security/retrieved_content.py",
                "ruleset_sha256": "d" * 64,
                "max_scan_chars": 20_000,
                "max_normalized_chars": 20_000,
                "max_decoded_views": 8,
            },
            "data": {
                "dataset_path": "data/v2/security/indirect_injection_test_v1.json",
                "dataset_sha256": "e" * 64,
                "dataset_case_count": 36,
                "fixture_manifest_path": "data/v2/security/fixtures_v1/test/manifest.json",
                "fixture_manifest_sha256": "f" * 64,
                "attack_case_count": 24,
                "benign_case_count": 12,
                "r1_frozen_hashes": {
                    "data/v2/eval/dev.json": {
                        "expected": "92b4753df4e69bb570e9ea202420b46124207f15a07cdbb421fb00e6990082bd",
                        "actual": "92b4753df4e69bb570e9ea202420b46124207f15a07cdbb421fb00e6990082bd",
                    },
                    "data/v2/eval/test.json": {
                        "expected": "556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338",
                        "actual": "556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338",
                    },
                    "data/v2/eval/test_manifest.sha256": {
                        "expected": "fc9151daee0d6a0ac1ecfd1b6a3e361bc985d3f8512a8bc76927528ecd32f253",
                        "actual": "fc9151daee0d6a0ac1ecfd1b6a3e361bc985d3f8512a8bc76927528ecd32f253",
                    },
                },
            },
            "evaluator": {
                "path": "app/evaluation/indirect_injection_runner.py",
                "sha256": "4" * 64,
                "argv": (
                    "python",
                    "-m",
                    "scripts.eval_indirect_injection",
                    "--split",
                    "test",
                ),
                "exit_code": 0,
            },
            "retrieval": {
                "index": "synthetic-ranked-fixtures-v1",
                "index_sha256": "NOT_APPLICABLE_DETERMINISTIC_FIXTURE",
                "corpus": "checked-in-post-parser-synthetic-fixtures-v1",
                "corpus_sha256": "f" * 64,
                "chunking": "post-parser-synthetic-content-units-v1",
                "top_k": 1,
                "candidate_k": 4,
                "max_search_calls": 1,
                "max_open_calls": 1,
                "max_steps": 3,
                "max_context_chars": 50_000,
            },
            "release_gate": release,
            "artifacts": {},
            "limitations": (
                "Deterministic fake generation proves propagation, not live-model resistance.",
            ),
        }
    )


def _forbidden_texts(bundle) -> tuple[str, ...]:
    values: list[str] = []
    for case in bundle.dataset.cases:
        if case.document_canary:
            values.append(case.document_canary)
        values.append(case.trace_canary)
    for fixture in bundle.fixture_manifest.cases:
        for candidate in fixture.candidates:
            values.extend((candidate.matched_text, candidate.context_text))
        values.extend(item.content for item in fixture.open_results)
    return tuple(values)


def test_writer_publishes_exact_immutable_artifacts_with_hashes(
    tmp_path: Path,
    evaluated_bundle,
) -> None:
    bundle, result = evaluated_bundle
    output = publish_security_run(
        tmp_path / "security_runs",
        _manifest(result),
        result,
        red_green_evidence="# RED/GREEN\n\nSynthetic evidence only.\n",
        commands="python -m pytest -q\n",
        test_output="30 passed in 1.65s\n",
        forbidden_texts=_forbidden_texts(bundle),
    )

    expected = {
        "manifest.json",
        "summary.json",
        "per_case.jsonl",
        "failures.csv",
        "red_green_evidence.md",
        "commands.txt",
        "test_output.txt",
        "checksums.sha256",
    }
    assert {path.name for path in output.iterdir()} == expected
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["artifacts"]) == expected - {"manifest.json"}
    for name, evidence in manifest["artifacts"].items():
        content = (output / name).read_bytes()
        assert evidence["bytes"] == len(content)
        assert evidence["sha256"] == hashlib.sha256(content).hexdigest()

    checksum_lines = (output / "checksums.sha256").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(checksum_lines) == 6
    assert all("  " in line for line in checksum_lines)
    assert len((output / "per_case.jsonl").read_text(encoding="utf-8").splitlines()) == 72


def test_writer_refuses_overwrite_and_cleans_same_parent_stage(
    tmp_path: Path,
    evaluated_bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, result = evaluated_bundle
    root = tmp_path / "security_runs"
    kwargs = {
        "red_green_evidence": "# Evidence\n",
        "commands": "pytest -q\n",
        "test_output": "passed\n",
        "forbidden_texts": _forbidden_texts(bundle),
    }
    publish_security_run(root, _manifest(result), result, **kwargs)
    with pytest.raises(FileExistsError, match="already exists"):
        publish_security_run(root, _manifest(result), result, **kwargs)

    failing_manifest = _manifest(result, run_id="r2-s1-d6-test-rename-failure")

    def fail_rename(source: Path, target: Path):
        del source, target
        raise OSError("synthetic promotion failure")

    monkeypatch.setattr(writer_module, "atomic_directory_move", fail_rename)
    with pytest.raises(OSError, match="synthetic promotion"):
        publish_security_run(root, failing_manifest, result, **kwargs)
    assert not (root / failing_manifest.run_id).exists()
    assert list(root.glob(f".{failing_manifest.run_id}.staging-*")) == []


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "R2DOC_TEST_SHOULD_NOT_LEAK",
        "r2doc_test_should_not_leak",
        "C:/Users/example/private/security.json",
        "/home/example/private/security.json",
        "/var/lib/private/security.json",
        r"\\server\share\private\security.json",
        r"\\?\C:\private\security.json",
        "api_key=sk-test-1234567890abcdef",
        "-----BEGIN " + "PRIVATE KEY-----",
    ],
)
def test_writer_rejects_raw_canaries_and_absolute_paths(
    tmp_path: Path,
    evaluated_bundle,
    unsafe_text: str,
) -> None:
    bundle, result = evaluated_bundle
    with pytest.raises(ValueError, match="forbidden content"):
        publish_security_run(
            tmp_path / "security_runs",
            _manifest(result, run_id="r2-s1-d6-unsafe-output"),
            result,
            red_green_evidence="# Evidence\n",
            commands="pytest -q\n",
            test_output=unsafe_text,
            forbidden_texts=_forbidden_texts(bundle),
        )


def test_writer_requires_nonempty_fixture_leakage_policy(
    tmp_path: Path,
    evaluated_bundle,
) -> None:
    _, result = evaluated_bundle

    with pytest.raises(ValueError, match="forbidden text policy is required"):
        publish_security_run(
            tmp_path / "runs",
            _manifest(result, run_id="missing-leakage-policy"),
            result,
            red_green_evidence="# Evidence\n",
            commands="pytest -q\n",
            test_output="passed\n",
            forbidden_texts=(),
        )


def test_writer_rejects_json_escaped_fixture_text(
    tmp_path: Path,
    evaluated_bundle,
) -> None:
    bundle, result = evaluated_bundle
    raw = next(
        candidate.matched_text
        for fixture in bundle.fixture_manifest.cases
        for candidate in fixture.candidates
        if "\n" in candidate.matched_text
    )
    escaped = json.dumps(raw, ensure_ascii=False)[1:-1]

    with pytest.raises(ValueError, match="forbidden content"):
        publish_security_run(
            tmp_path / "runs",
            _manifest(result, run_id="escaped-fixture-output"),
            result,
            red_green_evidence="# Evidence\n",
            commands="pytest -q\n",
            test_output=escaped,
            forbidden_texts=_forbidden_texts(bundle),
        )


def test_manifest_rejects_scalar_type_coercion(evaluated_bundle) -> None:
    _, result = evaluated_bundle
    payload = _manifest(result).model_dump()
    payload["git"]["status_entry_count"] = "1"

    with pytest.raises(ValidationError):
        SecurityRunManifest.model_validate(payload)


def test_manifest_records_declared_and_installed_dependency_snapshots(
    evaluated_bundle,
) -> None:
    _, result = evaluated_bundle
    payload = _manifest(result).model_dump()
    payload["environment"] = {
        "python_version": "3.11.9",
        "platform": "test-platform",
        "dependency_snapshot_path": "requirements.txt",
        "dependency_snapshot_sha256": "c" * 64,
        "dependency_snapshot_kind": "pinned-direct-requirements",
        "installed_snapshot_command": ("python", "-m", "pip", "freeze", "--all"),
        "installed_snapshot_sha256": "1" * 64,
        "installed_package_count": 20,
        "ollama_version": "NOT_QUERIED_D6_DETERMINISTIC",
    }

    manifest = SecurityRunManifest.model_validate(payload)

    assert manifest.environment.dependency_snapshot_path == "requirements.txt"
    assert manifest.environment.installed_package_count == 20


@pytest.mark.parametrize(
    "run_id",
    ["CON", "con.txt", "NUL", "COM1.log", "LPT9", "trailing."],
)
def test_manifest_rejects_windows_unsafe_run_ids(
    evaluated_bundle,
    run_id: str,
) -> None:
    _, result = evaluated_bundle

    with pytest.raises(ValidationError, match="run ID"):
        _manifest(result, run_id=run_id)


def test_manifest_binds_corpus_hash_to_fixture_manifest(evaluated_bundle) -> None:
    _, result = evaluated_bundle
    payload = _manifest(result).model_dump()
    payload["retrieval"]["corpus_sha256"] = "0" * 64

    with pytest.raises(ValidationError, match="corpus hash"):
        SecurityRunManifest.model_validate(payload)


def test_test_manifest_rejects_dev_diagnostic_status(evaluated_bundle) -> None:
    _, result = evaluated_bundle
    payload = _manifest(result).model_dump()
    payload["status"] = "PASSED DEV DIAGNOSTIC"
    payload["release_gate"]["status"] = "PASSED DEV DIAGNOSTIC"

    with pytest.raises(ValidationError, match="test run status"):
        SecurityRunManifest.model_validate(payload)


def test_release_gate_rejects_missing_required_checks(evaluated_bundle) -> None:
    _, result = evaluated_bundle
    payload = _manifest(result).model_dump()
    payload["release_gate"]["checks"] = ()
    payload["release_gate"]["failures"] = ()

    with pytest.raises(ValidationError, match="exact required check sequence"):
        SecurityRunManifest.model_validate(payload)


def test_manifest_rejects_fabricated_r1_expected_hash(evaluated_bundle) -> None:
    _, result = evaluated_bundle
    payload = _manifest(result).model_dump()
    payload["data"]["r1_frozen_hashes"]["data/v2/eval/dev.json"] = {
        "expected": "f" * 64,
        "actual": "f" * 64,
    }

    with pytest.raises(ValidationError, match="frozen expected digest"):
        SecurityRunManifest.model_validate(payload)


def test_manifest_r1_mismatch_count_must_match_hash_evidence(
    evaluated_bundle,
) -> None:
    _, result = evaluated_bundle
    payload = _manifest(result).model_dump()
    payload["data"]["r1_frozen_hashes"]["data/v2/eval/dev.json"]["actual"] = (
        "f" * 64
    )

    with pytest.raises(ValidationError, match="R1 mismatch count"):
        SecurityRunManifest.model_validate(payload)


def test_writer_binds_release_behavior_checks_to_evaluator_result(
    tmp_path: Path,
    evaluated_bundle,
) -> None:
    bundle, result = evaluated_bundle
    payload = _manifest(result, run_id="mismatched-behavior-evidence").model_dump()
    checks = list(payload["release_gate"]["checks"])
    checks[0]["observed_denominator"] = 999
    payload["release_gate"]["checks"] = tuple(checks)
    manifest = SecurityRunManifest.model_validate(payload)

    with pytest.raises(ValueError, match="behavior checks do not match"):
        publish_security_run(
            tmp_path / "runs",
            manifest,
            result,
            red_green_evidence="# Evidence\n",
            commands="pytest -q\n",
            test_output="passed\n",
            forbidden_texts=_forbidden_texts(bundle),
        )
