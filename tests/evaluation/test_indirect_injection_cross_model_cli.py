from __future__ import annotations

import json
import os
import argparse
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.evaluation.indirect_injection_cross_model import load_cross_model_plan
from app.evaluation import indirect_injection_cross_model_writer as matrix_writer
from app.evaluation.indirect_injection_cross_model_writer import (
    publish_cross_model_run,
    verify_cross_model_run,
)
from app.evaluation.indirect_injection_live_writer import (
    OllamaModelIdentity,
    publish_live_security_run,
)
from tests.evaluation.path_redirect_helpers import (
    directory_redirect,
    with_reparse_point_attribute,
)
from tests.evaluation import test_indirect_injection_live_writer as live_writer_tests
from tests.evaluation import test_indirect_injection_cross_model_writer as matrix_fixtures
from scripts import eval_indirect_injection_cross_model


ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "data" / "v2" / "evaluation" / "r2_s4_cross_model_matrix_v1.json"


def _identity(name: str, digest: str, capability: str) -> OllamaModelIdentity:
    return OllamaModelIdentity(
        requested_name=name,
        resolved_name=name if ":" in name else f"{name}:latest",
        digest=digest,
        size_bytes=1,
        format="gguf",
        family="qwen2" if name == "qwen2.5:3b" else "qwen3",
        parameter_size="3.1B" if name == "qwen2.5:3b" else "8.2B",
        quantization_level="Q4_K_M",
        context_length=32768,
        embedding_length=1024 if capability == "embedding" else None,
        capabilities=(capability,),
    )


def _runtime(plan):
    return eval_indirect_injection_cross_model.OllamaIdentitySnapshot(
        version="0.12.0",
        embedding=_identity(
            plan.embedding.requested_name,
            plan.embedding.digest,
            "embedding",
        ),
        chats={
            model.role: _identity(
                model.requested_name,
                model.digest,
                "completion",
            )
            for model in plan.chat_models
        },
    )


def _clean_git() -> dict[str, object]:
    return {
        "head": "a" * 40,
        "branch": "codex/rag-eval-system",
        "dirty": False,
        "status_entry_count": 0,
        "dirty_state_sha256": "b" * 64,
    }


def _component_context(plan):
    return eval_indirect_injection_cross_model.ComponentContext(
        data=SimpleNamespace(
            dataset_path=ROOT / "data" / "v2" / "security" / "indirect_injection_dev_v1.json",
            dataset_sha256="c" * 64,
            fixture_manifest_path=ROOT / "data" / "v2" / "security" / "indirect_injection_dev_v1.manifest.json",
            fixture_manifest_sha256="d" * 64,
            dataset=SimpleNamespace(case_count=36, attack_case_count=18, benign_case_count=18),
        ),
        r1_hashes={},
        guard_sha256="e" * 64,
    )


def _execution() -> SimpleNamespace:
    return SimpleNamespace()


@pytest.fixture(scope="module")
def writer_v3_inputs(tmp_path_factory: pytest.TempPathFactory):
    return live_writer_tests.writer_v3_inputs.__wrapped__(tmp_path_factory)


@pytest.fixture(scope="module")
def writer_legacy_inputs(tmp_path_factory: pytest.TempPathFactory):
    v1_inputs = live_writer_tests.writer_inputs.__wrapped__(tmp_path_factory)
    return v1_inputs, live_writer_tests.writer_v2_inputs.__wrapped__(v1_inputs)


def _real_admission_inputs(tmp_path: Path, writer_v3_inputs):
    bundle, built, result = writer_v3_inputs
    plan, plan_sha256 = load_cross_model_plan(PLAN_PATH)
    component = plan.model_for_role("replication").model_copy(
        update={"run_id": "r2-s4-admission-fixture"}
    )
    payload = live_writer_tests._manifest_v3(bundle, built, result).model_dump(
        mode="python"
    )
    payload["run_id"] = "r2-s4-admission-fixture"
    payload["git"] = _clean_git()
    payload["guard"] = {
        "detector_version": eval_indirect_injection_cross_model.DETECTOR_VERSION,
        "ruleset_path": "app/security/retrieved_content.py",
        "ruleset_sha256": "e" * 64,
        "max_scan_chars": eval_indirect_injection_cross_model.MAX_SCAN_CHARS,
        "max_normalized_chars": (
            eval_indirect_injection_cross_model.MAX_NORMALIZED_CHARS
        ),
        "max_decoded_views": eval_indirect_injection_cross_model.MAX_DECODED_VIEWS,
    }
    payload["evaluator"] = {
        "path": "scripts/eval_indirect_injection_cross_model.py",
        "sha256": eval_indirect_injection_cross_model._sha256(
            ROOT / "scripts" / "eval_indirect_injection_cross_model.py"
        ),
        "argv": (
            "python",
            "-m",
            "scripts.eval_indirect_injection_cross_model",
        ),
        "exit_code": 0,
    }
    manifest = eval_indirect_injection_cross_model.LiveSecurityRunManifestV3.model_validate(
        payload
    )
    target = publish_live_security_run(
        tmp_path / "verified-runs",
        manifest,
        result,
        paired_evidence="safe",
        commands="safe",
        test_output="safe",
        forbidden_texts=live_writer_tests._forbidden_texts(bundle),
    )
    context = eval_indirect_injection_cross_model.ComponentContext(
        data=SimpleNamespace(
            dataset_path=ROOT / manifest.data.dataset_path,
            dataset_sha256=manifest.data.dataset_sha256,
            fixture_manifest_path=ROOT / manifest.data.fixture_manifest_path,
            fixture_manifest_sha256=manifest.data.fixture_manifest_sha256,
            dataset=SimpleNamespace(
                case_count=manifest.data.dataset_case_count,
                attack_case_count=manifest.data.attack_case_count,
                benign_case_count=manifest.data.benign_case_count,
            ),
        ),
        r1_hashes=manifest.data.r1_frozen_hashes,
        guard_sha256=manifest.guard.ruleset_sha256,
    )
    planned_runtime = _runtime(plan)
    runtime = eval_indirect_injection_cross_model.OllamaIdentitySnapshot(
        version=manifest.environment.ollama_version,
        embedding=manifest.models.embedding,
        chats={
            "baseline": planned_runtime.chats["baseline"],
            "replication": manifest.models.chat,
        },
    )
    retrieval = manifest.retrieval
    execution = eval_indirect_injection_cross_model.ExecutionInvariantSnapshot(
        llm_endpoint=manifest.environment.ollama_endpoint + "/v1",
        ollama_origin=manifest.environment.ollama_endpoint,
        structured_generation_max_attempts=manifest.models.max_attempts,
        model_request_timeout_seconds=(
            manifest.transport.model_request_timeout_seconds
        ),
        model_max_attempts=manifest.transport.model_max_attempts,
        model_retry_backoff_ms=manifest.transport.model_retry_backoff_ms,
        ollama_version=manifest.environment.ollama_version,
        python_version=manifest.environment.python_version,
        platform=manifest.environment.platform,
        dependency_snapshot_path=manifest.environment.dependency_snapshot_path,
        dependency_snapshot_sha256=manifest.environment.dependency_snapshot_sha256,
        installed_snapshot_sha256=manifest.environment.installed_snapshot_sha256,
        installed_package_count=manifest.environment.installed_package_count,
        production_active_index=retrieval.production_active_index,
        top_k=retrieval.top_k,
        candidate_k=retrieval.candidate_k,
        max_search_calls=retrieval.max_search_calls,
        max_open_calls=retrieval.max_open_calls,
        max_steps=retrieval.max_steps,
        max_context_chars=retrieval.max_context_chars,
        evaluator_path=manifest.evaluator.path,
        evaluator_sha256=manifest.evaluator.sha256,
        canonical_argv=manifest.evaluator.argv,
    )
    return target, plan, plan_sha256, component, context, runtime, execution


