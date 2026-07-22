from __future__ import annotations

import contextlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.evaluation import indirect_injection_live_writer as live_writer
from app.evaluation.indirect_injection_cross_model import load_cross_model_plan
from app.evaluation.indirect_injection_dataset import build_v1_bundle
from app.evaluation.indirect_injection_live_writer import (
    LiveIndexReference,
    OllamaModelIdentity,
    resolve_ollama_model_identity,
)
from app.evaluation.indirect_injection_writer import (
    R1_FROZEN_EXPECTED_HASHES,
    R1HashPair,
)
from scripts import eval_indirect_injection_live
from tests.evaluation.test_indirect_injection_live_runner import (
    FREEZE_HEAD,
    FROZEN_AT,
    _StructuredFixtureChat,
    _embedding,
)


PLAN_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "v2"
    / "evaluation"
    / "r2_s4_cross_model_matrix_v1.json"
)
PLAN, PLAN_SHA256 = load_cross_model_plan(PLAN_PATH)


def _bundle_root(tmp_path: Path) -> Path:
    root = tmp_path / "security-data"
    build_v1_bundle(
        root,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    return root


def _identity(name: str, digest: str, capability: str) -> OllamaModelIdentity:
    return OllamaModelIdentity(
        requested_name=name,
        resolved_name=name if ":" in name else name + ":latest",
        digest=digest,
        size_bytes=100,
        format="gguf",
        family="bert" if capability == "embedding" else "qwen2",
        parameter_size="567M" if capability == "embedding" else "3.1B",
        quantization_level="F16" if capability == "embedding" else "Q4_K_M",
        context_length=8_192 if capability == "embedding" else 32_768,
        embedding_length=1_024 if capability == "embedding" else 2_048,
        capabilities=(capability,),
    )


def _cross_model_binding(
    *,
    role: str = "replication",
    plan_sha256: str = PLAN_SHA256,
) -> live_writer.CrossModelExperimentBinding:
    return live_writer.CrossModelExperimentBinding(
        plan_id="r2-s4-cross-model-dev-v1",
        plan_sha256=plan_sha256,
        model_role=role,
        only_changed_variable="chat_model_identity",
    )


def _planned_runtime() -> eval_indirect_injection_live.OllamaRuntimeSnapshot:
    model = PLAN.model_for_role("replication")
    embedding = _identity(
        PLAN.embedding.requested_name,
        PLAN.embedding.digest,
        "embedding",
    ).model_copy(update={"resolved_name": PLAN.embedding.resolved_name})
    chat = _identity(
        model.requested_name,
        model.digest,
        "completion",
    ).model_copy(
        update={
            "resolved_name": model.resolved_name,
            "family": model.family,
            "parameter_size": model.parameter_size,
        }
    )
    return eval_indirect_injection_live.OllamaRuntimeSnapshot(
        version="0.32.1",
        embedding=embedding,
        chat=chat,
    )


def test_parser_has_no_force_guard_or_model_override_switches() -> None:
    parser = eval_indirect_injection_live.build_parser()
    options = {
        option
        for action in parser._actions
        for option in action.option_strings
    }

    assert "--force" not in options
    assert "--guard-off" not in options
    assert "--chat-model" not in options
    assert "--embedding-model" not in options
    assert "--arm-order-protocol" not in options
    assert {"--split", "--run-id", "--data-root", "--out-dir", "--index-root"}.issubset(options)


def test_direct_live_execute_acquires_shared_endpoint_lock_before_model_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    @contextlib.contextmanager
    def recording_lock(origin: str):
        events.append(f"lock-enter:{origin}")
        try:
            yield
        finally:
            events.append("lock-exit")

    monkeypatch.setattr(
        eval_indirect_injection_live,
        "evaluation_lock",
        recording_lock,
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "get_settings",
        lambda: SimpleNamespace(
            llm_base_url="http://localhost:11434/v1",
            chat_model="qwen2.5:3b",
            embedding_model="bge-m3",
            structured_generation_max_attempts=2,
            model_request_timeout_seconds=12.0,
            model_max_attempts=2,
            model_retry_backoff_ms=100,
            v2_indexes_dir=tmp_path / "production-index",
        ),
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "verify_r1_frozen_hashes",
        lambda _root: {},
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "_git_provenance",
        lambda _root: {"head": "a" * 40},
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "_installed_dependency_snapshot",
        lambda: {
            "installed_snapshot_sha256": "b" * 64,
            "installed_package_count": 1,
        },
    )

    def stop_at_first_evaluator_side_effect(_root: Path):
        events.append("production-index")
        raise RuntimeError("stop after direct live lock")

    monkeypatch.setattr(
        eval_indirect_injection_live,
        "production_active_index_reference",
        stop_at_first_evaluator_side_effect,
    )
    for name in (
        "fetch_ollama_runtime",
        "run_model_smoke",
        "build_live_fixture_index",
        "evaluate_live_paired",
    ):
        monkeypatch.setattr(
            eval_indirect_injection_live,
            name,
            lambda *args, _name=name, **kwargs: (_ for _ in ()).throw(
                AssertionError(f"{_name} ran before ordering stop")
            ),
        )
    args = eval_indirect_injection_live.build_parser().parse_args(
        [
            "--split",
            "dev",
            "--run-id",
            "d7-lock-ordering-probe",
            "--data-root",
            str(_bundle_root(tmp_path)),
            "--out-dir",
            str(tmp_path / "runs"),
            "--index-root",
            str(tmp_path / "indexes"),
        ]
    )
    request = eval_indirect_injection_live.LiveExecutionRequest(
        args=args,
        chat_model="qwen2.5:3b",
        expected_chat_digest=eval_indirect_injection_live.FROZEN_QWEN25_CHAT_DIGEST,
        canonical_argv=("python", "-m", "scripts.eval_indirect_injection_live"),
    )

    with pytest.raises(RuntimeError, match="stop after direct live lock"):
        eval_indirect_injection_live.execute_live_security_run(request)

    assert events == [
        "lock-enter:http://localhost:11434/v1",
        "production-index",
        "lock-exit",
    ]


def test_cross_model_request_rejects_test_before_settings_or_external_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = eval_indirect_injection_live.build_parser().parse_args(
        [
            "--split",
            "test",
            "--run-id",
            "r2-s4-cross-model-test-probe",
            "--data-root",
            str(tmp_path / "unused-data"),
            "--out-dir",
            str(tmp_path / "unused-runs"),
            "--index-root",
            str(tmp_path / "unused-indexes"),
        ]
    )
    called: list[str] = []
    for name in (
        "get_settings",
        "fetch_ollama_runtime",
        "run_model_smoke",
        "build_live_fixture_index",
        "evaluate_live_paired",
    ):
        monkeypatch.setattr(
            eval_indirect_injection_live,
            name,
            lambda *args, _name=name, **kwargs: called.append(_name),
        )

    request = eval_indirect_injection_live.LiveExecutionRequest(
        args=args,
        chat_model="qwen3:8b",
        expected_chat_digest="8" * 64,
        experiment=live_writer.CrossModelExperimentBinding(
            plan_id="r2-s4-cross-model-dev-v1",
            plan_sha256="a" * 64,
            model_role="replication",
            only_changed_variable="chat_model_identity",
        ),
    )

    with pytest.raises(ValueError, match="dev"):
        eval_indirect_injection_live.execute_live_security_run(request)

    assert called == []


@pytest.mark.parametrize(
    ("identity_name", "field", "value"),
    (
        ("chat", "requested_name", "qwen3-alternate:8b"),
        ("chat", "resolved_name", "qwen3:8b-alternate"),
        ("chat", "digest", "c" * 64),
        ("chat", "family", "qwen2"),
        ("chat", "parameter_size", "8.1B"),
        ("embedding", "requested_name", "bge-m3-alternate"),
        ("embedding", "resolved_name", "bge-m3:alternate"),
        ("embedding", "digest", "d" * 64),
    ),
)
def test_cross_model_runtime_identity_mismatch_aborts_before_index_or_model_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    identity_name: str,
    field: str,
    value: str,
) -> None:
    data_root = _bundle_root(tmp_path)
    args = eval_indirect_injection_live.build_parser().parse_args(
        [
            "--split",
            "dev",
            "--run-id",
            "r2-s4-cross-model-digest-probe",
            "--data-root",
            str(data_root),
            "--out-dir",
            str(tmp_path / "runs"),
            "--index-root",
            str(tmp_path / "indexes"),
        ]
    )
    called: list[str] = []
    settings = SimpleNamespace(
        llm_base_url="http://127.0.0.1:11434/v1",
        chat_model="qwen2.5:3b",
        embedding_model="bge-m3",
        structured_generation_max_attempts=2,
        model_request_timeout_seconds=12.0,
        model_max_attempts=2,
        model_retry_backoff_ms=100,
        v2_indexes_dir=tmp_path / "production-index",
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "verify_r1_frozen_hashes",
        lambda _root: {},
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "_git_provenance",
        lambda _root: {
            "head": "a" * 40,
            "branch": "codex/rag-eval-system",
            "dirty": False,
            "status_entry_count": 0,
            "dirty_state_sha256": "b" * 64,
        },
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "_installed_dependency_snapshot",
        lambda: {
            "installed_snapshot_sha256": "c" * 64,
            "installed_package_count": 50,
        },
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "production_active_index_reference",
        lambda _root: called.append("production-index"),
    )
    runtime = _planned_runtime()
    runtime = eval_indirect_injection_live.OllamaRuntimeSnapshot(
        version=runtime.version,
        embedding=(
            runtime.embedding.model_copy(update={field: value})
            if identity_name == "embedding"
            else runtime.embedding
        ),
        chat=(
            runtime.chat.model_copy(update={field: value})
            if identity_name == "chat"
            else runtime.chat
        ),
    )

    def fetch_runtime(*_args, **_kwargs):
        called.append("runtime")
        return runtime

    monkeypatch.setattr(
        eval_indirect_injection_live,
        "fetch_ollama_runtime",
        fetch_runtime,
    )
    for name in (
        "run_model_smoke",
        "build_live_fixture_index",
        "evaluate_live_paired",
    ):
        monkeypatch.setattr(
            eval_indirect_injection_live,
            name,
            lambda *args, _name=name, **kwargs: (_ for _ in ()).throw(
                AssertionError(f"{_name} ran before identity admission")
            ),
        )
    model = PLAN.model_for_role("replication")
    request = eval_indirect_injection_live.LiveExecutionRequest(
        args=args,
        chat_model=model.requested_name,
        expected_chat_digest=model.digest,
        experiment=_cross_model_binding(),
    )

    with pytest.raises(ValueError, match="checked-in cross-model plan"):
        eval_indirect_injection_live.execute_live_security_run(request)

    assert called == ["runtime"]


