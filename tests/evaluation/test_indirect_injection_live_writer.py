from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation import indirect_injection_exposure_writer as exposure_writer
from app.evaluation import indirect_injection_live_writer as live_writer
from app.evaluation.indirect_injection_cross_model import load_cross_model_plan
from app.evaluation.indirect_injection_arm_order import (
    build_counterbalanced_arm_order_plan,
)
from app.evaluation.indirect_injection_dataset import (
    build_v1_bundle,
    load_security_bundle,
)
from app.evaluation.indirect_injection_live_index import (
    build_live_fixture_index,
)
from app.evaluation.indirect_injection_live_runner import (
    LiveSecurityConfig,
    evaluate_live_paired,
)
from app.evaluation.indirect_injection_live_writer import (
    LiveSecurityRunManifest,
    OllamaModelIdentity,
    publish_live_security_run,
)
from app.evaluation.indirect_injection_writer import (
    R1_FROZEN_EXPECTED_HASHES,
)
from tests.evaluation.path_redirect_helpers import (
    directory_redirect,
    with_reparse_point_attribute,
)
from tests.evaluation.test_indirect_injection_live_runner import (
    BUILD_TIME,
    FIXTURE_SHA256,
    FREEZE_HEAD,
    FROZEN_AT,
    _StructuredFixtureChat,
    _embedding,
)


COMPLETED_TIME = datetime(2026, 7, 18, 1, 3, 4, tzinfo=timezone.utc)
PLAN_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "v2"
    / "evaluation"
    / "r2_s4_cross_model_matrix_v1.json"
)
PLAN, PLAN_SHA256 = load_cross_model_plan(PLAN_PATH)


