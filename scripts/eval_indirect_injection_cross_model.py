from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
import platform
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import requests

from app.config import get_settings
from app.domain.retrieved_security import (
    DETECTOR_VERSION,
    MAX_DECODED_VIEWS,
    MAX_NORMALIZED_CHARS,
    MAX_SCAN_CHARS,
)
from app.evaluation.indirect_injection_cross_model import (
    CLEAN_GIT_STATE_SHA256,
    CrossModelModelPlan,
    CrossModelPlanV1,
    compare_verified_runs,
    load_cross_model_plan,
)
from app.evaluation.indirect_injection_cross_model_writer import (
    publish_cross_model_run,
    validate_current_cross_model_bindings,
)
from app.evaluation.indirect_injection_dataset import (
    LoadedSecurityBundle,
    load_security_bundle,
)
from app.evaluation.ollama_evaluation_lock import (
    evaluation_lock,
    evaluation_lock_path,
    normalized_ollama_origin,
)
from app.evaluation.indirect_injection_live_runner import (
    LiveSecurityConfig,
    LocalOllamaOnlyBoundary,
)
from app.evaluation.indirect_injection_live_writer import (
    CrossModelExperimentBinding,
    LiveIndexReference,
    LiveSecurityRunManifestV3,
    OllamaModelIdentity,
    resolve_ollama_model_identity,
    validate_v3_cross_model_plan_binding,
    verify_live_security_run,
)
from scripts.eval_indirect_injection import (
    _assert_git_provenance_stable,
    _forbidden_fixture_texts,
    _git_provenance,
    _installed_dependency_snapshot,
    _safe_display_path,
    _sha256,
    verify_r1_frozen_hashes,
)
from scripts.eval_indirect_injection_live import (
    DEFAULT_DATA_ROOT,
    FROZEN_FORMAL_D7_RUN_ID,
    LiveExecutionOutcome,
    LiveExecutionRequest,
    _get_json,
    execute_live_security_run,
    production_active_index_reference,
)


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PLAN_PATH = (
    BASE_DIR / "data" / "v2" / "evaluation" / "r2_s4_cross_model_matrix_v1.json"
)
DEFAULT_OUT_DIR = BASE_DIR / "security_runs"
DEFAULT_INDEX_ROOT = DEFAULT_OUT_DIR / ".d7_indexes"
DEFAULT_MATRIX_OUT_DIR = DEFAULT_OUT_DIR / "cross_model_matrices"
_GUARD_RULESET_PATH = "app/security/retrieved_content.py"
_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass(frozen=True)
class OllamaIdentitySnapshot:
    version: str
    embedding: OllamaModelIdentity
    chats: Mapping[str, OllamaModelIdentity]


@dataclass(frozen=True)
class ComponentContext:
    data: LoadedSecurityBundle
    r1_hashes: Mapping[str, object]
    guard_sha256: str


@dataclass(frozen=True)
class ExecutionInvariantSnapshot:
    llm_endpoint: str
    ollama_origin: str
    structured_generation_max_attempts: int
    model_request_timeout_seconds: float
    model_max_attempts: int
    model_retry_backoff_ms: int
    ollama_version: str
    python_version: str
    platform: str
    dependency_snapshot_path: str
    dependency_snapshot_sha256: str
    installed_snapshot_sha256: str
    installed_package_count: int
    production_active_index: LiveIndexReference
    top_k: int
    candidate_k: int
    max_search_calls: int
    max_open_calls: int
    max_steps: int
    max_context_chars: int
    evaluator_path: str
    evaluator_sha256: str
    canonical_argv: tuple[str, ...]


@dataclass(frozen=True)
class ComponentRun:
    role: str
    reused: bool
    admission_kind: str
    outcome: LiveExecutionOutcome


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen R2-S4 cross-model indirect-injection matrix."
    )
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--index-root", type=Path, default=DEFAULT_INDEX_ROOT)
    parser.add_argument(
        "--matrix-out-dir",
        type=Path,
        default=DEFAULT_MATRIX_OUT_DIR,
    )
    return parser


def _configured_ollama_origin() -> str:
    settings = get_settings()
    baseline = LiveSecurityConfig(
        llm_endpoint=settings.llm_base_url,
        chat_model="qwen2.5:3b",
        structured_generation_max_attempts=settings.structured_generation_max_attempts,
    )
    return baseline.ollama_origin