@pytest.mark.parametrize(
    ("chat_model", "expected_digest", "binding"),
    (
        (
            PLAN.model_for_role("replication").requested_name,
            PLAN.model_for_role("replication").digest,
            _cross_model_binding(plan_sha256="b" * 64),
        ),
        (
            PLAN.model_for_role("replication").requested_name,
            PLAN.model_for_role("replication").digest,
            _cross_model_binding(role="baseline"),
        ),
        (
            PLAN.model_for_role("replication").requested_name,
            "c" * 64,
            _cross_model_binding(),
        ),
        (
            PLAN.model_for_role("baseline").requested_name,
            PLAN.model_for_role("replication").digest,
            _cross_model_binding(),
        ),
    ),
)
def test_cross_model_request_rejects_valid_plan_contradictions_before_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chat_model: str,
    expected_digest: str,
    binding: live_writer.CrossModelExperimentBinding,
) -> None:
    data_root = _bundle_root(tmp_path)
    args = eval_indirect_injection_live.build_parser().parse_args(
        [
            "--split",
            "dev",
            "--run-id",
            "r2-s4-cross-model-request-contradiction",
            "--data-root",
            str(data_root),
            "--out-dir",
            str(tmp_path / "runs"),
            "--index-root",
            str(tmp_path / "indexes"),
        ]
    )
    called: list[str] = []
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "get_settings",
        lambda: called.append("settings"),
    )
    request = eval_indirect_injection_live.LiveExecutionRequest(
        args=args,
        chat_model=chat_model,
        expected_chat_digest=expected_digest,
        experiment=binding,
    )

    with pytest.raises(ValueError, match="checked-in cross-model plan"):
        eval_indirect_injection_live.execute_live_security_run(request)

    assert called == []