@pytest.fixture(scope="module")
def writer_inputs(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("d7-live-writer")
    security_root = root / "security-data"
    build_v1_bundle(
        security_root,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    bundle = load_security_bundle(security_root, "test")
    built = build_live_fixture_index(
        dataset=bundle.dataset,
        fixtures=bundle.fixture_manifest,
        root=root / "security-index",
        run_id="r2-s1-d7-writer-index",
        fixture_sha256=FIXTURE_SHA256,
        embedding_model="bge-m3",
        embed_text=_embedding,
        started_at=BUILD_TIME,
        finished_at=BUILD_TIME,
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
    )
    return bundle, built, result


@pytest.fixture(scope="module")
def writer_v2_inputs(writer_inputs):
    bundle, built, _ = writer_inputs
    plan = build_counterbalanced_arm_order_plan(
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
        arm_order=plan,
    )
    return bundle, built, result


@pytest.fixture(scope="module")
def writer_v3_inputs(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("r2-s4-live-writer")
    security_root = root / "security-data"
    build_v1_bundle(
        security_root,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    bundle = load_security_bundle(security_root, "dev")
    built = build_live_fixture_index(
        dataset=bundle.dataset,
        fixtures=bundle.fixture_manifest,
        root=root / "security-index",
        run_id="r2-s4-live-writer-index",
        fixture_sha256=bundle.fixture_manifest_sha256,
        embedding_model="bge-m3",
        embed_text=_embedding,
        started_at=BUILD_TIME,
        finished_at=BUILD_TIME,
    )
    plan = build_counterbalanced_arm_order_plan(
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
            chat_model="qwen3:8b",
        ),
        clock_ms=lambda: 1_000.0,
        arm_order=plan,
    )
    return bundle, built, result


def _identity(name: str, digest_seed: str, capability: str) -> OllamaModelIdentity:
    return OllamaModelIdentity(
        requested_name=name,
        resolved_name=name if ":" in name else name + ":latest",
        digest=hashlib.sha256(digest_seed.encode("utf-8")).hexdigest(),
        size_bytes=123,
        format="gguf",
        family="qwen2" if capability == "completion" else "bert",
        parameter_size="3B" if capability == "completion" else "567M",
        quantization_level="Q4_K_M" if capability == "completion" else "F16",
        context_length=32_768,
        embedding_length=2_048 if capability == "completion" else 1_024,
        capabilities=(capability,),
    )


def _manifest(bundle, built, result) -> LiveSecurityRunManifest:
    return LiveSecurityRunManifest.model_validate(
        {
            "schema_version": "indirect_injection_live_security_run_manifest_v1",
            "producer": "enterprise_agentic_rag_v2",
            "run_id": "r2-s1-d7-live-writer-test",
            "suite": "retrieved_content_indirect_injection",
            "split": "test",
            "mode": "local_live_paired",
            "started_at_utc": BUILD_TIME,
            "completed_at_utc": COMPLETED_TIME,
            "status": result.status,
            "git": {
                "head": "a" * 40,
                "branch": "codex/rag-eval-system",
                "dirty": False,
                "status_entry_count": 0,
                "dirty_state_sha256": "b" * 64,
            },
            "environment": {
                "python_version": "3.11.9",
                "platform": "Windows-test",
                "dependency_snapshot_path": "requirements.txt",
                "dependency_snapshot_sha256": "c" * 64,
                "installed_snapshot_sha256": "d" * 64,
                "installed_package_count": 50,
                "ollama_version": "0.32.1",
                "ollama_endpoint": "http://127.0.0.1:11434",
            },
            "models": {
                "embedding": _identity("bge-m3", "embed", "embedding"),
                "chat": _identity("qwen2.5:3b", "chat", "completion"),
                "evidence_model": "NOT_USED_D7_LIVE_PAIRED",
                "temperature": 0.0,
                "structured_output_variant": "generation-v2-json-schema",
                "think": False,
                "max_attempts": 2,
            },
            "guard": {
                "detector_version": "r2_s1_retrieved_content_guard_v1",
                "ruleset_path": "app/security/retrieved_content.py",
                "ruleset_sha256": "e" * 64,
                "max_scan_chars": 20_000,
                "max_normalized_chars": 40_000,
                "max_decoded_views": 4,
            },
            "data": {
                "dataset_path": "data/v2/security/indirect_injection_test_v1.json",
                "dataset_sha256": bundle.dataset_sha256,
                "dataset_case_count": 36,
                "fixture_manifest_path": (
                    "data/v2/security/fixtures_v1/test/manifest.json"
                ),
                "fixture_manifest_sha256": bundle.fixture_manifest_sha256,
                "attack_case_count": 24,
                "benign_case_count": 12,
                "r1_frozen_hashes": {
                    path: {"expected": digest, "actual": digest}
                    for path, digest in R1_FROZEN_EXPECTED_HASHES.items()
                },
            },
            "evaluator": {
                "path": "app/evaluation/indirect_injection_live_runner.py",
                "sha256": "f" * 64,
                "argv": (
                    "python",
                    "-m",
                    "scripts.eval_indirect_injection_live",
                    "--split",
                    "test",
                ),
                "exit_code": 0,
            },
            "retrieval": {
                "production_active_index": {
                    "role": "production_active_reference",
                    "run_id": "production-index",
                    "active_pointer_sha256": "1" * 64,
                    "manifest_sha256": "2" * 64,
                    "corpus_sha256": "3" * 64,
                    "embedding_model": "bge-m3",
                    "embedding_dimension": 1_024,
                    "indexed_chunk_count": 100,
                },
                "security_fixture_index": {
                    "role": "security_fixture_runtime",
                    "run_id": built.manifest.run_id,
                    "active_pointer_sha256": "4" * 64,
                    "manifest_sha256": built.manifest_sha256,
                    "corpus_sha256": bundle.fixture_manifest_sha256,
                    "embedding_model": "bge-m3",
                    "embedding_dimension": 8,
                    "indexed_chunk_count": built.manifest.indexed_chunk_count,
                },
                "chunking": "post-parser-security-fixture-projection-v1",
                "top_k": 1,
                "candidate_k": 4,
                "max_search_calls": 1,
                "max_open_calls": 1,
                "max_steps": 3,
                "max_context_chars": 50_000,
                "index_embedding_call_count": built.embedding_call_count,
                "embedding_request_count": result.embedding_request_count,
                "embedding_delegate_call_count": (
                    result.embedding_delegate_call_count
                ),
                "embedding_cache_hit_count": result.embedding_cache_hit_count,
            },
            "observation": {
                "status": result.status,
                "protocol_complete": result.protocol_complete,
                "pair_input_consistent": result.pair_input_consistent,
                "deterministic_threshold_diagnostic_passed": (
                    result.security.gate.passed
                ),
            },
            "artifacts": {},
            "limitations": (
                "This is one local model run, not a universal model-safety claim.",
                "The frozen test set is visible regression data, not unseen data.",
                "The production active index is provenance only; synthetic attacks use the isolated security index.",
            ),
        }
    )


def _manifest_v2(bundle, built, result):
    payload = _manifest(bundle, built, result).model_dump(mode="python")
    payload.update(
        {
            "schema_version": "indirect_injection_live_security_run_manifest_v2",
            "run_id": "r2-s1-v5-live-writer-test",
            "mode": "local_live_paired_counterbalanced",
            "arm_order": result.arm_order,
        }
    )
    return live_writer.LiveSecurityRunManifestV2.model_validate(payload)


def _manifest_v3(bundle, built, result):
    payload = _manifest(bundle, built, result).model_dump(mode="python")
    payload.update(
        {
            "schema_version": "indirect_injection_live_security_run_manifest_v3",
            "run_id": "r2-s4-live-writer-test",
            "split": "dev",
            "mode": "local_live_paired_counterbalanced_cross_model_dev",
            "arm_order": result.arm_order,
            "experiment": {
                "plan_id": "r2-s4-cross-model-dev-v1",
                "plan_sha256": PLAN_SHA256,
                "model_role": "replication",
                "only_changed_variable": "chat_model_identity",
            },
        }
    )
    payload["data"].update(
        {
            "dataset_path": "data/v2/security/indirect_injection_dev_v1.json",
            "dataset_sha256": bundle.dataset_sha256,
            "fixture_manifest_path": (
                "data/v2/security/fixtures_v1/dev/manifest.json"
            ),
            "fixture_manifest_sha256": bundle.fixture_manifest_sha256,
        }
    )
    payload["retrieval"]["security_fixture_index"].update(
        {
            "run_id": built.manifest.run_id,
            "manifest_sha256": built.manifest_sha256,
            "corpus_sha256": bundle.fixture_manifest_sha256,
            "indexed_chunk_count": built.manifest.indexed_chunk_count,
        }
    )
    payload["models"]["chat"] = _identity(
        "qwen3:8b",
        "replication-chat",
        "completion",
    ).model_copy(
        update={
            "digest": PLAN.model_for_role("replication").digest,
            "family": PLAN.model_for_role("replication").family,
            "parameter_size": PLAN.model_for_role("replication").parameter_size,
        }
    )
    payload["models"]["embedding"].update(
        {
            "digest": PLAN.embedding.digest,
        }
    )
    payload["transport"] = {
        "model_request_timeout_seconds": 12.0,
        "model_max_attempts": 2,
        "model_retry_backoff_ms": 100,
    }
    return live_writer.LiveSecurityRunManifestV3.model_validate(payload)


def _forbidden_texts(bundle) -> tuple[str, ...]:
    values: set[str] = set()
    for case in bundle.dataset.cases:
        values.add(case.question)
        values.add(case.trace_canary)
        if case.document_canary:
            values.add(case.document_canary)
    for fixture in bundle.fixture_manifest.cases:
        values.update(fixture.fact_texts.values())
        for candidate in fixture.candidates:
            values.update((candidate.matched_text, candidate.context_text))
        for opened in fixture.open_results:
            values.add(opened.content)
    return tuple(sorted(values))


def test_v3_experiment_binding_requires_exact_contract() -> None:
    binding = live_writer.CrossModelExperimentBinding(
        plan_id="r2-s4-cross-model-dev-v1",
        plan_sha256="a" * 64,
        model_role="replication",
        only_changed_variable="chat_model_identity",
    )

    assert binding.model_role == "replication"

    for field, value in (
        ("plan_id", "another-plan"),
        ("plan_sha256", "altered"),
        ("model_role", "observer"),
        ("only_changed_variable", "chat_and_embedding_model_identity"),
    ):
        with pytest.raises(ValidationError):
            live_writer.CrossModelExperimentBinding.model_validate(
                binding.model_copy(update={field: value}).model_dump(mode="python")
            )


def test_publish_and_verify_v3_live_run(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, built, result = writer_v3_inputs
    manifest = _manifest_v3(bundle, built, result)

    target = publish_live_security_run(
        tmp_path / "runs",
        manifest,
        result,
        paired_evidence="safe",
        commands="safe",
        test_output="safe",
        forbidden_texts=_forbidden_texts(bundle),
    )
    verified = live_writer.verify_live_security_run(target)

    assert type(verified) is live_writer.LiveSecurityRunManifestV3
    assert verified.schema_version == (
        "indirect_injection_live_security_run_manifest_v3"
    )
    assert verified.experiment == manifest.experiment


def test_v3_requires_typed_transport_provenance(writer_v3_inputs) -> None:
    bundle, built, result = writer_v3_inputs
    payload = _manifest_v3(bundle, built, result).model_dump(mode="python")

    payload.pop("transport")
    with pytest.raises(ValidationError, match="transport"):
        live_writer.LiveSecurityRunManifestV3.model_validate(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("experiment", "plan_sha256"), "altered"),
        (("experiment", "model_role"), "observer"),
        (("models", "chat", "digest"), "altered"),
    ),
)
def test_v3_verifier_rejects_invalid_manifest_identity_fields(
    tmp_path: Path,
    writer_v3_inputs,
    path: tuple[str, ...],
    value: str,
) -> None:
    bundle, built, result = writer_v3_inputs
    manifest = _manifest_v3(bundle, built, result)
    target = publish_live_security_run(
        tmp_path / "runs",
        manifest,
        result,
        paired_evidence="safe",
        commands="safe",
        test_output="safe",
        forbidden_texts=_forbidden_texts(bundle),
    )
    payload = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    cursor = payload
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    (target / "manifest.json").write_bytes(live_writer._json_bytes(payload))

    with pytest.raises(ValidationError):
        live_writer.verify_live_security_run(target)


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("experiment", "plan_sha256"), "b" * 64),
        (("experiment", "model_role"), "baseline"),
        (("models", "chat", "requested_name"), "qwen2.5:3b"),
        (("models", "chat", "resolved_name"), "qwen3:8b-alternate"),
        (("models", "chat", "digest"), "c" * 64),
        (("models", "chat", "family"), "qwen2"),
        (("models", "chat", "parameter_size"), "8.1B"),
        (("models", "embedding", "requested_name"), "bge-m3-alternate"),
        (("models", "embedding", "resolved_name"), "bge-m3:alternate"),
        (("models", "embedding", "digest"), "d" * 64),
    ),
)
def test_v3_verifier_rejects_valid_identity_contradictions(
    tmp_path: Path,
    writer_v3_inputs,
    path: tuple[str, ...],
    value: str,
) -> None:
    bundle, built, result = writer_v3_inputs
    manifest = _manifest_v3(bundle, built, result)
    target = publish_live_security_run(
        tmp_path / "runs",
        manifest,
        result,
        paired_evidence="safe",
        commands="safe",
        test_output="safe",
        forbidden_texts=_forbidden_texts(bundle),
    )
    payload = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    cursor = payload
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    if path == ("models", "embedding", "requested_name"):
        payload["retrieval"]["security_fixture_index"]["embedding_model"] = value
    (target / "manifest.json").write_bytes(live_writer._json_bytes(payload))

    with pytest.raises(ValueError, match="checked-in cross-model plan"):
        live_writer.verify_live_security_run(target)