def _normalized_ollama_origin(origin: str) -> str:
    return normalized_ollama_origin(origin)


def _evaluation_lock_path(origin: str, *, lock_root: Path | None = None) -> Path:
    return evaluation_lock_path(origin, lock_root=lock_root)


def _evaluation_lock(origin: str, *, lock_root: Path | None = None):
    return evaluation_lock(origin, lock_root=lock_root)


def fetch_ollama_identities(plan: CrossModelPlanV1) -> OllamaIdentitySnapshot:
    """Read the local Ollama tags once for every fixed identity in the plan."""

    settings = get_settings()
    if settings.embedding_model not in {
        plan.embedding.requested_name,
        plan.embedding.resolved_name,
    }:
        raise ValueError("configured embedding model contradicts the frozen plan")
    baseline = plan.model_for_role("baseline")
    config = LiveSecurityConfig(
        llm_endpoint=settings.llm_base_url,
        chat_model=baseline.requested_name,
        structured_generation_max_attempts=settings.structured_generation_max_attempts,
    )
    with LocalOllamaOnlyBoundary(config.llm_endpoint) as boundary:
        session = requests.Session()
        session.trust_env = False
        version_payload = _get_json(session, f"{config.ollama_origin}/api/version")
        tags_payload = _get_json(session, f"{config.ollama_origin}/api/tags")
    if boundary.blocked_attempt_count:
        raise RuntimeError("Ollama identity preflight attempted external egress")
    version = version_payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("Ollama version response is invalid")
    chats = {
        component.role: resolve_ollama_model_identity(
            tags_payload,
            component.requested_name,
        )
        for component in plan.chat_models
    }
    return OllamaIdentitySnapshot(
        version=version.strip(),
        embedding=resolve_ollama_model_identity(
            tags_payload,
            plan.embedding.requested_name,
        ),
        chats=chats,
    )


def admit_existing_component(
    target: Path,
    *,
    plan: CrossModelPlanV1,
    plan_sha256: str,
    component: CrossModelModelPlan,
    git_provenance: Mapping[str, object],
    context: ComponentContext,
    runtime: OllamaIdentitySnapshot,
    execution: ExecutionInvariantSnapshot,
) -> LiveExecutionOutcome:
    """Verify an existing component against all current frozen bindings."""

    manifest = verify_live_security_run(target)
    if not isinstance(manifest, LiveSecurityRunManifestV3):
        raise ValueError("existing component is not a complete V3 live run")
    valid_observation_state = (
        manifest.status == "COMPLETED WITH OBSERVATIONS"
        and manifest.observation.protocol_complete
    ) or (
        manifest.status == "FAILED"
        and not manifest.observation.protocol_complete
    )
    if (
        manifest.run_id != component.run_id
        or manifest.split != plan.split
        or not valid_observation_state
    ):
        raise ValueError("existing component has contradictory run binding")
    experiment = manifest.experiment
    if (
        experiment.plan_id != plan.experiment_id
        or experiment.plan_sha256 != plan_sha256
        or experiment.model_role != component.role
        or experiment.only_changed_variable != plan.only_changed_variable
    ):
        raise ValueError("existing component has contradictory plan binding")
    if _model_dump(manifest.git) != dict(git_provenance):
        raise ValueError("existing component has contradictory Git binding")
    _validate_data_binding(manifest, plan, context)
    _validate_guard_binding(manifest, context)
    _validate_model_binding(manifest, plan, component, runtime)
    _validate_execution_invariants(manifest, execution)
    return LiveExecutionOutcome(output_dir=Path(target), manifest=manifest)