def test_ollama_tag_resolution_records_exact_digest_and_capability() -> None:
    payload = {
        "models": [
            {
                "name": "bge-m3:latest",
                "model": "bge-m3:latest",
                "size": 1_157_672_605,
                "digest": "7" * 64,
                "details": {
                    "format": "gguf",
                    "family": "bert",
                    "parameter_size": "566.70M",
                    "quantization_level": "F16",
                    "context_length": 8_192,
                    "embedding_length": 1_024,
                },
                "capabilities": ["embedding"],
            }
        ]
    }

    identity = resolve_ollama_model_identity(payload, "bge-m3")

    assert identity.requested_name == "bge-m3"
    assert identity.resolved_name == "bge-m3:latest"
    assert identity.digest == "7" * 64
    assert identity.embedding_length == 1_024
    assert identity.capabilities == ("embedding",)


def test_frozen_test_mismatch_aborts_before_any_model_or_index_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = _bundle_root(tmp_path)
    (data_root / "indirect_injection_test_v1.json").write_text(
        "{}",
        encoding="utf-8",
    )
    called: list[str] = []

    monkeypatch.setattr(
        eval_indirect_injection_live,
        "verify_r1_frozen_hashes",
        lambda _root: {},
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "fetch_ollama_runtime",
        lambda *args, **kwargs: called.append("model"),
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "build_live_fixture_index",
        lambda *args, **kwargs: called.append("index"),
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "evaluate_live_paired",
        lambda *args, **kwargs: called.append("evaluate"),
    )

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        eval_indirect_injection_live.main(
            [
                "--split",
                "test",
                "--run-id",
                "d7-tampered-test",
                "--data-root",
                str(data_root),
                "--out-dir",
                str(tmp_path / "runs"),
                "--index-root",
                str(tmp_path / "indexes"),
            ]
        )

    assert called == []