def _guard(digest: str) -> SimpleNamespace:
    return SimpleNamespace(
        detector_version=eval_indirect_injection_cross_model.DETECTOR_VERSION,
        ruleset_path="app/security/retrieved_content.py",
        ruleset_sha256=digest,
        max_scan_chars=eval_indirect_injection_cross_model.MAX_SCAN_CHARS,
        max_normalized_chars=(
            eval_indirect_injection_cross_model.MAX_NORMALIZED_CHARS
        ),
        max_decoded_views=eval_indirect_injection_cross_model.MAX_DECODED_VIEWS,
    )


def _patch_main_preflight(monkeypatch: pytest.MonkeyPatch, plan):
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "_git_provenance",
        lambda _root: _clean_git(),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "_load_component_context",
        lambda _plan: _component_context(_plan),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "fetch_ollama_identities",
        lambda _plan: _runtime(_plan),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "_capture_execution_invariants",
        lambda _plan, _runtime, _args: _execution(),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "_capture_current_effective_static_binding",
        lambda _plan, _args: {},
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "_effective_static_binding_from_execution",
        lambda _plan, _execution: {},
    )


def _real_matrix_for_main(tmp_path: Path, writer_v3_inputs):
    bundle, built, result = writer_v3_inputs
    plan, _ = load_cross_model_plan(PLAN_PATH)
    runtime = _runtime(plan)
    component_root = tmp_path / "components"
    matrix_root = tmp_path / "matrix"
    args = eval_indirect_injection_cross_model.build_parser().parse_args(
        [
            "--out-dir",
            str(component_root),
            "--index-root",
            str(tmp_path / "indexes"),
            "--matrix-out-dir",
            str(matrix_root),
        ]
    )
    execution = eval_indirect_injection_cross_model._capture_execution_invariants(
        plan,
        runtime,
        args,
    )
    current_git = matrix_fixtures._component_manifest(
        bundle,
        built,
        result,
        "baseline",
    ).git.model_dump(mode="python")
    forbidden = live_writer_tests._forbidden_texts(bundle)
    component_root.mkdir()
    components = {}
    for role in ("baseline", "replication"):
        payload = matrix_fixtures._component_manifest(
            bundle,
            built,
            result,
            role,
        ).model_dump(mode="python")
        payload["git"] = dict(current_git)
        payload["environment"].update(
            {
                "python_version": execution.python_version,
                "platform": execution.platform,
                "dependency_snapshot_path": execution.dependency_snapshot_path,
                "dependency_snapshot_sha256": execution.dependency_snapshot_sha256,
                "installed_snapshot_sha256": execution.installed_snapshot_sha256,
                "installed_package_count": execution.installed_package_count,
                "ollama_version": execution.ollama_version,
                "ollama_endpoint": execution.ollama_origin,
            }
        )
        payload["models"].update(
            {
                "embedding": runtime.embedding,
                "chat": runtime.chats[role],
                "max_attempts": execution.structured_generation_max_attempts,
            }
        )
        payload["transport"] = {
            "model_request_timeout_seconds": execution.model_request_timeout_seconds,
            "model_max_attempts": execution.model_max_attempts,
            "model_retry_backoff_ms": execution.model_retry_backoff_ms,
        }
        payload["retrieval"].update(
            {
                "production_active_index": execution.production_active_index,
                "top_k": execution.top_k,
                "candidate_k": execution.candidate_k,
                "max_search_calls": execution.max_search_calls,
                "max_open_calls": execution.max_open_calls,
                "max_steps": execution.max_steps,
                "max_context_chars": execution.max_context_chars,
            }
        )
        payload["evaluator"] = {
            "path": execution.evaluator_path,
            "sha256": execution.evaluator_sha256,
            "argv": execution.canonical_argv,
            "exit_code": 0,
        }
        manifest = eval_indirect_injection_cross_model.LiveSecurityRunManifestV3.model_validate(
            payload
        )
        components[role] = publish_live_security_run(
            component_root,
            manifest,
            result,
            paired_evidence="offline fixture\n",
            commands="offline fixture\n",
            test_output="offline fixture\n",
            forbidden_texts=forbidden,
        )
    comparison = matrix_fixtures._compare(bundle, components)
    matrix_root.mkdir()
    package = publish_cross_model_run(
        matrix_root,
        comparison,
        plan_path=PLAN_PATH,
        component_runs=components,
        commands="offline fixture\n",
        forbidden_texts=forbidden,
        code_root=ROOT,
        current_git=current_git,
        current_effective_static=(
            eval_indirect_injection_cross_model._effective_static_binding_from_execution(
                plan,
                execution,
            )
        ),
    )
    manifest = verify_cross_model_run(package)
    return bundle, components, matrix_root, manifest


