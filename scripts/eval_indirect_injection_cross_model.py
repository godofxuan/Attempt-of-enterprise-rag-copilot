from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
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
    CrossModelModelPlan,
    CrossModelPlanV1,
    load_cross_model_plan,
)
from app.evaluation.indirect_injection_dataset import (
    LoadedSecurityBundle,
    load_security_bundle,
)
from app.evaluation.indirect_injection_live_runner import (
    LiveSecurityConfig,
    LocalOllamaOnlyBoundary,
)
from app.evaluation.indirect_injection_live_writer import (
    CrossModelExperimentBinding,
    LiveSecurityRunManifestV3,
    OllamaModelIdentity,
    resolve_ollama_model_identity,
    validate_v3_cross_model_plan_binding,
    verify_live_security_run,
)
from scripts.eval_indirect_injection import (
    _assert_git_provenance_stable,
    _git_provenance,
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
)


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PLAN_PATH = (
    BASE_DIR / "data" / "v2" / "evaluation" / "r2_s4_cross_model_matrix_v1.json"
)
DEFAULT_OUT_DIR = BASE_DIR / "security_runs"
DEFAULT_INDEX_ROOT = DEFAULT_OUT_DIR / ".d7_indexes"
DEFAULT_MATRIX_OUT_DIR = DEFAULT_OUT_DIR / "cross_model_matrices"
_GUARD_RULESET_PATH = "app/security/retrieved_content.py"


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
class ComponentRun:
    role: str
    reused: bool
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
) -> LiveExecutionOutcome:
    """Verify an existing component against all current frozen bindings."""

    manifest = verify_live_security_run(target)
    if not isinstance(manifest, LiveSecurityRunManifestV3):
        raise ValueError("existing component is not a complete V3 live run")
    if (
        manifest.run_id != component.run_id
        or manifest.split != plan.split
        or manifest.status != "COMPLETED WITH OBSERVATIONS"
        or not manifest.observation.protocol_complete
    ):
        raise ValueError("existing component has incomplete or contradictory run binding")
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
) -> ComponentRun:
    output_root = Path(args.out_dir).resolve()
    target = (output_root / component.run_id).resolve()
    if target.parent != output_root:
        raise ValueError("planned component output resolves outside output root")
    if target.exists():
        return ComponentRun(
            role=component.role,
            reused=True,
            outcome=admit_existing_component(
                target,
                plan=plan,
                plan_sha256=plan_sha256,
                component=component,
                git_provenance=git_provenance,
                context=context,
                runtime=runtime,
            ),
        )

    request_args = argparse.Namespace(
        split=plan.split,
        run_id=component.run_id,
        data_root=DEFAULT_DATA_ROOT,
        out_dir=output_root,
        index_root=Path(args.index_root).resolve(),
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
    return ComponentRun(
        role=component.role,
        reused=False,
        outcome=execute_live_security_run(request),
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plan, plan_sha256 = load_cross_model_plan(Path(args.plan))
    _validate_plan_execution_targets(plan)
    git_provenance = _git_provenance(BASE_DIR)
    if git_provenance.get("dirty"):
        raise ValueError("cross-model execution requires one clean Git snapshot")
    matrix_target = (Path(args.matrix_out_dir).resolve() / plan.matrix_run_id).resolve()
    if matrix_target.parent != Path(args.matrix_out_dir).resolve():
        raise ValueError("matrix output resolves outside matrix output root")
    if matrix_target.exists():
        raise FileExistsError(f"matrix output already exists: {matrix_target}")

    context = _load_component_context(plan)
    runtime = fetch_ollama_identities(plan)
    _validate_runtime_identities(plan, runtime)

    components = tuple(
        run_component(
            args,
            plan=plan,
            plan_sha256=plan_sha256,
            component=component,
            git_provenance=git_provenance,
            context=context,
            runtime=runtime,
        )
        for component in plan.chat_models
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
                    "status": manifest.status,
                    "protocol_complete": manifest.observation.protocol_complete,
                    "output_path": str(component.outcome.output_dir),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return 0 if all(
        component.outcome.manifest.observation.protocol_complete
        for component in components
    ) else 1


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


def _model_dump(value: object) -> object:
    model_dump = getattr(value, "model_dump", None)
    return model_dump(mode="python") if callable(model_dump) else value


def _normalized_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return {key: _model_dump(item) for key, item in value.items()}


if __name__ == "__main__":
    raise SystemExit(main())