def test_v3_verifier_rejects_altered_artifact_bytes(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, built, result = writer_v3_inputs
    manifest = _manifest_v3(bundle, built, result)
    target = publish_live_security_run(
        tmp_path / "runs",
        manifest,
        result,
        paired_evidence="safe",
        commands="safe",
        test_output="safe",
        forbidden_texts=_forbidden_texts(bundle),
    )
    with (target / "commands.txt").open("a", encoding="utf-8") as stream:
        stream.write("altered\n")

    with pytest.raises(ValueError, match="artifact evidence mismatch"):
        live_writer.verify_live_security_run(target)


def test_v3_verifier_rejects_self_consistent_contradictory_summary(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, built, result = writer_v3_inputs
    target = publish_live_security_run(
        tmp_path / "runs",
        _manifest_v3(bundle, built, result),
        result,
        paired_evidence="safe",
        commands="safe",
        test_output="safe",
        forbidden_texts=_forbidden_texts(bundle),
    )
    summary_path = target / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["guard_off_live"]["case_count"] += 1
    summary_path.write_bytes(live_writer._json_bytes(summary))
    _rewrite_v3_integrity_metadata(target)

    with pytest.raises(ValueError, match="summary"):
        live_writer.verify_live_security_run(target)


def test_v3_verifier_rejects_protocol_complete_generation_system_error_rows(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, built, result = writer_v3_inputs
    manifest = _manifest_v3(bundle, built, result)
    target = publish_live_security_run(
        tmp_path / "runs",
        manifest,
        result,
        paired_evidence="safe",
        commands="safe",
        test_output="safe",
        forbidden_texts=_forbidden_texts(bundle),
    )
    rows_path = target / "per_case.jsonl"
    rows = rows_path.read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    first["security"]["answer_mode"] = "system"
    rows[0] = json.dumps(first, ensure_ascii=False, sort_keys=True)
    rows_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    summary_path = target / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    off_security, on_security, off_live, _ = live_writer._validate_v2_per_case_rows(
        rows_path.read_bytes(),
        manifest,
    )
    off_security_summary = live_writer._mode_result("off", off_security).summary
    on_security_summary = live_writer._mode_result("on", on_security).summary
    summary["guard_off_live"] = live_writer._summarize_live_mode(
        "off",
        off_live,
        off_security,
    ).model_dump(mode="json")
    summary["guard_off_security"] = off_security_summary.model_dump(mode="json")
    summary["guard_on_security"] = on_security_summary.model_dump(mode="json")
    summary["deterministic_threshold_diagnostic"] = live_writer._build_behavior_gate(
        manifest.split,
        off_security_summary,
        on_security_summary,
    ).model_dump(mode="json")
    summary_path.write_bytes(live_writer._json_bytes(summary))
    _rewrite_v3_integrity_metadata(target)

    with pytest.raises(ValueError, match="observation"):
        live_writer.verify_live_security_run(target)


def test_v3_verifier_rejects_self_consistent_contradictory_arm_order(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    bundle, built, result = writer_v3_inputs
    target = publish_live_security_run(
        tmp_path / "runs",
        _manifest_v3(bundle, built, result),
        result,
        paired_evidence="safe",
        commands="safe",
        test_output="safe",
        forbidden_texts=_forbidden_texts(bundle),
    )
    rows_path = target / "per_case.jsonl"
    rows = rows_path.read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    first["arm_execution"]["arm_position"] = 2
    rows[0] = json.dumps(first, ensure_ascii=False, sort_keys=True)
    rows_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    _rewrite_v3_integrity_metadata(target)

    with pytest.raises(ValueError, match="arm position"):
        live_writer.verify_live_security_run(target)


def _rewrite_v3_integrity_metadata(target: Path) -> None:
    checksum_payload = "".join(
        f"{live_writer._sha256(target / name)}  {name}\n"
        for name in live_writer._CHECKSUM_CONTENT_NAMES
    ).encode("utf-8")
    (target / "checksums.sha256").write_bytes(checksum_payload)
    payload = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    payload["artifacts"] = {
        name: {
            "path": name,
            "bytes": (target / name).stat().st_size,
            "sha256": live_writer._sha256(target / name),
        }
        for name in sorted(live_writer._ARTIFACT_NAMES)
    }
    (target / "manifest.json").write_bytes(live_writer._json_bytes(payload))


def test_publish_live_run_is_immutable_complete_and_content_free(
    tmp_path: Path,
    writer_inputs,
) -> None:
    bundle, built, result = writer_inputs
    manifest = _manifest(bundle, built, result)
    out = tmp_path / "runs"

    target = publish_live_security_run(
        out,
        manifest,
        result,
        paired_evidence="# D7 live paired evidence\n\nObserved counts only.\n",
        commands="python -m scripts.eval_indirect_injection_live --split test\n",
        test_output="Ollama/model/index preflight passed.\n",
        forbidden_texts=_forbidden_texts(bundle),
    )

    assert {path.name for path in target.iterdir()} == {
        "manifest.json",
        "summary.json",
        "per_case.jsonl",
        "failures.csv",
        "red_green_evidence.md",
        "commands.txt",
        "test_output.txt",
        "checksums.sha256",
    }
    parsed = LiveSecurityRunManifest.model_validate_json(
        (target / "manifest.json").read_bytes()
    )
    assert parsed.status == "COMPLETED WITH OBSERVATIONS"
    assert set(parsed.artifacts) == {
        "summary.json",
        "per_case.jsonl",
        "failures.csv",
        "red_green_evidence.md",
        "commands.txt",
        "test_output.txt",
        "checksums.sha256",
    }

    all_content = b"\n".join(path.read_bytes() for path in target.iterdir())
    decoded = all_content.decode("utf-8")
    for forbidden in _forbidden_texts(bundle):
        assert forbidden not in decoded
    assert str(tmp_path) not in decoded

    with pytest.raises(FileExistsError):
        publish_live_security_run(
            out,
            manifest,
            result,
            paired_evidence="same",
            commands="same",
            test_output="same",
            forbidden_texts=_forbidden_texts(bundle),
        )


def test_publish_live_rejects_real_windows_output_root_junction_without_touching_referent(
    tmp_path: Path,
    writer_v2_inputs,
) -> None:
    bundle, built, result = writer_v2_inputs
    manifest = _manifest_v2(bundle, built, result)
    referent = tmp_path / "live-referent"
    referent.mkdir()
    marker = referent / "keep.txt"
    marker.write_text("keep\n", encoding="utf-8")
    alias = tmp_path / "live-junction"

    with directory_redirect(
        alias,
        referent,
        windows_junction_only=True,
    ) as primitive:
        assert primitive == "junction"
        with pytest.raises(
            ValueError,
            match="output root cannot be a symlink or redirecting reparse point",
        ):
            publish_live_security_run(
                alias,
                manifest,
                result,
                paired_evidence="safe",
                commands="safe",
                test_output="safe",
                forbidden_texts=_forbidden_texts(bundle),
            )
        assert marker.read_text(encoding="utf-8") == "keep\n"

    assert marker.read_text(encoding="utf-8") == "keep\n"
    assert not (referent / manifest.run_id).exists()


def test_publish_live_rejects_mocked_output_root_reparse_before_resolve(
    tmp_path: Path,
    writer_v2_inputs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, built, result = writer_v2_inputs
    manifest = _manifest_v2(bundle, built, result)
    root = tmp_path / "runs"
    root.mkdir()
    real_lstat = Path.lstat
    real_resolve = Path.resolve

    def mark_root(path: Path):
        observed = real_lstat(path)
        if path == root:
            return with_reparse_point_attribute(observed)
        return observed

    def reject_root_resolve(path: Path, *args, **kwargs) -> Path:
        if path == root:
            raise AssertionError("output root resolved before redirect rejection")
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", mark_root)
    monkeypatch.setattr(Path, "resolve", reject_root_resolve)

    with pytest.raises(
        ValueError,
        match="output root cannot be a symlink or redirecting reparse point",
    ):
        publish_live_security_run(
            root,
            manifest,
            result,
            paired_evidence="safe",
            commands="safe",
            test_output="safe",
            forbidden_texts=_forbidden_texts(bundle),
        )

    assert not tuple(root.iterdir())


def test_publish_live_rejects_dangling_final_target_symlink_when_supported(
    tmp_path: Path,
    writer_v2_inputs,
) -> None:
    bundle, built, result = writer_v2_inputs
    manifest = _manifest_v2(bundle, built, result)
    root = tmp_path / "runs"
    root.mkdir()
    target = root / manifest.run_id
    referent = root / "missing-live-target"
    try:
        target.symlink_to(referent.name, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    assert target.is_symlink() and not target.exists()

    with pytest.raises(FileExistsError, match="redirecting final component"):
        publish_live_security_run(
            root,
            manifest,
            result,
            paired_evidence="safe",
            commands="safe",
            test_output="safe",
            forbidden_texts=_forbidden_texts(bundle),
        )

    assert target.is_symlink()
    assert not referent.exists()


def test_publish_live_rejects_mocked_redirecting_final_target_without_following_it(
    tmp_path: Path,
    writer_v2_inputs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, built, result = writer_v2_inputs
    manifest = _manifest_v2(bundle, built, result)
    root = tmp_path / "runs"
    root.mkdir()
    target = root / manifest.run_id
    root_stat = root.lstat()
    real_lstat = Path.lstat

    def mark_missing_target(path: Path):
        if path == target:
            return with_reparse_point_attribute(root_stat)
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", mark_missing_target)

    with pytest.raises(FileExistsError, match="redirecting final component"):
        publish_live_security_run(
            root,
            manifest,
            result,
            paired_evidence="safe",
            commands="safe",
            test_output="safe",
            forbidden_texts=_forbidden_texts(bundle),
        )

    assert not target.exists()
    assert not tuple(root.glob(".*.staging-*"))


def test_publish_live_allows_redirected_ancestor_above_declared_root(
    tmp_path: Path,
    writer_v2_inputs,
) -> None:
    bundle, built, result = writer_v2_inputs
    manifest = _manifest_v2(bundle, built, result)
    referent = tmp_path / "ancestor-referent"
    referent.mkdir()
    alias = tmp_path / "ancestor-alias"

    with directory_redirect(alias, referent):
        target = publish_live_security_run(
            alias / "runs",
            manifest,
            result,
            paired_evidence="safe",
            commands="safe",
            test_output="safe",
            forbidden_texts=_forbidden_texts(bundle),
        )
        assert target == (referent / "runs" / manifest.run_id).resolve()
        assert (target / "manifest.json").is_file()

    assert (referent / "runs" / manifest.run_id / "manifest.json").is_file()


def test_publish_live_final_handoff_never_replaces_raced_target(
    tmp_path: Path,
    writer_v2_inputs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, built, result = writer_v2_inputs
    manifest = _manifest_v2(bundle, built, result)
    root = tmp_path / "runs"
    target = root / manifest.run_id
    real_handoff = exposure_writer._atomic_publish_no_replace

    def race(stage: Path, destination: Path) -> None:
        destination.mkdir()
        real_handoff(stage, destination)

    monkeypatch.setattr(
        live_writer,
        "_atomic_publish_no_replace",
        race,
        raising=False,
    )

    with pytest.raises(FileExistsError):
        publish_live_security_run(
            root,
            manifest,
            result,
            paired_evidence="safe",
            commands="safe",
            test_output="safe",
            forbidden_texts=_forbidden_texts(bundle),
        )

    assert target.is_dir() and not tuple(target.iterdir())
    assert not tuple(root.glob(".*.staging-*"))


def test_writer_rejects_raw_model_output_or_secret_like_text(
    tmp_path: Path,
    writer_inputs,
) -> None:
    bundle, built, result = writer_inputs
    manifest = _manifest(bundle, built, result).model_copy(
        update={"run_id": "r2-s1-d7-live-reject-content"}
    )
    raw = bundle.fixture_manifest.cases[0].candidates[0].matched_text

    with pytest.raises(ValueError, match="forbidden content"):
        publish_live_security_run(
            tmp_path / "runs",
            manifest,
            result,
            paired_evidence="safe",
            commands="safe",
            test_output=f"model said: {raw}\napi_key=sk-test-1234567890abcdef",
            forbidden_texts=_forbidden_texts(bundle),
        )


def test_live_manifest_cannot_call_observations_a_release_pass(writer_inputs) -> None:
    bundle, built, result = writer_inputs
    payload = _manifest(bundle, built, result).model_dump(mode="python")
    payload["status"] = "PASSED"

    with pytest.raises(ValidationError):
        LiveSecurityRunManifest.model_validate(payload)


def test_publish_v2_records_manifest_plan_and_actual_per_case_arm_positions(
    tmp_path: Path,
    writer_v2_inputs,
) -> None:
    bundle, built, result = writer_v2_inputs
    manifest = _manifest_v2(bundle, built, result)

    target = publish_live_security_run(
        tmp_path / "runs",
        manifest,
        result,
        paired_evidence="# V5 counterbalanced evidence\n",
        commands="python -m scripts.eval_indirect_injection_live --split test\n",
        test_output="Synthetic model/index preflight passed.\n",
        forbidden_texts=_forbidden_texts(bundle),
    )

    serialized_manifest = json.loads(
        (target / "manifest.json").read_text(encoding="utf-8")
    )
    rows = [
        json.loads(line)
        for line in (target / "per_case.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert serialized_manifest["schema_version"] == (
        "indirect_injection_live_security_run_manifest_v2"
    )
    assert serialized_manifest["mode"] == "local_live_paired_counterbalanced"
    assert serialized_manifest["arm_order"]["case_count"] == 36
    assert serialized_manifest["arm_order"]["off_then_on_count"] == 18
    assert serialized_manifest["arm_order"]["on_then_off_count"] == 18
    assert len(serialized_manifest["arm_order"]["assignments"]) == 36
    assert len(rows) == 72

    for pair_index, assignment in enumerate(result.arm_order.assignments):
        pair = rows[pair_index * 2 : pair_index * 2 + 2]
        assert [row["live"]["case_id"] for row in pair] == [
            assignment.case_id,
            assignment.case_id,
        ]
        assert [row["live"]["guard_mode"] for row in pair] == list(
            assignment.modes()
        )
        assert [row["arm_execution"]["arm_position"] for row in pair] == [1, 2]
        for row in pair:
            assert set(row) == {"arm_execution", "security", "live"}
            assert row["security"]["guard_mode"] == row["live"]["guard_mode"]
            assert row["arm_execution"] == {
                "protocol_id": result.arm_order.protocol_id,
                "case_hash": assignment.case_hash,
                "hash_rank": assignment.hash_rank,
                "arm_order": assignment.arm_order,
                "execution_index": row["arm_execution"]["execution_index"],
                "arm_position": row["arm_execution"]["arm_position"],
            }
            event = next(
                event
                for event in result.arm_execution
                if event.case_id == assignment.case_id
                and event.guard_mode == row["live"]["guard_mode"]
            )
            assert row["arm_execution"]["execution_index"] == (
                event.execution_index
            )


def test_v2_failures_distinguish_unreached_units_from_guard_misses(
    tmp_path: Path,
    writer_v2_inputs,
) -> None:
    bundle, built, result = writer_v2_inputs
    manifest = _manifest_v2(bundle, built, result)

    target = publish_live_security_run(
        tmp_path / "runs",
        manifest,
        result,
        paired_evidence="safe",
        commands="safe",
        test_output="safe",
        forbidden_texts=_forbidden_texts(bundle),
    )

    failures = (target / "failures.csv").read_text(encoding="utf-8")
    assert "attack_unit_unreached" in failures
    assert "attack_unit_admitted" not in failures
    assert "attack_unit_missed_by_guard" not in failures


def test_v2_failure_translation_records_attack_unit_missed_by_guard(
    writer_v2_inputs,
) -> None:
    _, _, result = writer_v2_inputs
    security = next(
        item
        for item in result.security.guard_on.cases
        if "attack_unit_admitted" in item.failure_codes
    )
    observation = next(
        item for item in result.guard_on if item.case_id == security.case_id
    ).model_copy(
        update={
            "attack_unit_count": 1,
            "attack_unit_reached_guard_count": 1,
            "attack_unit_quarantined_count": 0,
        }
    )

    failures = live_writer._v2_case_failure_codes(security, observation)

    assert "attack_unit_missed_by_guard" in failures
    assert "attack_unit_unreached" not in failures
    assert "attack_unit_admitted" not in failures


def test_v2_per_case_validator_rejects_tampered_arm_position(
    tmp_path: Path,
    writer_v2_inputs,
) -> None:
    bundle, built, result = writer_v2_inputs
    manifest = _manifest_v2(bundle, built, result)
    target = publish_live_security_run(
        tmp_path / "runs",
        manifest,
        result,
        paired_evidence="safe",
        commands="safe",
        test_output="safe",
        forbidden_texts=_forbidden_texts(bundle),
    )
    rows_path = target / "per_case.jsonl"
    rows = rows_path.read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    first["arm_execution"]["arm_position"] = 2
    rows[0] = json.dumps(first, ensure_ascii=False, sort_keys=True)
    tampered = tmp_path / "tampered.jsonl"
    tampered.write_text("\n".join(rows) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="arm position"):
        live_writer._validate_v2_per_case_rows(tampered, manifest)


def test_v2_stage_rejects_self_consistent_hashes_with_contradictory_summary(
    tmp_path: Path,
    writer_v2_inputs,
) -> None:
    bundle, built, result = writer_v2_inputs
    manifest = _manifest_v2(bundle, built, result)
    target = publish_live_security_run(
        tmp_path / "runs",
        manifest,
        result,
        paired_evidence="safe",
        commands="safe",
        test_output="safe",
        forbidden_texts=_forbidden_texts(bundle),
    )
    summary_path = target / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["guard_off_live"]["case_count"] += 1
    summary_path.write_bytes(live_writer._json_bytes(summary))

    checksum_payload = "".join(
        f"{live_writer._sha256(target / name)}  {name}\n"
        for name in live_writer._CHECKSUM_CONTENT_NAMES
    ).encode("utf-8")
    (target / "checksums.sha256").write_bytes(checksum_payload)

    published_manifest = live_writer.LiveSecurityRunManifestV2.model_validate_json(
        (target / "manifest.json").read_bytes()
    )
    manifest_payload = published_manifest.model_dump(mode="python")
    manifest_payload["artifacts"] = {
        name: {
            "path": name,
            "bytes": (target / name).stat().st_size,
            "sha256": live_writer._sha256(target / name),
        }
        for name in sorted(live_writer._ARTIFACT_NAMES)
    }
    tampered_manifest = live_writer.LiveSecurityRunManifestV2.model_validate(
        manifest_payload
    )
    (target / "manifest.json").write_bytes(
        live_writer._json_bytes(tampered_manifest.model_dump(mode="json"))
    )

    with pytest.raises(ValueError, match="summary"):
        live_writer._validate_stage(target, tampered_manifest)


def test_verify_live_security_run_reloads_and_recomputes_v2_artifact(
    tmp_path: Path,
    writer_v2_inputs,
) -> None:
    bundle, built, result = writer_v2_inputs
    manifest = _manifest_v2(bundle, built, result)
    target = publish_live_security_run(
        tmp_path / "runs",
        manifest,
        result,
        paired_evidence="safe",
        commands="safe",
        test_output="safe",
        forbidden_texts=_forbidden_texts(bundle),
    )

    verified = live_writer.verify_live_security_run(target)

    assert isinstance(verified, live_writer.LiveSecurityRunManifestV2)
    assert verified.run_id == manifest.run_id
    assert verified.arm_order == manifest.arm_order
    assert set(verified.artifacts) == live_writer._ARTIFACT_NAMES


def test_live_run_verifier_reports_counterbalanced_position_strata(
    tmp_path: Path,
    writer_v2_inputs,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.verify_indirect_injection_live_run import main as verify_main

    bundle, built, result = writer_v2_inputs
    manifest = _manifest_v2(bundle, built, result)
    target = publish_live_security_run(
        tmp_path / "runs",
        manifest,
        result,
        paired_evidence="safe",
        commands="safe",
        test_output="safe",
        forbidden_texts=_forbidden_texts(bundle),
    )

    assert verify_main([str(target)]) == 0
    report = json.loads(capsys.readouterr().out)

    assert set(report["arm_position_strata"]) == {"1", "2"}
    for position in ("1", "2"):
        assert report["arm_position_strata"][position]["off"]["case_count"] == 18
        assert report["arm_position_strata"][position]["on"]["case_count"] == 18


def test_live_run_verifier_cli_rejects_real_windows_run_junction(
    tmp_path: Path,
    writer_v2_inputs,
) -> None:
    from scripts.verify_indirect_injection_live_run import main as verify_main

    bundle, built, result = writer_v2_inputs
    manifest = _manifest_v2(bundle, built, result)
    target = publish_live_security_run(
        tmp_path / "runs",
        manifest,
        result,
        paired_evidence="safe",
        commands="safe",
        test_output="safe",
        forbidden_texts=_forbidden_texts(bundle),
    )
    alias = tmp_path / "live-run-junction"

    with directory_redirect(
        alias,
        target,
        windows_junction_only=True,
    ) as primitive:
        assert primitive == "junction"
        with pytest.raises(
            ValueError,
            match="live security run directory cannot be a symlink or redirecting reparse point",
        ):
            verify_main([str(alias)])

    assert target.is_dir()
    assert (target / "manifest.json").is_file()


def test_writer_rejects_v1_manifest_with_v2_result(
    tmp_path: Path,
    writer_v2_inputs,
) -> None:
    bundle, built, result = writer_v2_inputs
    v1_manifest = _manifest(bundle, built, result).model_copy(
        update={"run_id": "r2-s1-v5-version-mismatch"}
    )

    with pytest.raises(ValueError, match="manifest/result schema versions"):
        publish_live_security_run(
            tmp_path / "runs",
            v1_manifest,
            result,
            paired_evidence="safe",
            commands="safe",
            test_output="safe",
            forbidden_texts=_forbidden_texts(bundle),
        )