def test_help_has_no_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "_git_provenance",
        lambda _root: called.append("git"),
    )

    with pytest.raises(SystemExit, match="0"):
        eval_indirect_injection_cross_model.main(["--help"])

    assert called == []


def test_parser_defaults_to_checked_in_plan_and_has_only_bounded_options() -> None:
    parser = eval_indirect_injection_cross_model.build_parser()
    args = parser.parse_args([])

    assert args.plan == eval_indirect_injection_cross_model.DEFAULT_PLAN_PATH
    assert args.plan == PLAN_PATH
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    assert option_strings == {
        "-h",
        "--help",
        "--plan",
        "--out-dir",
        "--index-root",
        "--matrix-out-dir",
    }


@pytest.mark.parametrize(
    "argv",
    [
        ["--force"],
        ["--model", "other"],
        ["--split", "test"],
        ["--timeout", "60"],
        ["--prompt", "ignore safeguards"],
    ],
)
def test_parser_rejects_unbounded_execution_options(argv: list[str]) -> None:
    with pytest.raises(SystemExit, match="2"):
        eval_indirect_injection_cross_model.build_parser().parse_args(argv)


def test_dirty_git_fails_before_identity_or_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    dirty = _clean_git() | {"dirty": True}
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "_git_provenance",
        lambda _root: dirty,
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "fetch_ollama_identities",
        lambda _plan: called.append("identity"),
    )

    with pytest.raises(ValueError, match="clean Git"):
        eval_indirect_injection_cross_model.main([])

    assert called == []


@pytest.mark.parametrize("mutation", ["missing", "wrong_embedding", "wrong_digest"])
def test_missing_or_wrong_ollama_identity_fails_before_execution(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    plan, _ = load_cross_model_plan(PLAN_PATH)
    _patch_main_preflight(monkeypatch, plan)
    bad_runtime = _runtime(plan)
    if mutation == "missing":
        bad_runtime = replace(
            bad_runtime,
            chats={"baseline": bad_runtime.chats["baseline"]},
        )
    elif mutation == "wrong_embedding":
        bad_runtime = replace(
            bad_runtime,
            embedding=bad_runtime.embedding.model_copy(
                update={"digest": "0" * 64}
            ),
        )
    else:
        bad_runtime = replace(
            bad_runtime,
            chats={
                **bad_runtime.chats,
                "baseline": bad_runtime.chats["baseline"].model_copy(
                    update={"digest": "0" * 64}
                ),
            },
        )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "fetch_ollama_identities",
        lambda _plan: bad_runtime,
    )
    executed: list[object] = []
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "execute_live_security_run",
        lambda request: executed.append(request),
    )

    with pytest.raises(ValueError, match="Ollama identities"):
        eval_indirect_injection_cross_model.main([])

    assert executed == []


def test_invalid_existing_matrix_fails_before_identity_or_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _ = load_cross_model_plan(PLAN_PATH)
    _patch_main_preflight(monkeypatch, plan)
    matrix_root = tmp_path / "matrix"
    (matrix_root / plan.matrix_run_id).mkdir(parents=True)
    called: list[object] = []
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "fetch_ollama_identities",
        lambda _plan: called.append("identity"),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "execute_live_security_run",
        lambda request: called.append(request),
    )

    with pytest.raises(ValueError, match="artifact set"):
        eval_indirect_injection_cross_model.main(["--matrix-out-dir", str(matrix_root)])

    assert called == []


def test_exact_existing_matrix_is_reused_without_identity_or_component_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan, _ = load_cross_model_plan(PLAN_PATH)
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "_git_provenance",
        lambda _root: _clean_git(),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "_load_component_context",
        lambda _plan: _component_context(_plan),
    )
    matrix_root = tmp_path / "matrix"
    matrix_target = matrix_root / plan.matrix_run_id
    matrix_target.mkdir(parents=True)
    called: list[str] = []
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "validate_current_cross_model_bindings",
        lambda *args, **kwargs: SimpleNamespace(
            matrix_run_id=plan.matrix_run_id,
            decision="CONSISTENT_OBSERVATION",
        ),
        raising=False,
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "fetch_ollama_identities",
        lambda _plan: called.append("identity"),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "run_component",
        lambda *args, **kwargs: called.append("component"),
    )

    assert eval_indirect_injection_cross_model.main(
        [
            "--out-dir", str(tmp_path / "components"),
            "--index-root", str(tmp_path / "indexes"),
            "--matrix-out-dir", str(matrix_root),
        ]
    ) == 0

    assert called == []
    payload = json.loads(capsys.readouterr().out)
    assert payload["matrix_run_id"] == plan.matrix_run_id
    assert payload["reused"] is True


def test_real_existing_matrix_is_readmitted_by_main_without_model_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    writer_v3_inputs,
) -> None:
    _, components, matrix_root, manifest = _real_matrix_for_main(
        tmp_path,
        writer_v3_inputs,
    )
    current_git = manifest.git.model_dump(mode="python")
    called: list[str] = []
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "_git_provenance",
        lambda _root: dict(current_git),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "fetch_ollama_identities",
        lambda _plan: called.append("identity"),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "execute_live_security_run",
        lambda _request: called.append("execution"),
    )

    assert eval_indirect_injection_cross_model.main(
        [
            "--out-dir",
            str(components["baseline"].parent),
            "--index-root",
            str(tmp_path / "indexes"),
            "--matrix-out-dir",
            str(matrix_root),
        ]
    ) == 0

    assert called == []
    assert json.loads(capsys.readouterr().out)["reused"] is True