def run_component(
    args: argparse.Namespace,
    *,
    plan: CrossModelPlanV1,
    plan_sha256: str,
    component: CrossModelModelPlan,
    git_provenance: Mapping[str, object],
    context: ComponentContext,
    runtime: OllamaIdentitySnapshot,
    execution: ExecutionInvariantSnapshot,
) -> ComponentRun:
    output_root = _validated_lexical_directory(Path(args.out_dir), "output root")
    index_root = _validated_lexical_directory(Path(args.index_root), "index root")
    target = output_root / component.run_id
    index_target = index_root / component.run_id
    _validate_child_target(output_root, target, "component output")
    _validate_child_target(index_root, index_target, "component index")
    _reject_frozen_formal_d7_path(output_root, "output root")
    _reject_frozen_formal_d7_path(target, "component output")
    _reject_frozen_formal_d7_path(index_root, "index root")
    _reject_frozen_formal_d7_path(index_target, "component index")
    output_root = output_root.resolve()
    index_root = index_root.resolve()
    target = target.resolve()
    if target.parent != output_root:
        raise ValueError("planned component output resolves outside output root")
    if target.exists():
        outcome = admit_existing_component(
            target,
            plan=plan,
            plan_sha256=plan_sha256,
            component=component,
            git_provenance=git_provenance,
            context=context,
            runtime=runtime,
            execution=execution,
        )
        failed = outcome.manifest.status == "FAILED"
        return ComponentRun(
            role=component.role,
            reused=not failed,
            admission_kind=(
                "admitted_failed_evidence"
                if failed
                else "reused_completed_component"
            ),
            outcome=outcome,
        )

    request_args = argparse.Namespace(
        split=plan.split,
        run_id=component.run_id,
        data_root=DEFAULT_DATA_ROOT,
        out_dir=output_root,
        index_root=index_root,
    )
    binding = CrossModelExperimentBinding(
        plan_id=plan.experiment_id,
        plan_sha256=plan_sha256,
        model_role=component.role,
        only_changed_variable=plan.only_changed_variable,
    )
    request = LiveExecutionRequest(
        args=request_args,
        chat_model=component.requested_name,
        expected_chat_digest=component.digest,
        experiment=binding,
        evaluator_path="scripts/eval_indirect_injection_cross_model.py",
        canonical_argv=_canonical_argv(args),
    )
    outcome = execute_live_security_run(request)
    if _validated_lexical_path(outcome.output_dir, "returned component output") != target:
        raise ValueError("new component returned a contradictory output path")
    post_runtime = fetch_ollama_identities(plan)
    _assert_ollama_identity_snapshot_stable(
        runtime,
        post_runtime,
        scope="component execution",
    )
    _validate_runtime_identities(plan, post_runtime)
    return ComponentRun(
        role=component.role,
        reused=False,
        admission_kind="new_execution",
        outcome=admit_existing_component(
            target,
            plan=plan,
            plan_sha256=plan_sha256,
            component=component,
            git_provenance=git_provenance,
            context=context,
            runtime=post_runtime,
            execution=execution,
        ),
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.plan = _validated_canonical_plan_path(Path(args.plan))
    with _evaluation_lock(_configured_ollama_origin()):
        return _main_locked(args)


def _main_locked(args: argparse.Namespace) -> int:
    plan, plan_sha256 = load_cross_model_plan(args.plan)
    _validate_plan_execution_targets(plan)
    _validate_execution_paths(args, plan)
    _preflight_execution_state(args, plan, plan_sha256)
    git_provenance = _git_provenance(BASE_DIR)
    _require_clean_git_provenance(git_provenance)
    context = _load_component_context(plan)
    component_paths = {
        component.role: Path(args.out_dir) / component.run_id
        for component in plan.chat_models
    }
    matrix_target = Path(args.matrix_out_dir) / plan.matrix_run_id
    if _lexical_exists(matrix_target):
        current_static = _capture_current_effective_static_binding(plan, args)
        manifest = validate_current_cross_model_bindings(
            matrix_target,
            plan_path=Path(args.plan),
            component_runs=component_paths,
            code_root=BASE_DIR,
            current_git=git_provenance,
            current_effective_static=current_static,
        )
        _assert_git_provenance_stable(git_provenance, _git_provenance(BASE_DIR))
        print(
            json.dumps(
                {
                    "matrix_run_id": manifest.matrix_run_id,
                    "decision": manifest.decision,
                    "reused": True,
                    "output_path": str(matrix_target),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return _decision_exit_code(manifest.decision)

    runtime = fetch_ollama_identities(plan)
    _validate_runtime_identities(plan, runtime)
    execution = _capture_execution_invariants(plan, runtime, args)
    current_static = _effective_static_binding_from_execution(plan, execution)

    components: list[ComponentRun] = []
    for component in plan.chat_models:
        _assert_git_provenance_stable(git_provenance, _git_provenance(BASE_DIR))
        components.append(run_component(
            args,
            plan=plan,
            plan_sha256=plan_sha256,
            component=component,
            git_provenance=git_provenance,
            context=context,
            runtime=runtime,
            execution=execution,
        ))
        _assert_git_provenance_stable(git_provenance, _git_provenance(BASE_DIR))
    _assert_git_provenance_stable(git_provenance, _git_provenance(BASE_DIR))
    component_paths = {
        component.role: component.outcome.output_dir
        for component in components
    }
    comparison = compare_verified_runs(
        component_paths["baseline"],
        component_paths["replication"],
        plan=plan,
        plan_sha256=plan_sha256,
        dataset=context.data.dataset,
    )
    _assert_git_provenance_stable(git_provenance, _git_provenance(BASE_DIR))
    matrix_path = publish_cross_model_run(
        Path(args.matrix_out_dir),
        comparison,
        plan_path=Path(args.plan),
        component_runs=component_paths,
        commands=subprocess.list2cmdline(list(_canonical_argv(args))) + "\n",
        forbidden_texts=_forbidden_fixture_texts(context.data),
        code_root=BASE_DIR,
        current_git=git_provenance,
        current_effective_static=current_static,
    )
    matrix_manifest = validate_current_cross_model_bindings(
        matrix_path,
        plan_path=Path(args.plan),
        component_runs=component_paths,
        code_root=BASE_DIR,
        current_git=git_provenance,
        current_effective_static=current_static,
    )
    _assert_git_provenance_stable(git_provenance, _git_provenance(BASE_DIR))
    for component in components:
        manifest = component.outcome.manifest
        print(
            json.dumps(
                {
                    "run_id": manifest.run_id,
                    "role": component.role,
                    "reused": component.reused,
                    "admission_kind": component.admission_kind,
                    "status": manifest.status,
                    "protocol_complete": manifest.observation.protocol_complete,
                    "output_path": str(component.outcome.output_dir),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    print(
        json.dumps(
            {
                "matrix_run_id": matrix_manifest.matrix_run_id,
                "decision": matrix_manifest.decision,
                "reused": False,
                "output_path": str(matrix_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return _decision_exit_code(matrix_manifest.decision)


def _load_component_context(plan: CrossModelPlanV1) -> ComponentContext:
    bundle = load_security_bundle(DEFAULT_DATA_ROOT, plan.split)
    if (
        bundle.dataset.case_count != plan.expected_case_count
        or bundle.dataset.case_count * 2 != plan.expected_arm_event_count_per_model
    ):
        raise ValueError("frozen plan contradicts the loaded security data")
    return ComponentContext(
        data=bundle,
        r1_hashes=verify_r1_frozen_hashes(BASE_DIR),
        guard_sha256=_sha256(BASE_DIR / _GUARD_RULESET_PATH),
    )


def _capture_execution_invariants(
    plan: CrossModelPlanV1,
    runtime: OllamaIdentitySnapshot,
    args: argparse.Namespace,
) -> ExecutionInvariantSnapshot:
    settings = get_settings()
    baseline = plan.model_for_role("baseline")
    config = LiveSecurityConfig(
        llm_endpoint=settings.llm_base_url,
        chat_model=baseline.requested_name,
        structured_generation_max_attempts=settings.structured_generation_max_attempts,
    )
    canonical_endpoint = f"{config.ollama_origin}/v1"
    if config.llm_endpoint != canonical_endpoint:
        raise ValueError("cross-model execution requires the canonical Ollama /v1 endpoint")
    installed = _installed_dependency_snapshot()
    requirements = BASE_DIR / "requirements.txt"
    return ExecutionInvariantSnapshot(
        llm_endpoint=config.llm_endpoint,
        ollama_origin=config.ollama_origin,
        structured_generation_max_attempts=config.structured_generation_max_attempts,
        model_request_timeout_seconds=settings.model_request_timeout_seconds,
        model_max_attempts=settings.model_max_attempts,
        model_retry_backoff_ms=settings.model_retry_backoff_ms,
        ollama_version=runtime.version,
        python_version=platform.python_version(),
        platform=platform.platform(),
        dependency_snapshot_path="requirements.txt",
        dependency_snapshot_sha256=_sha256(requirements),
        installed_snapshot_sha256=str(installed["installed_snapshot_sha256"]),
        installed_package_count=int(installed["installed_package_count"]),
        production_active_index=production_active_index_reference(
            settings.v2_indexes_dir
        ),
        top_k=config.top_k,
        candidate_k=config.candidate_k,
        max_search_calls=config.max_search_calls,
        max_open_calls=config.max_open_calls,
        max_steps=config.max_steps,
        max_context_chars=config.max_context_chars,
        evaluator_path="scripts/eval_indirect_injection_cross_model.py",
        evaluator_sha256=_sha256(
            BASE_DIR / "scripts" / "eval_indirect_injection_cross_model.py"
        ),
        canonical_argv=_canonical_argv(args),
    )


def _capture_current_effective_static_binding(
    plan: CrossModelPlanV1,
    args: argparse.Namespace,
) -> dict[str, object]:
    no_identity_lookup = OllamaIdentitySnapshot(
        version="NOT_QUERIED_STATIC_ADMISSION",
        embedding=None,  # type: ignore[arg-type]
        chats={},
    )
    execution = _capture_execution_invariants(plan, no_identity_lookup, args)
    return _effective_static_binding_from_execution(plan, execution)


def _effective_static_binding_from_execution(
    plan: CrossModelPlanV1,
    execution: ExecutionInvariantSnapshot,
) -> dict[str, object]:
    return {
        "environment": {
            "ollama_endpoint": execution.ollama_origin,
            "python_version": execution.python_version,
            "platform": execution.platform,
            "dependency_snapshot_path": execution.dependency_snapshot_path,
            "dependency_snapshot_sha256": execution.dependency_snapshot_sha256,
            "installed_snapshot_sha256": execution.installed_snapshot_sha256,
            "installed_package_count": execution.installed_package_count,
        },
        "embedding": {
            "requested_name": plan.embedding.requested_name,
            "resolved_name": plan.embedding.resolved_name,
            "digest": plan.embedding.digest,
        },
        "model_protocol": {
            "evidence_model": "NOT_USED_D7_LIVE_PAIRED",
            "temperature": 0.0,
            "structured_output_variant": "generation-v2-json-schema",
            "think": False,
            "max_attempts": execution.structured_generation_max_attempts,
        },
        "transport": {
            "model_request_timeout_seconds": (
                execution.model_request_timeout_seconds
            ),
            "model_max_attempts": execution.model_max_attempts,
            "model_retry_backoff_ms": execution.model_retry_backoff_ms,
        },
        "retrieval": {
            "production_active_index": execution.production_active_index.model_dump(
                mode="json"
            ),
            "chunking": "post-parser-security-fixture-projection-v1",
            "top_k": execution.top_k,
            "candidate_k": execution.candidate_k,
            "max_search_calls": execution.max_search_calls,
            "max_open_calls": execution.max_open_calls,
            "max_steps": execution.max_steps,
            "max_context_chars": execution.max_context_chars,
        },
        "evaluator": {
            "path": execution.evaluator_path,
            "sha256": execution.evaluator_sha256,
            "argv": execution.canonical_argv,
        },
    }


def _validate_plan_execution_targets(plan: CrossModelPlanV1) -> None:
    if any(component.run_id == FROZEN_FORMAL_D7_RUN_ID for component in plan.chat_models):
        raise ValueError("the frozen formal D7 run ID cannot be rerun")


def _validate_runtime_identities(
    plan: CrossModelPlanV1,
    runtime: OllamaIdentitySnapshot,
) -> None:
    embedding = runtime.embedding
    if (
        embedding.requested_name,
        embedding.resolved_name,
        embedding.digest,
    ) != (
        plan.embedding.requested_name,
        plan.embedding.resolved_name,
        plan.embedding.digest,
    ) or "embedding" not in embedding.capabilities:
        raise ValueError("Ollama identities contradict the frozen embedding plan")
    for component in plan.chat_models:
        chat = runtime.chats.get(component.role)
        if chat is None:
            raise ValueError("Ollama identities are missing a planned chat model")
        if (
            chat.requested_name,
            chat.resolved_name,
            chat.digest,
            chat.family,
            chat.parameter_size,
        ) != (
            component.requested_name,
            component.resolved_name,
            component.digest,
            component.family,
            component.parameter_size,
        ) or "completion" not in chat.capabilities:
            raise ValueError("Ollama identities contradict the frozen chat plan")


def _require_clean_git_provenance(git_provenance: Mapping[str, object]) -> None:
    if (
        git_provenance.get("dirty") is not False
        or git_provenance.get("status_entry_count") != 0
        or git_provenance.get("dirty_state_sha256") != CLEAN_GIT_STATE_SHA256
    ):
        raise ValueError(
            "cross-model execution requires one exact clean Git snapshot"
        )


def _assert_ollama_identity_snapshot_stable(
    before: OllamaIdentitySnapshot,
    after: OllamaIdentitySnapshot,
    *,
    scope: str,
) -> None:
    if before != after:
        raise ValueError(f"Ollama model/runtime identity changed during {scope}")


def _validate_data_binding(
    manifest: LiveSecurityRunManifestV3,
    plan: CrossModelPlanV1,
    context: ComponentContext,
) -> None:
    data = manifest.data
    expected = context.data.dataset
    if (
        data.dataset_path != _safe_display_path(context.data.dataset_path, BASE_DIR)
        or data.dataset_sha256 != context.data.dataset_sha256
        or data.fixture_manifest_path
        != _safe_display_path(context.data.fixture_manifest_path, BASE_DIR)
        or data.fixture_manifest_sha256 != context.data.fixture_manifest_sha256
        or data.dataset_case_count != expected.case_count
        or data.dataset_case_count != plan.expected_case_count
        or data.attack_case_count != expected.attack_case_count
        or data.benign_case_count != expected.benign_case_count
        or _normalized_mapping(data.r1_frozen_hashes)
        != _normalized_mapping(context.r1_hashes)
    ):
        raise ValueError("existing component has contradictory data binding")


def _validate_guard_binding(
    manifest: LiveSecurityRunManifestV3,
    context: ComponentContext,
) -> None:
    guard = manifest.guard
    if (
        guard.detector_version != DETECTOR_VERSION
        or guard.ruleset_path != _GUARD_RULESET_PATH
        or guard.ruleset_sha256 != context.guard_sha256
        or guard.max_scan_chars != MAX_SCAN_CHARS
        or guard.max_normalized_chars != MAX_NORMALIZED_CHARS
        or guard.max_decoded_views != MAX_DECODED_VIEWS
    ):
        raise ValueError("existing component has contradictory Guard binding")


def _validate_model_binding(
    manifest: LiveSecurityRunManifestV3,
    plan: CrossModelPlanV1,
    component: CrossModelModelPlan,
    runtime: OllamaIdentitySnapshot,
) -> None:
    validate_v3_cross_model_plan_binding(
        manifest.experiment,
        requested_chat_model=component.requested_name,
        expected_chat_digest=component.digest,
        embedding=manifest.models.embedding,
        chat=manifest.models.chat,
    )
    if (
        manifest.models.embedding != runtime.embedding
        or manifest.models.chat != runtime.chats.get(component.role)
    ):
        raise ValueError("existing component has contradictory model binding")
    _validate_runtime_identities(plan, runtime)


def _validate_execution_invariants(
    manifest: LiveSecurityRunManifestV3,
    execution: ExecutionInvariantSnapshot,
) -> None:
    environment = manifest.environment
    models = manifest.models
    retrieval = manifest.retrieval
    if (
        execution.llm_endpoint != f"{execution.ollama_origin}/v1"
        or environment.ollama_endpoint != execution.ollama_origin
        or environment.ollama_version != execution.ollama_version
        or environment.python_version != execution.python_version
        or environment.platform != execution.platform
        or environment.dependency_snapshot_path
        != execution.dependency_snapshot_path
        or environment.dependency_snapshot_sha256
        != execution.dependency_snapshot_sha256
        or environment.installed_snapshot_sha256
        != execution.installed_snapshot_sha256
        or environment.installed_package_count
        != execution.installed_package_count
        or models.evidence_model != "NOT_USED_D7_LIVE_PAIRED"
        or models.temperature != 0.0
        or models.structured_output_variant != "generation-v2-json-schema"
        or models.think is not False
        or models.max_attempts != execution.structured_generation_max_attempts
        or manifest.transport.model_request_timeout_seconds
        != execution.model_request_timeout_seconds
        or manifest.transport.model_max_attempts != execution.model_max_attempts
        or manifest.transport.model_retry_backoff_ms
        != execution.model_retry_backoff_ms
        or retrieval.production_active_index != execution.production_active_index
        or retrieval.top_k != execution.top_k
        or retrieval.candidate_k != execution.candidate_k
        or retrieval.max_search_calls != execution.max_search_calls
        or retrieval.max_open_calls != execution.max_open_calls
        or retrieval.max_steps != execution.max_steps
        or retrieval.max_context_chars != execution.max_context_chars
        or manifest.evaluator.path != execution.evaluator_path
        or manifest.evaluator.sha256 != execution.evaluator_sha256
        or manifest.evaluator.argv != execution.canonical_argv
    ):
        raise ValueError("existing component has contradictory execution invariant")


def _validate_execution_paths(
    args: argparse.Namespace,
    plan: CrossModelPlanV1,
) -> None:
    output_root = _validated_lexical_directory(Path(args.out_dir), "output root")
    index_root = _validated_lexical_directory(Path(args.index_root), "index root")
    matrix_root = _validated_lexical_directory(
        Path(args.matrix_out_dir),
        "matrix output root",
    )
    args.out_dir = output_root
    args.index_root = index_root
    args.matrix_out_dir = matrix_root

    targets = [
        ("output root", output_root),
        ("index root", index_root),
        ("matrix output root", matrix_root),
        ("matrix output", matrix_root / plan.matrix_run_id),
    ]
    for component in plan.chat_models:
        output_target = output_root / component.run_id
        index_target = index_root / component.run_id
        _validate_child_target(output_root, output_target, "component output")
        _validate_child_target(index_root, index_target, "component index")
        targets.extend(
            (
                ("component output", output_target),
                ("component index", index_target),
            )
        )
    matrix_target = matrix_root / plan.matrix_run_id
    _validate_child_target(matrix_root, matrix_target, "matrix output")
    for label, path in targets:
        _reject_frozen_formal_d7_path(path, label)

    final_targets = [
        ("matrix output", matrix_target),
        *(
            ("component output", output_root / component.run_id)
            for component in plan.chat_models
        ),
        *(
            ("component index", index_root / component.run_id)
            for component in plan.chat_models
        ),
    ]
    _validate_final_target_topology(final_targets)


def _validated_canonical_plan_path(path: Path) -> Path:
    supplied = _absolute_lexical(path)
    canonical = _absolute_lexical(DEFAULT_PLAN_PATH)
    _validate_lexical_chain(supplied, "cross-model plan")
    _validate_lexical_chain(canonical, "canonical cross-model plan")
    try:
        observed = supplied.lstat()
        canonical_observed = canonical.lstat()
    except OSError as exc:
        raise ValueError("cross-model plan must be the canonical checked-in plan") from exc
    if (
        _is_redirecting_path(observed)
        or _is_redirecting_path(canonical_observed)
        or not stat.S_ISREG(observed.st_mode)
        or not stat.S_ISREG(canonical_observed.st_mode)
        or supplied.resolve() != canonical.resolve()
    ):
        raise ValueError("cross-model plan must be the canonical checked-in plan")
    return canonical.resolve()


def _preflight_execution_state(
    args: argparse.Namespace,
    plan: CrossModelPlanV1,
    plan_sha256: str,
) -> None:
    output_root = Path(args.out_dir)
    index_root = Path(args.index_root)
    matrix_root = Path(args.matrix_out_dir)
    _reject_matching_staging_entries(
        matrix_root,
        f".{plan.matrix_run_id}.staging-",
        "matrix output",
    )
    for component in plan.chat_models:
        output_target = output_root / component.run_id
        index_target = index_root / component.run_id
        _reject_matching_staging_entries(
            output_root,
            f".{component.run_id}.staging-",
            f"{component.role} component output",
        )
        output_exists = _lexical_exists(output_target)
        index_exists = _lexical_exists(index_target)
        if not output_exists:
            if index_exists:
                raise ValueError(
                    "orphan auxiliary index detected before model activity; "
                    "the immutable run ID is non-resumable and requires a "
                    "reviewed plan with new run IDs"
                )
            continue
        try:
            manifest = verify_live_security_run(output_target)
        except (OSError, ValueError) as exc:
            raise ValueError(
                f"partial or invalid {component.role} component output: {exc}"
            ) from exc
        if not isinstance(manifest, LiveSecurityRunManifestV3):
            raise ValueError(
                f"{component.role} component is not a structurally valid V3 package"
            )
        experiment = manifest.experiment
        if (
            manifest.run_id != component.run_id
            or manifest.split != plan.split
            or experiment.plan_id != plan.experiment_id
            or experiment.plan_sha256 != plan_sha256
            or experiment.model_role != component.role
            or experiment.only_changed_variable != plan.only_changed_variable
        ):
            raise ValueError(
                f"{component.role} component has contradictory frozen-plan binding"
            )


def _reject_matching_staging_entries(
    root: Path,
    prefix: str,
    label: str,
) -> None:
    if not _lexical_exists(root):
        return
    try:
        matches = sorted(
            child.name for child in root.iterdir() if child.name.startswith(prefix)
        )
    except OSError as exc:
        raise ValueError(f"{label} staging state cannot be inspected") from exc
    if matches:
        raise ValueError(
            f"stale staging state exists for {label}: {matches[0]}"
        )


def _validate_final_target_topology(
    targets: list[tuple[str, Path]],
) -> None:
    resolved = [(label, path.resolve()) for label, path in targets]
    for index, (left_label, left) in enumerate(resolved):
        for right_label, right in resolved[index + 1 :]:
            if _same_or_nested(left, right) or _same_or_nested(right, left):
                raise ValueError(
                    "planned final targets overlap or are nested: "
                    f"{left_label}={left} and {right_label}={right}"
                )


def _same_or_nested(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _validated_lexical_directory(path: Path, label: str) -> Path:
    absolute = _absolute_lexical(path)
    _validate_lexical_chain(absolute, label)
    if _lexical_exists(absolute):
        observed = absolute.lstat()
        if not stat.S_ISDIR(observed.st_mode):
            raise ValueError(f"{label} must be a directory")
    return absolute


def _validate_child_target(root: Path, target: Path, label: str) -> None:
    if target.parent != root:
        raise ValueError(f"{label} resolves outside its root")
    _validate_lexical_chain(target, label)
    if _lexical_exists(target) and not stat.S_ISDIR(target.lstat().st_mode):
        raise ValueError(f"{label} must be a directory")
    if target.resolve().parent != root.resolve():
        raise ValueError(f"{label} resolves outside its root")


def _validated_lexical_path(path: Path, label: str) -> Path:
    absolute = _absolute_lexical(path)
    _validate_lexical_chain(absolute, label)
    return absolute.resolve()


def _absolute_lexical(path: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else Path.cwd() / candidate


def _validate_lexical_chain(path: Path, label: str) -> None:
    chain: list[Path] = []
    current = path
    while True:
        chain.append(current)
        if current.parent == current:
            break
        current = current.parent
    missing = False
    for candidate in reversed(chain):
        try:
            observed = candidate.lstat()
        except FileNotFoundError:
            missing = True
            continue
        except OSError as exc:
            raise ValueError(f"{label} cannot be inspected") from exc
        if missing:
            raise ValueError(f"{label} changed during lexical validation")
        if _is_redirecting_path(observed):
            raise ValueError(f"{label} cannot be a symlink or redirecting reparse point")
        if candidate != path and not stat.S_ISDIR(observed.st_mode):
            raise ValueError(f"{label} has a non-directory path component")


def _lexical_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ValueError(f"path cannot be inspected: {path}") from exc
    return True


def _is_redirecting_path(value: object) -> bool:
    return stat.S_ISLNK(value.st_mode) or bool(
        getattr(value, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
    )


def _reject_frozen_formal_d7_path(path: Path, label: str) -> None:
    frozen = DEFAULT_OUT_DIR / FROZEN_FORMAL_D7_RUN_ID
    try:
        _absolute_lexical(path).resolve().relative_to(frozen.resolve())
    except ValueError:
        return
    raise ValueError(f"{label} cannot be inside the frozen formal D7 directory")


def _canonical_argv(args: argparse.Namespace) -> tuple[str, ...]:
    return (
        "python",
        "-m",
        "scripts.eval_indirect_injection_cross_model",
        "--plan",
        _safe_display_path(Path(args.plan).resolve(), BASE_DIR),
        "--out-dir",
        _safe_display_path(Path(args.out_dir).resolve(), BASE_DIR),
        "--index-root",
        _safe_display_path(Path(args.index_root).resolve(), BASE_DIR),
        "--matrix-out-dir",
        _safe_display_path(Path(args.matrix_out_dir).resolve(), BASE_DIR),
    )


def _decision_exit_code(decision: str) -> int:
    if decision in {"CONSISTENT_OBSERVATION", "DIVERGENT_OBSERVATION"}:
        return 0
    if decision == "INCONCLUSIVE":
        return 1
    raise ValueError(f"unsupported cross-model decision: {decision}")


def _model_dump(value: object) -> object:
    model_dump = getattr(value, "model_dump", None)
    return model_dump(mode="python") if callable(model_dump) else value


def _normalized_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return {key: _model_dump(item) for key, item in value.items()}


if __name__ == "__main__":
    raise SystemExit(main())
