from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.evaluation.indirect_injection_cross_model import load_cross_model_plan
from app.evaluation.indirect_injection_live_writer import OllamaModelIdentity
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


def test_occupied_matrix_target_fails_before_execution(
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
        "execute_live_security_run",
        lambda request: called.append(request),
    )

    with pytest.raises(FileExistsError, match="matrix output"):
        eval_indirect_injection_cross_model.main(["--matrix-out-dir", str(matrix_root)])

    assert called == []


def test_runs_absent_components_baseline_then_replication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan, _ = load_cross_model_plan(PLAN_PATH)
    _patch_main_preflight(monkeypatch, plan)
    requests: list[object] = []

    def execute(request):
        requests.append(request)
        manifest = SimpleNamespace(
            run_id=request.args.run_id,
            status="COMPLETED WITH OBSERVATIONS",
            observation=SimpleNamespace(protocol_complete=True),
        )
        return SimpleNamespace(output_dir=request.args.out_dir / request.args.run_id, manifest=manifest)

    monkeypatch.setattr(
        eval_indirect_injection_cross_model,
        "execute_live_security_run",
        execute,
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

    outcome = eval_indirect_injection_cross_model.admit_existing_component(
        tmp_path,
        plan=plan,
        plan_sha256=plan_sha256,
        component=component,
        git_provenance=_clean_git(),
        context=context,
        runtime=runtime,
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

    with pytest.raises(ValueError, match="existing component"):
        eval_indirect_injection_cross_model.admit_existing_component(
            tmp_path,
            plan=plan,
            plan_sha256=plan_sha256,
            component=component,
            git_provenance=_clean_git(),
            context=context,
            runtime=runtime,
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
        )