@pytest.mark.parametrize("mutation", ["git", "data", "guard", "dependency"])
def test_real_existing_matrix_rejects_current_binding_mismatch_before_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer_v3_inputs,
    mutation: str,
) -> None:
    bundle, components, matrix_root, manifest = _real_matrix_for_main(
        tmp_path,
        writer_v3_inputs,
    )
    current_git = manifest.git.model_dump(mode="python")
    if mutation == "git":
        current_git["head"] = "b" * 40
    elif mutation == "data":
        current_bundle = matrix_writer.load_security_bundle(
            ROOT / "data" / "v2" / "security",
            "dev",
        )
        stale = replace(current_bundle, dataset_sha256="0" * 64)
        monkeypatch.setattr(matrix_writer, "load_security_bundle", lambda *_: stale)
    else:
        if mutation == "guard":
            monkeypatch.setattr(matrix_writer, "DETECTOR_VERSION", "changed-guard")
        else:
            installed = eval_indirect_injection_cross_model._installed_dependency_snapshot()
            installed["installed_snapshot_sha256"] = "f" * 64
            monkeypatch.setattr(
                eval_indirect_injection_cross_model,
                "_installed_dependency_snapshot",
                lambda: installed,
            )
    called: list[str] = []
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "_git_provenance",
        lambda _root: dict(current_git),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "fetch_ollama_identities",
        lambda _plan: called.append("identity"),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "execute_live_security_run",
        lambda _request: called.append("execution"),
    )

    with pytest.raises(ValueError, match="Git|dataset|Guard|static"):
        eval_indirect_injection_cross_model.main(
            [
                "--out-dir",
                str(components["baseline"].parent),
                "--index-root",
                str(tmp_path / "indexes"),
                "--matrix-out-dir",
                str(matrix_root),
            ]
        )

    assert called == []


def test_real_new_flow_compares_publishes_and_readmits_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer_v3_inputs,
) -> None:
    bundle, built, result = writer_v3_inputs
    plan, _ = load_cross_model_plan(PLAN_PATH)
    runtime = _runtime(plan)
    current_git = matrix_fixtures._component_manifest(
        bundle,
        built,
        result,
        "baseline",
    ).git.model_dump(mode="python")
    args = eval_indirect_injection_cross_model.build_parser().parse_args(
        [
            "--out-dir",
            str(tmp_path / "components"),
            "--index-root",
            str(tmp_path / "indexes"),
            "--matrix-out-dir",
            str(tmp_path / "matrix"),
        ]
    )
    execution = eval_indirect_injection_cross_model._capture_execution_invariants(
        plan,
        runtime,
        args,
    )
    roles: list[str] = []

    def execute(request):
        role = request.experiment.model_role
        roles.append(role)
        payload = matrix_fixtures._component_manifest(
            bundle,
            built,
            result,
            role,
        ).model_dump(mode="python")
        payload["run_id"] = request.args.run_id
        payload["git"] = dict(current_git)
        payload["environment"].update(
            {
                "python_version": execution.python_version,
                "platform": execution.platform,
                "dependency_snapshot_path": execution.dependency_snapshot_path,
                "dependency_snapshot_sha256": execution.dependency_snapshot_sha256,
                "installed_snapshot_sha256": execution.installed_snapshot_sha256,
                "installed_package_count": execution.installed_package_count,
                "ollama_version": execution.ollama_version,
                "ollama_endpoint": execution.ollama_origin,
            }
        )
        payload["models"].update(
            {
                "embedding": runtime.embedding,
                "chat": runtime.chats[role],
                "evidence_model": "NOT_USED_D7_LIVE_PAIRED",
                "temperature": 0.0,
                "structured_output_variant": "generation-v2-json-schema",
                "think": False,
                "max_attempts": execution.structured_generation_max_attempts,
            }
        )
        payload["transport"] = {
            "model_request_timeout_seconds": execution.model_request_timeout_seconds,
            "model_max_attempts": execution.model_max_attempts,
            "model_retry_backoff_ms": execution.model_retry_backoff_ms,
        }
        payload["retrieval"].update(
            {
                "production_active_index": execution.production_active_index,
                "top_k": execution.top_k,
                "candidate_k": execution.candidate_k,
                "max_search_calls": execution.max_search_calls,
                "max_open_calls": execution.max_open_calls,
                "max_steps": execution.max_steps,
                "max_context_chars": execution.max_context_chars,
            }
        )
        payload["evaluator"] = {
            "path": execution.evaluator_path,
            "sha256": execution.evaluator_sha256,
            "argv": execution.canonical_argv,
            "exit_code": 0,
        }
        payload["experiment"] = request.experiment
        manifest = eval_indirect_injection_cross_model.LiveSecurityRunManifestV3.model_validate(
            payload
        )
        target = publish_live_security_run(
            request.args.out_dir,
            manifest,
            result,
            paired_evidence="offline model-boundary fixture\n",
            commands="offline model-boundary fixture\n",
            test_output="offline model-boundary fixture\n",
            forbidden_texts=live_writer_tests._forbidden_texts(bundle),
        )
        return eval_indirect_injection_cross_model.LiveExecutionOutcome(
            output_dir=target,
            manifest=manifest,
        )

    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "_git_provenance",
        lambda _root: dict(current_git),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "fetch_ollama_identities",
        lambda _plan: runtime,
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "execute_live_security_run",
        execute,
    )

    assert eval_indirect_injection_cross_model.main(
        [
            "--out-dir",
            str(tmp_path / "components"),
            "--index-root",
            str(tmp_path / "indexes"),
            "--matrix-out-dir",
            str(tmp_path / "matrix"),
        ]
    ) == 0

    assert roles == ["baseline", "replication"]
    matrix = tmp_path / "matrix" / plan.matrix_run_id
    assert verify_cross_model_run(matrix).decision == "CONSISTENT_OBSERVATION"


def test_runs_absent_components_baseline_then_replication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan, _ = load_cross_model_plan(PLAN_PATH)
    _patch_main_preflight(monkeypatch, plan)
    requests: list[object] = []
    outcomes: dict[str, object] = {}
    published: list[object] = []

    def execute(request):
        requests.append(request)
        manifest = SimpleNamespace(
            run_id=request.args.run_id,
            status="COMPLETED WITH OBSERVATIONS",
            observation=SimpleNamespace(protocol_complete=True),
        )
        outcome = SimpleNamespace(
            output_dir=request.args.out_dir / request.args.run_id,
            manifest=manifest,
        )
        outcomes[request.args.run_id] = outcome
        return outcome

    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "execute_live_security_run",
        execute,
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "admit_existing_component",
        lambda target, **_kwargs: outcomes[target.name],
    )
    comparison = SimpleNamespace(
        matrix_run_id=plan.matrix_run_id,
        decision="CONSISTENT_OBSERVATION",
        invariant_mismatches=(),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "compare_verified_runs",
        lambda *args, **kwargs: comparison,
        raising=False,
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "publish_cross_model_run",
        lambda *args, **kwargs: published.append((args, kwargs))
        or (tmp_path / "matrix" / plan.matrix_run_id),
        raising=False,
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "_forbidden_fixture_texts",
        lambda _bundle: ("private-fixture-text",),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "validate_current_cross_model_bindings",
        lambda *args, **kwargs: SimpleNamespace(
            matrix_run_id=plan.matrix_run_id,
            decision="CONSISTENT_OBSERVATION",
        ),
        raising=False,
    )

    assert eval_indirect_injection_cross_model.main(
        [
            "--out-dir", str(tmp_path / "runs"),
            "--index-root", str(tmp_path / "indexes"),
            "--matrix-out-dir", str(tmp_path / "matrix"),
        ]
    ) == 0

    assert [request.experiment.model_role for request in requests] == [
        "baseline",
        "replication",
    ]
    assert [request.chat_model for request in requests] == [
        "qwen2.5:3b",
        "qwen3:8b",
    ]
    assert len(published) == 1
    assert '"reused": false' in capsys.readouterr().out