def test_self_consistent_alternative_test_bundle_is_not_the_frozen_cohort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = _bundle_root(tmp_path)
    dataset_path = data_root / "indirect_injection_test_v1.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    dataset["cases"][0]["question"] += " altered"
    dataset_path.write_text(
        json.dumps(dataset, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    freeze_path = data_root / "indirect_injection_test_v1.manifest.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    freeze["dataset_sha256"] = eval_indirect_injection_live._sha256(dataset_path)
    freeze["dataset_bytes"] = dataset_path.stat().st_size
    freeze_path.write_text(
        json.dumps(freeze, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    called: list[str] = []
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "verify_r1_frozen_hashes",
        lambda _root: {},
    )

    def unexpected_settings_call():
        called.append("settings")
        raise AssertionError("alternative test data reached runtime setup")

    monkeypatch.setattr(
        eval_indirect_injection_live,
        "get_settings",
        unexpected_settings_call,
    )

    with pytest.raises(ValueError, match="official frozen test cohort"):
        eval_indirect_injection_live.main(
            [
                "--split",
                "test",
                "--run-id",
                "r2-s1-v5-alternative-test",
                "--data-root",
                str(data_root),
                "--out-dir",
                str(tmp_path / "runs"),
                "--index-root",
                str(tmp_path / "indexes"),
            ]
        )

    assert called == []


@pytest.mark.parametrize("option", ["--out-dir", "--index-root"])
def test_future_run_cannot_write_inside_the_frozen_formal_run_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    option: str,
) -> None:
    frozen = (
        eval_indirect_injection_live.DEFAULT_OUT_DIR
        / eval_indirect_injection_live.FROZEN_FORMAL_D7_RUN_ID
    )
    called: list[str] = []
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "verify_r1_frozen_hashes",
        lambda _root: called.append("frozen-check"),
    )
    argv = [
        "--split",
        "dev",
        "--run-id",
        "r2-s1-v5-frozen-directory-probe",
        "--data-root",
        str(tmp_path / "unused-data"),
        "--out-dir",
        str(tmp_path / "safe-runs"),
        "--index-root",
        str(tmp_path / "safe-indexes"),
    ]
    argv[argv.index(option) + 1] = str(frozen)

    with pytest.raises(ValueError, match="frozen formal D7 directory"):
        eval_indirect_injection_live.main(argv)

    assert called == []


def test_completed_live_observation_publishes_and_returns_zero_even_with_attacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = _bundle_root(tmp_path)
    embedding_identity = _identity("bge-m3", "7" * 64, "embedding")
    chat_identity = _identity(
        "qwen2.5:3b",
        eval_indirect_injection_live.FROZEN_QWEN25_CHAT_DIGEST,
        "completion",
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "get_settings",
        lambda: SimpleNamespace(
            llm_base_url="http://127.0.0.1:11434/v1",
            chat_model="qwen2.5:3b",
            embedding_model="bge-m3",
            structured_generation_max_attempts=2,
            model_request_timeout_seconds=12.0,
            model_max_attempts=2,
            model_retry_backoff_ms=100,
            v2_indexes_dir=tmp_path / "production-index",
        ),
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "verify_r1_frozen_hashes",
        lambda _root: {
            path: R1HashPair(expected=digest, actual=digest)
            for path, digest in R1_FROZEN_EXPECTED_HASHES.items()
        },
    )
    git = {
        "head": "a" * 40,
        "branch": "codex/rag-eval-system",
        "dirty": False,
        "status_entry_count": 0,
        "dirty_state_sha256": "b" * 64,
    }
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "_git_provenance",
        lambda _root: dict(git),
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "_installed_dependency_snapshot",
        lambda: {
            "installed_snapshot_command": (
                "python",
                "-m",
                "pip",
                "freeze",
                "--all",
            ),
            "installed_snapshot_sha256": "c" * 64,
            "installed_package_count": 50,
        },
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "production_active_index_reference",
        lambda _root: LiveIndexReference(
            role="production_active_reference",
            run_id="production-index",
            active_pointer_sha256="1" * 64,
            manifest_sha256="2" * 64,
            corpus_sha256="3" * 64,
            embedding_model="bge-m3",
            embedding_dimension=1_024,
            indexed_chunk_count=100,
        ),
    )

    runtime_calls: list[str] = []

    def stable_runtime(*_args, **_kwargs):
        runtime_calls.append("runtime")
        return eval_indirect_injection_live.OllamaRuntimeSnapshot(
            version="0.32.1",
            embedding=embedding_identity,
            chat=chat_identity,
        )

    monkeypatch.setattr(
        eval_indirect_injection_live,
        "fetch_ollama_runtime",
        stable_runtime,
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "run_model_smoke",
        lambda *args, **kwargs: eval_indirect_injection_live.ModelSmokeEvidence(
            embedding_dimension=1_024,
            structured_chat_valid=True,
            allowed_http_request_count=2,
            blocked_egress_attempt_count=0,
        ),
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "_embed_text",
        lambda _model, text: _embedding(text),
    )
    chat = _StructuredFixtureChat()
    monkeypatch.setattr(eval_indirect_injection_live, "chat_with_ollama", chat)
    out = tmp_path / "runs"

    exit_code = eval_indirect_injection_live.main(
        [
            "--split",
            "test",
            "--run-id",
            "d7-completed-observation",
            "--data-root",
            str(data_root),
            "--out-dir",
            str(out),
            "--index-root",
            str(tmp_path / "indexes"),
        ]
    )

    assert exit_code == 0
    assert runtime_calls == ["runtime", "runtime"]
    run = out / "d7-completed-observation"
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (run / "per_case.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert manifest["status"] == "COMPLETED WITH OBSERVATIONS"
    assert manifest["schema_version"] == (
        "indirect_injection_live_security_run_manifest_v2"
    )
    assert manifest["mode"] == "local_live_paired_counterbalanced"
    assert manifest["arm_order"]["protocol_id"] == (
        "stable_case_hash_rank_counterbalanced_v1"
    )
    assert manifest["arm_order"]["case_count"] == 36
    assert manifest["arm_order"]["off_then_on_count"] == 18
    assert manifest["arm_order"]["on_then_off_count"] == 18
    assert len(manifest["arm_order"]["assignments"]) == 36
    assert summary["schema_version"] == "indirect_injection_live_paired_result_v2"
    assert summary["arm_order"]["off_then_on_count"] == 18
    assert len(rows) == 72
    assert all(set(row) == {"arm_execution", "security", "live"} for row in rows)
    assert manifest["models"]["embedding"]["digest"] == "7" * 64
    assert manifest["models"]["chat"]["digest"] == (
        eval_indirect_injection_live.FROZEN_QWEN25_CHAT_DIGEST
    )
    assert summary["guard_off_live"]["model_attack_followed"]["numerator"] >= 1
    evidence = (run / "red_green_evidence.md").read_text(encoding="utf-8")
    assert "raw canary or forbidden-action follow" in evidence
    assert "raw_canary_or_forbidden_action_follow_v1" in evidence
    assert "semantic attack following is NOT MEASURED" in evidence
    assert "stable_case_hash_rank_counterbalanced_v1" in evidence
    assert "raw model attack-follow observation" not in evidence
    assert manifest["observation"]["deterministic_threshold_diagnostic_passed"] in {
        True,
        False,
    }


def test_live_runtime_identity_drift_is_rejected() -> None:
    initial = _planned_runtime()
    changed = eval_indirect_injection_live.OllamaRuntimeSnapshot(
        version=initial.version,
        embedding=initial.embedding,
        chat=initial.chat.model_copy(update={"digest": "f" * 64}),
    )

    with pytest.raises(ValueError, match="changed during live evaluation"):
        eval_indirect_injection_live._assert_ollama_runtime_stable(
            initial,
            changed,
        )


def test_frozen_formal_d7_run_id_is_rejected_before_any_external_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "verify_r1_frozen_hashes",
        lambda _root: called.append("frozen-data"),
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "fetch_ollama_runtime",
        lambda *args, **kwargs: called.append("model"),
    )
    monkeypatch.setattr(
        eval_indirect_injection_live,
        "build_live_fixture_index",
        lambda *args, **kwargs: called.append("index"),
    )

    with pytest.raises(ValueError, match="frozen formal D7 run ID"):
        eval_indirect_injection_live.main(
            [
                "--split",
                "test",
                "--run-id",
                "r2-s1-d7-test-20260718-01",
                "--data-root",
                str(tmp_path / "missing-data"),
                "--out-dir",
                str(tmp_path / "different-output-root"),
                "--index-root",
                str(tmp_path / "different-index-root"),
            ]
        )

    assert called == []