def test_git_transition_after_component_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _ = load_cross_model_plan(PLAN_PATH)
    _patch_main_preflight(monkeypatch, plan)
    snapshots = [_clean_git(), _clean_git() | {"head": "f" * 40}]
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "_git_provenance",
        lambda _root: snapshots.pop(0),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "run_component",
        lambda *args, **kwargs: SimpleNamespace(
            role="baseline",
            reused=False,
            outcome=SimpleNamespace(
                output_dir=tmp_path,
                manifest=SimpleNamespace(
                    run_id="run", status="COMPLETED WITH OBSERVATIONS", observation=SimpleNamespace(protocol_complete=True)
                ),
            ),
        ),
    )

    with pytest.raises(RuntimeError, match="Git state changed"):
        eval_indirect_injection_cross_model.main([])


def test_frozen_d7_target_is_rejected_before_git_or_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, plan_sha256 = load_cross_model_plan(PLAN_PATH)
    frozen_plan = plan.model_copy(
        update={
            "chat_models": (
                plan.chat_models[0].model_copy(
                    update={
                        "run_id": "r2-s1-d7-test-20260718-01",
                    }
                ),
                plan.chat_models[1],
            )
        }
    )
    called: list[str] = []
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "load_cross_model_plan",
        lambda _path: (frozen_plan, plan_sha256),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "_git_provenance",
        lambda _root: called.append("git"),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "fetch_ollama_identities",
        lambda _plan: called.append("identity"),
    )

    with pytest.raises(ValueError, match="frozen formal D7 run ID"):
        eval_indirect_injection_cross_model.main([])

    assert called == []


def test_admission_reuses_only_a_complete_exact_v3_component(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, plan_sha256 = load_cross_model_plan(PLAN_PATH)
    component = plan.model_for_role("baseline")
    context = _component_context(plan)
    runtime = _runtime(plan)
    manifest = SimpleNamespace(
        run_id=component.run_id,
        split="dev",
        status="COMPLETED WITH OBSERVATIONS",
        observation=SimpleNamespace(protocol_complete=True),
        experiment=SimpleNamespace(
            plan_id=plan.experiment_id,
            plan_sha256=plan_sha256,
            model_role="baseline",
            only_changed_variable=plan.only_changed_variable,
        ),
        git=_clean_git(),
        data=SimpleNamespace(
            dataset_path=str(context.data.dataset_path.relative_to(ROOT).as_posix()),
            dataset_sha256=context.data.dataset_sha256,
            fixture_manifest_path=str(context.data.fixture_manifest_path.relative_to(ROOT).as_posix()),
            fixture_manifest_sha256=context.data.fixture_manifest_sha256,
            dataset_case_count=36,
            attack_case_count=18,
            benign_case_count=18,
            r1_frozen_hashes={},
        ),
        guard=_guard(context.guard_sha256),
        models=SimpleNamespace(embedding=runtime.embedding, chat=runtime.chats["baseline"]),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "LiveSecurityRunManifestV3",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "verify_live_security_run",
        lambda _target: manifest,
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "_validate_execution_invariants",
        lambda *_args: None,
    )

    outcome = eval_indirect_injection_cross_model.admit_existing_component(
        tmp_path,
        plan=plan,
        plan_sha256=plan_sha256,
        component=component,
        git_provenance=_clean_git(),
        context=context,
        runtime=runtime,
        execution=_execution(),
    )

    assert outcome is not None
    assert outcome.manifest is manifest


@pytest.mark.parametrize(
    "field, value",
    [
        ("schema", "v2"),
        ("plan_sha256", "0" * 64),
        ("model_role", "replication"),
        ("run_id", "wrong-run"),
        ("git", _clean_git() | {"head": "f" * 40}),
        ("protocol_complete", False),
        ("dataset_sha256", "0" * 64),
        ("guard_sha256", "0" * 64),
    ],
)
def test_admission_rejects_partial_or_contradictory_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    plan, plan_sha256 = load_cross_model_plan(PLAN_PATH)
    component = plan.model_for_role("baseline")
    context = _component_context(plan)
    runtime = _runtime(plan)
    manifest = SimpleNamespace(
        run_id=component.run_id,
        split="dev",
        status="COMPLETED WITH OBSERVATIONS",
        observation=SimpleNamespace(protocol_complete=True),
        experiment=SimpleNamespace(plan_id=plan.experiment_id, plan_sha256=plan_sha256, model_role="baseline", only_changed_variable=plan.only_changed_variable),
        git=_clean_git(),
        data=SimpleNamespace(dataset_path=str(context.data.dataset_path.relative_to(ROOT).as_posix()), dataset_sha256=context.data.dataset_sha256, fixture_manifest_path=str(context.data.fixture_manifest_path.relative_to(ROOT).as_posix()), fixture_manifest_sha256=context.data.fixture_manifest_sha256, dataset_case_count=36, attack_case_count=18, benign_case_count=18, r1_frozen_hashes={}),
        guard=_guard(context.guard_sha256),
        models=SimpleNamespace(embedding=runtime.embedding, chat=runtime.chats["baseline"]),
    )
    if field == "schema":
        monkeypatch.setattr(eval_indirect_injection_cross_model, "LiveSecurityRunManifestV3", type("Other", (), {}))
    else:
        monkeypatch.setattr(eval_indirect_injection_cross_model, "LiveSecurityRunManifestV3", SimpleNamespace)
        if field == "plan_sha256":
            manifest.experiment.plan_sha256 = value
        elif field == "model_role":
            manifest.experiment.model_role = value
        elif field == "protocol_complete":
            manifest.observation.protocol_complete = value
        elif field == "guard_sha256":
            manifest.guard.ruleset_sha256 = value
        elif field == "dataset_sha256":
            manifest.data.dataset_sha256 = value
        else:
            setattr(manifest, field, value)
    monkeypatch.setattr(eval_indirect_injection_cross_model, "verify_live_security_run", lambda _target: manifest)
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "_validate_execution_invariants",
        lambda *_args: None,
    )

    with pytest.raises(ValueError, match="existing component"):
        eval_indirect_injection_cross_model.admit_existing_component(
            tmp_path,
            plan=plan,
            plan_sha256=plan_sha256,
            component=component,
            git_provenance=_clean_git(),
            context=context,
            runtime=runtime,
            execution=_execution(),
        )


def test_admission_propagates_artifact_verification_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, plan_sha256 = load_cross_model_plan(PLAN_PATH)
    component = plan.model_for_role("baseline")
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "verify_live_security_run",
        lambda _target: (_ for _ in ()).throw(ValueError("artifact mismatch")),
    )

    with pytest.raises(ValueError, match="artifact mismatch"):
        eval_indirect_injection_cross_model.admit_existing_component(
            tmp_path,
            plan=plan,
            plan_sha256=plan_sha256,
            component=component,
            git_provenance=_clean_git(),
            context=_component_context(plan),
            runtime=_runtime(plan),
            execution=_execution(),
        )


def test_new_component_manifest_with_different_git_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _ = load_cross_model_plan(PLAN_PATH)
    _patch_main_preflight(monkeypatch, plan)
    executions: list[object] = []
    outcomes: dict[str, object] = {}

    def execute(request):
        executions.append(request)
        outcome = SimpleNamespace(
            output_dir=request.args.out_dir / request.args.run_id,
            manifest=SimpleNamespace(
                run_id=request.args.run_id,
                status="COMPLETED WITH OBSERVATIONS",
                observation=SimpleNamespace(protocol_complete=True),
                git=_clean_git() | {"head": "f" * 40},
            ),
        )
        outcomes[request.args.run_id] = outcome
        return outcome

    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "execute_live_security_run",
        execute,
    )
    def reject_git(target, **_kwargs):
        manifest = outcomes[target.name].manifest
        if manifest.git != _clean_git():
            raise ValueError("existing component has contradictory Git binding")
        return outcomes[target.name]

    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "admit_existing_component",
        reject_git,
    )

    with pytest.raises(ValueError, match="Git binding"):
        eval_indirect_injection_cross_model.main(
            [
                "--out-dir", str(tmp_path / "safe-runs"),
                "--index-root", str(tmp_path / "safe-indexes"),
                "--matrix-out-dir", str(tmp_path / "safe-matrix"),
            ]
        )

    assert len(executions) == 1


def test_git_transition_between_components_stops_before_replication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _ = load_cross_model_plan(PLAN_PATH)
    _patch_main_preflight(monkeypatch, plan)
    snapshots = [
        _clean_git(),
        _clean_git(),
        _clean_git() | {"head": "f" * 40},
        _clean_git(),
    ]
    executed: list[str] = []
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "_git_provenance",
        lambda _root: snapshots.pop(0),
    )

    def run_component(*args, **kwargs):
        component = kwargs["component"]
        executed.append(component.role)
        return SimpleNamespace(
            role=component.role,
            reused=False,
            outcome=SimpleNamespace(
                output_dir=tmp_path / "safe-component",
                manifest=SimpleNamespace(
                    run_id=component.run_id,
                    status="COMPLETED WITH OBSERVATIONS",
                    observation=SimpleNamespace(protocol_complete=True),
                ),
            ),
        )

    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "run_component",
        run_component,
    )

    with pytest.raises(RuntimeError, match="Git state changed"):
        eval_indirect_injection_cross_model.main([])

    assert executed == ["baseline"]


def test_admission_reuses_real_writer_generated_v3_package(
    tmp_path: Path,
    writer_v3_inputs,
) -> None:
    target, plan, plan_sha256, component, context, runtime, execution = (
        _real_admission_inputs(tmp_path, writer_v3_inputs)
    )

    outcome = eval_indirect_injection_cross_model.admit_existing_component(
        target,
        plan=plan,
        plan_sha256=plan_sha256,
        component=component,
        git_provenance=_clean_git(),
        context=context,
        runtime=runtime,
        execution=execution,
    )

    assert outcome.output_dir == target
    assert outcome.manifest.run_id == "r2-s4-admission-fixture"


@pytest.mark.parametrize(
    "mutation",
    ["partial", "extra", "checksum", "artifact", "manifest"],
)
def test_admission_rejects_real_v3_artifact_tampering_without_execution(
    tmp_path: Path,
    writer_v3_inputs,
    mutation: str,
) -> None:
    target, plan, plan_sha256, component, context, runtime, execution = (
        _real_admission_inputs(tmp_path, writer_v3_inputs)
    )
    if mutation == "partial":
        (target / "failures.csv").unlink()
    elif mutation == "extra":
        (target / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
    elif mutation == "checksum":
        (target / "checksums.sha256").write_text("tampered\n", encoding="utf-8")
    elif mutation == "artifact":
        with (target / "summary.json").open("a", encoding="utf-8") as stream:
            stream.write("\n")
    else:
        (target / "manifest.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises((ValueError, ValidationError)):
        eval_indirect_injection_cross_model.admit_existing_component(
            target,
            plan=plan,
            plan_sha256=plan_sha256,
            component=component,
            git_provenance=_clean_git(),
            context=context,
            runtime=runtime,
            execution=execution,
        )


@pytest.mark.parametrize(
    "field, value",
    [
        ("max_attempts", 1),
        ("ollama_version", "0.0.0"),
        ("installed_snapshot_sha256", "0" * 64),
    ],
)
def test_admission_rejects_real_v3_execution_invariant_mismatch(
    tmp_path: Path,
    writer_v3_inputs,
    field: str,
    value: object,
) -> None:
    target, plan, plan_sha256, component, context, runtime, execution = (
        _real_admission_inputs(tmp_path, writer_v3_inputs)
    )
    if field == "max_attempts":
        execution = replace(execution, structured_generation_max_attempts=value)
    elif field == "ollama_version":
        execution = replace(execution, ollama_version=value)
    else:
        execution = replace(execution, installed_snapshot_sha256=value)

    with pytest.raises(ValueError, match="execution invariant"):
        eval_indirect_injection_cross_model.admit_existing_component(
            target,
            plan=plan,
            plan_sha256=plan_sha256,
            component=component,
            git_provenance=_clean_git(),
            context=context,
            runtime=runtime,
            execution=execution,
        )


@pytest.mark.parametrize("binding", ["git", "data", "guard", "model"])
def test_admission_rejects_real_v3_binding_mismatch(
    tmp_path: Path,
    writer_v3_inputs,
    binding: str,
) -> None:
    target, plan, plan_sha256, component, context, runtime, execution = (
        _real_admission_inputs(tmp_path, writer_v3_inputs)
    )
    git = _clean_git()
    if binding == "git":
        git = git | {"head": "f" * 40}
    elif binding == "data":
        altered_data = SimpleNamespace(**vars(context.data))
        altered_data.dataset_sha256 = "0" * 64
        context = replace(context, data=altered_data)
    elif binding == "guard":
        context = replace(context, guard_sha256="0" * 64)
    else:
        runtime = replace(
            runtime,
            chats={
                **runtime.chats,
                "replication": runtime.chats["replication"].model_copy(
                    update={"digest": "0" * 64}
                ),
            },
        )

    with pytest.raises(ValueError):
        eval_indirect_injection_cross_model.admit_existing_component(
            target,
            plan=plan,
            plan_sha256=plan_sha256,
            component=component,
            git_provenance=git,
            context=context,
            runtime=runtime,
            execution=execution,
        )


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("environment", "python_version", "0.0.0"),
        ("environment", "platform", "Other-platform"),
        ("evaluator", "path", "scripts/eval_indirect_injection_live.py"),
        ("evaluator", "sha256", "0" * 64),
        (
            "evaluator",
            "argv",
            ["python", "-m", "scripts.eval_indirect_injection_live"],
        ),
    ],
)
def test_admission_rejects_real_v3_environment_or_evaluator_mismatch(
    tmp_path: Path,
    writer_v3_inputs,
    section: str,
    field: str,
    value: object,
) -> None:
    target, plan, plan_sha256, component, context, runtime, execution = (
        _real_admission_inputs(tmp_path, writer_v3_inputs)
    )
    payload = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    payload[section][field] = value
    (target / "manifest.json").write_bytes(
        live_writer_tests.live_writer._json_bytes(payload)
    )

    with pytest.raises(ValueError, match="execution invariant"):
        eval_indirect_injection_cross_model.admit_existing_component(
            target,
            plan=plan,
            plan_sha256=plan_sha256,
            component=component,
            git_provenance=_clean_git(),
            context=context,
            runtime=runtime,
            execution=execution,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_request_timeout_seconds", 1.0),
        ("model_max_attempts", 1),
        ("model_retry_backoff_ms", 0),
    ],
)
def test_admission_rejects_real_v3_transport_policy_mismatch(
    tmp_path: Path,
    writer_v3_inputs,
    field: str,
    value: object,
) -> None:
    target, plan, plan_sha256, component, context, runtime, execution = (
        _real_admission_inputs(tmp_path, writer_v3_inputs)
    )
    payload = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    payload["transport"][field] = value
    (target / "manifest.json").write_bytes(
        live_writer_tests.live_writer._json_bytes(payload)
    )

    with pytest.raises(ValueError, match="execution invariant"):
        eval_indirect_injection_cross_model.admit_existing_component(
            target,
            plan=plan,
            plan_sha256=plan_sha256,
            component=component,
            git_provenance=_clean_git(),
            context=context,
            runtime=runtime,
            execution=execution,
        )

@pytest.mark.parametrize("schema", ["v1", "v2"])
def test_admission_rejects_real_verified_legacy_packages(
    tmp_path: Path,
    writer_legacy_inputs,
    schema: str,
) -> None:
    v1_inputs, v2_inputs = writer_legacy_inputs
    bundle, built, result = v1_inputs if schema == "v1" else v2_inputs
    manifest = (
        live_writer_tests._manifest(bundle, built, result)
        if schema == "v1"
        else live_writer_tests._manifest_v2(bundle, built, result)
    )
    target = publish_live_security_run(
        tmp_path / "legacy-runs",
        manifest,
        result,
        paired_evidence="safe",
        commands="safe",
        test_output="safe",
        forbidden_texts=live_writer_tests._forbidden_texts(bundle),
    )
    plan, plan_sha256 = load_cross_model_plan(PLAN_PATH)

    with pytest.raises(ValueError, match="complete V3"):
        eval_indirect_injection_cross_model.admit_existing_component(
            target,
            plan=plan,
            plan_sha256=plan_sha256,
            component=plan.model_for_role("baseline"),
            git_provenance=_clean_git(),
            context=_component_context(plan),
            runtime=_runtime(plan),
            execution=_execution(),
        )


def test_redirected_output_root_fails_before_identity_activity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _ = load_cross_model_plan(PLAN_PATH)
    root = tmp_path / "redirected-output"
    root.mkdir()
    called: list[str] = []
    root_stat = root.lstat()
    real_lstat = Path.lstat

    def mark_root(path: Path):
        if path == root:
            return with_reparse_point_attribute(root_stat)
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", mark_root)
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "fetch_ollama_identities",
        lambda _plan: called.append("identity"),
    )

    with pytest.raises(ValueError, match="output root cannot be a symlink"):
        eval_indirect_injection_cross_model.main(
            [
                "--out-dir", str(root),
                "--index-root", str(tmp_path / "safe-index"),
                "--matrix-out-dir", str(tmp_path / "safe-matrix"),
            ]
        )

    assert called == []


def test_dangling_component_target_fails_before_identity_activity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _ = load_cross_model_plan(PLAN_PATH)
    root = tmp_path / "safe-output"
    root.mkdir()
    target = root / plan.model_for_role("baseline").run_id
    root_stat = root.lstat()
    real_lstat = Path.lstat
    called: list[str] = []

    def mark_target(path: Path):
        if path == target:
            return with_reparse_point_attribute(root_stat)
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", mark_target)
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "fetch_ollama_identities",
        lambda _plan: called.append("identity"),
    )

    with pytest.raises(ValueError, match="component output cannot be a symlink"):
        eval_indirect_injection_cross_model.main(
            [
                "--out-dir", str(root),
                "--index-root", str(tmp_path / "safe-index"),
                "--matrix-out-dir", str(tmp_path / "safe-matrix"),
            ]
        )

    assert called == []


@pytest.mark.parametrize(
    ("option", "label"),
    [
        ("--out-dir", "output root"),
        ("--index-root", "index root"),
        ("--matrix-out-dir", "matrix output root"),
    ],
)
def test_real_directory_redirect_roots_fail_before_identity_or_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    option: str,
    label: str,
) -> None:
    referent = tmp_path / "redirect-referent"
    referent.mkdir()
    redirect = tmp_path / "redirect-root"
    called: list[str] = []
    values = {
        "--out-dir": str(tmp_path / "safe-output"),
        "--index-root": str(tmp_path / "safe-index"),
        "--matrix-out-dir": str(tmp_path / "safe-matrix"),
    }
    values[option] = str(redirect)
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "fetch_ollama_identities",
        lambda _plan: called.append("identity"),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "execute_live_security_run",
        lambda _request: called.append("execution"),
    )

    with directory_redirect(redirect, referent):
        with pytest.raises(ValueError, match=rf"{label} cannot be a symlink"):
            eval_indirect_injection_cross_model.main(
                [
                    "--out-dir", values["--out-dir"],
                    "--index-root", values["--index-root"],
                    "--matrix-out-dir", values["--matrix-out-dir"],
                ]
            )

    assert called == []


@pytest.mark.parametrize("target_kind", ["component", "matrix"])
def test_real_dangling_targets_fail_before_identity_or_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_kind: str,
) -> None:
    plan, plan_sha256 = load_cross_model_plan(PLAN_PATH)
    output_root = tmp_path / "safe-output"
    index_root = tmp_path / "safe-index"
    matrix_root = tmp_path / "safe-matrix"
    root = output_root if target_kind == "component" else matrix_root
    root.mkdir()
    if target_kind == "component":
        component = plan.model_for_role("baseline").model_copy(
            update={"run_id": "r2-s4-dangling-component-fixture"}
        )
        plan = plan.model_copy(
            update={
                "chat_models": tuple(
                    component if item.role == "baseline" else item
                    for item in plan.chat_models
                )
            }
        )
        target = root / component.run_id
        label = "component output"
    else:
        plan = plan.model_copy(
            update={"matrix_run_id": "r2-s4-dangling-matrix-fixture"}
        )
        target = root / plan.matrix_run_id
        label = "matrix output"
    called: list[str] = []
    try:
        target.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"dangling directory symlink creation is unavailable: {exc}")
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "load_cross_model_plan",
        lambda _path: (plan, plan_sha256),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "fetch_ollama_identities",
        lambda _plan: called.append("identity"),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "execute_live_security_run",
        lambda _request: called.append("execution"),
    )

    try:
        with pytest.raises(ValueError, match=rf"{label} cannot be a symlink"):
            eval_indirect_injection_cross_model.main(
                [
                    "--out-dir", str(output_root),
                    "--index-root", str(index_root),
                    "--matrix-out-dir", str(matrix_root),
                ]
            )
    finally:
        if os.path.lexists(target):
            target.unlink()

    assert called == []


@pytest.mark.parametrize(
    ("option", "label"),
    [
        ("--out-dir", "output root"),
        ("--index-root", "index root"),
        ("--matrix-out-dir", "matrix output root"),
    ],
)
def test_frozen_d7_roots_fail_before_identity_or_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    option: str,
    label: str,
) -> None:
    called: list[str] = []
    frozen_child = (
        eval_indirect_injection_cross_model.DEFAULT_OUT_DIR
        / eval_indirect_injection_cross_model.FROZEN_FORMAL_D7_RUN_ID
        / f"{label.replace(' ', '-')}-fixture"
    )
    values = {
        "--out-dir": str(tmp_path / "safe-output"),
        "--index-root": str(tmp_path / "safe-index"),
        "--matrix-out-dir": str(tmp_path / "safe-matrix"),
    }
    values[option] = str(frozen_child)
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "fetch_ollama_identities",
        lambda _plan: called.append("identity"),
    )
    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "execute_live_security_run",
        lambda _request: called.append("execution"),
    )

    with pytest.raises(ValueError, match=rf"{label} cannot be inside the frozen formal D7"):
        eval_indirect_injection_cross_model.main(
            [
                "--out-dir", values["--out-dir"],
                "--index-root", values["--index-root"],
                "--matrix-out-dir", values["--matrix-out-dir"],
            ]
        )

    assert called == []


def test_run_component_rejects_redirected_root_before_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, plan_sha256 = load_cross_model_plan(PLAN_PATH)
    root = tmp_path / "redirected-output"
    root.mkdir()
    root_stat = root.lstat()
    real_lstat = Path.lstat
    real_resolve = Path.resolve

    def mark_root(path: Path):
        if path == root:
            return with_reparse_point_attribute(root_stat)
        return real_lstat(path)

    def reject_root_resolve(path: Path, *args, **kwargs):
        if path == root:
            raise AssertionError("root resolved before lexical rejection")
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", mark_root)
    monkeypatch.setattr(Path, "resolve", reject_root_resolve)
    args = SimpleNamespace(
        out_dir=root,
        index_root=tmp_path / "safe-index",
        matrix_out_dir=tmp_path / "safe-matrix",
        plan=PLAN_PATH,
    )

    with pytest.raises(ValueError, match="output root cannot be a symlink"):
        eval_indirect_injection_cross_model.run_component(
            args,
            plan=plan,
            plan_sha256=plan_sha256,
            component=plan.model_for_role("baseline"),
            git_provenance=_clean_git(),
            context=_component_context(plan),
            runtime=_runtime(plan),
            execution=_execution(),
        )
