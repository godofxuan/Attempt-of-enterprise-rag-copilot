from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
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
from app.evaluation.indirect_injection_arm_order import (
    build_counterbalanced_arm_order_plan,
)
from app.evaluation.indirect_injection_dataset import (
    LoadedSecurityBundle,
    load_security_bundle,
)
from app.evaluation.indirect_injection_live_index import (
    LiveFixtureIndexBuild,
    build_live_fixture_index,
)
from app.evaluation.indirect_injection_metric_semantics import (
    RAW_FOLLOW_SEMANTICS,
)
from app.evaluation.indirect_injection_live_runner import (
    LivePairedResultV2,
    LiveSecurityConfig,
    LocalOllamaOnlyBoundary,
    evaluate_live_paired,
)
from app.evaluation.indirect_injection_live_writer import (
    CrossModelExperimentBinding,
    LiveIndexReference,
    LiveSecurityRunManifestV2,
    LiveSecurityRunManifestV3,
    OllamaModelIdentity,
    publish_live_security_run,
    resolve_ollama_model_identity,
    validate_v3_cross_model_plan_binding,
    verify_live_security_run,
)
from app.evaluation.indirect_injection_writer import R1HashPair, validate_security_run_id
from app.indexing.store import load_index_version
from app.ollama_chat import chat_with_ollama
from app.retriever import _embed_text
from scripts.eval_indirect_injection import (
    _assert_git_provenance_stable,
    _forbidden_fixture_texts,
    _git_provenance,
    _installed_dependency_snapshot,
    _safe_display_path,
    _sha256,
    verify_r1_frozen_hashes,
)


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_ROOT = BASE_DIR / "data" / "v2" / "security"
DEFAULT_OUT_DIR = BASE_DIR / "security_runs"
DEFAULT_INDEX_ROOT = DEFAULT_OUT_DIR / ".d7_indexes"
FROZEN_FORMAL_D7_RUN_ID = "r2-s1-d7-test-20260718-01"
FROZEN_TEST_DATASET_SHA256 = (
    "062aec151d29854ffcebf6368b42fc768f7a0a5f64e1218e32fd326a441a137c"
)
FROZEN_TEST_FIXTURE_SHA256 = (
    "eea41009bd5a8eda2b0a1ff7c29e593895d917b4055e9712b1db48daa9d51c1d"
)
FROZEN_QWEN25_CHAT_DIGEST = (
    "357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b"
)
_SMOKE_RESPONSE_FORMAT = {
    "type": "object",
    "properties": {"status": {"type": "string", "enum": ["ready"]}},
    "required": ["status"],
}


@dataclass(frozen=True)
class OllamaRuntimeSnapshot:
    version: str
    embedding: OllamaModelIdentity
    chat: OllamaModelIdentity


@dataclass(frozen=True)
class ModelSmokeEvidence:
    embedding_dimension: int
    structured_chat_valid: bool
    allowed_http_request_count: int
    blocked_egress_attempt_count: int


@dataclass(frozen=True)
class LiveExecutionRequest:
    args: argparse.Namespace
    chat_model: str
    expected_chat_digest: str
    experiment: CrossModelExperimentBinding | None = None
    evaluator_path: str = "scripts/eval_indirect_injection_live.py"
    canonical_argv: tuple[str, ...] | None = None


@dataclass(frozen=True)
class LiveExecutionOutcome:
    output_dir: Path
    manifest: LiveSecurityRunManifestV2 | LiveSecurityRunManifestV3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a future explicitly local, non-CI counterbalanced paired "
            "indirect-injection evaluation. The frozen D7 run remains historical."
        )
    )
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--index-root", type=Path, default=DEFAULT_INDEX_ROOT)
    return parser


def fetch_ollama_runtime(
    config: LiveSecurityConfig,
    embedding_model: str,
) -> OllamaRuntimeSnapshot:
    with LocalOllamaOnlyBoundary(config.llm_endpoint) as boundary:
        session = requests.Session()
        session.trust_env = False
        version_payload = _get_json(
            session,
            f"{config.ollama_origin}/api/version",
        )
        tags_payload = _get_json(
            session,
            f"{config.ollama_origin}/api/tags",
        )
    if boundary.blocked_attempt_count:
        raise RuntimeError("Ollama identity preflight attempted external egress")
    version = version_payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("Ollama version response is invalid")
    return OllamaRuntimeSnapshot(
        version=version.strip(),
        embedding=resolve_ollama_model_identity(tags_payload, embedding_model),
        chat=resolve_ollama_model_identity(tags_payload, config.chat_model),
    )


def run_model_smoke(
    config: LiveSecurityConfig,
    embedding_model: str,
    runtime: OllamaRuntimeSnapshot,
) -> ModelSmokeEvidence:
    with LocalOllamaOnlyBoundary(config.llm_endpoint) as boundary:
        vector = _embed_text(
            embedding_model,
            "D7 local embedding readiness probe; no enterprise content.",
        )
        raw = chat_with_ollama(
            config.chat_model,
            [
                {
                    "role": "system",
                    "content": "Return only the requested readiness JSON object.",
                },
                {"role": "user", "content": "Report status ready."},
            ],
            response_format=_SMOKE_RESPONSE_FORMAT,
            think=False,
        )
    if boundary.blocked_attempt_count:
        raise RuntimeError("model smoke test attempted external egress")
    if not vector:
        raise ValueError("embedding smoke test returned an empty vector")
    if (
        runtime.embedding.embedding_length is not None
        and len(vector) != runtime.embedding.embedding_length
    ):
        raise ValueError("embedding smoke dimension differs from Ollama identity")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("structured chat smoke returned invalid JSON") from exc
    structured_chat_valid = payload == {"status": "ready"}
    if not structured_chat_valid:
        raise ValueError("structured chat smoke returned the wrong shape")
    return ModelSmokeEvidence(
        embedding_dimension=len(vector),
        structured_chat_valid=True,
        allowed_http_request_count=boundary.allowed_http_request_count,
        blocked_egress_attempt_count=boundary.blocked_attempt_count,
    )


def production_active_index_reference(index_root: Path) -> LiveIndexReference:
    root = Path(index_root).resolve()
    active_path = root / "active.json"
    if not active_path.is_file():
        raise FileNotFoundError("D7 requires a production active v2 index reference")
    loaded = load_index_version(root)
    manifest = loaded.manifest
    return LiveIndexReference(
        role="production_active_reference",
        run_id=manifest.run_id,
        active_pointer_sha256=_sha256(active_path),
        manifest_sha256=loaded.manifest_sha256,
        corpus_sha256=manifest.corpus_manifest_hash,
        embedding_model=manifest.embedding.model,
        embedding_dimension=manifest.embedding.dimension,
        indexed_chunk_count=manifest.indexed_chunk_count,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    request = LiveExecutionRequest(
        args=args,
        chat_model="qwen2.5:3b",
        expected_chat_digest=FROZEN_QWEN25_CHAT_DIGEST,
        canonical_argv=_canonical_argv(args),
    )
    outcome = execute_live_security_run(request)
    manifest = outcome.manifest
    print(
        json.dumps(
            {
                "run_id": manifest.run_id,
                "split": manifest.split,
                "status": manifest.status,
                "protocol_complete": manifest.observation.protocol_complete,
                "arm_order_protocol": manifest.arm_order.protocol_id,
                "off_then_on_case_count": manifest.arm_order.off_then_on_count,
                "on_then_off_case_count": manifest.arm_order.on_then_off_count,
                "output_dir": str(outcome.output_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if manifest.observation.protocol_complete else 1


def execute_live_security_run(
    request: LiveExecutionRequest,
) -> LiveExecutionOutcome:
    args = request.args
    _validate_execution_request(request)
    validate_security_run_id(args.run_id)
    if args.run_id == FROZEN_FORMAL_D7_RUN_ID:
        raise ValueError("the frozen formal D7 run ID cannot be rerun")
    output_root = args.out_dir.resolve()
    output_target = (output_root / args.run_id).resolve()
    if output_target.parent != output_root:
        raise ValueError("run ID resolves outside output root")
    if output_target.exists():
        raise FileExistsError(
            f"live security output run already exists: {output_target}"
        )
    frozen_formal_dir = (
        DEFAULT_OUT_DIR / FROZEN_FORMAL_D7_RUN_ID
    ).resolve()
    _reject_frozen_formal_run_path(
        output_root,
        frozen_formal_dir=frozen_formal_dir,
        label="output root",
    )
    _reject_frozen_formal_run_path(
        output_target,
        frozen_formal_dir=frozen_formal_dir,
        label="output target",
    )
    _reject_frozen_formal_run_path(
        args.index_root.resolve(),
        frozen_formal_dir=frozen_formal_dir,
        label="index root",
    )

    # Frozen-data checks intentionally precede every Ollama or index-build call.
    r1_hashes = verify_r1_frozen_hashes(BASE_DIR)
    bundle = load_security_bundle(args.data_root, args.split)
    _validate_official_test_cohort(bundle, split=args.split)
    arm_order = build_counterbalanced_arm_order_plan(
        case.case_id for case in bundle.dataset.cases
    )
    settings = get_settings()
    config = LiveSecurityConfig(
        llm_endpoint=settings.llm_base_url,
        chat_model=request.chat_model,
        structured_generation_max_attempts=(
            settings.structured_generation_max_attempts
        ),
    )
    if request.experiment is None:
        _validate_frozen_models(settings.embedding_model, settings.chat_model)
        if settings.chat_model != request.chat_model:
            raise ValueError("D7 frozen protocol chat model changed internally")
    else:
        _validate_frozen_embedding_model(settings.embedding_model)

    started_at = datetime.now(timezone.utc)
    git_provenance = _git_provenance(BASE_DIR)
    installed_dependencies = _installed_dependency_snapshot()
    if request.experiment is not None:
        runtime = fetch_ollama_runtime(config, settings.embedding_model)
        validate_v3_cross_model_plan_binding(
            request.experiment,
            embedding=runtime.embedding,
            chat=runtime.chat,
        )
        production_index = production_active_index_reference(
            settings.v2_indexes_dir
        )
    else:
        production_index = production_active_index_reference(
            settings.v2_indexes_dir
        )
        runtime = fetch_ollama_runtime(config, settings.embedding_model)
        if runtime.chat.digest != request.expected_chat_digest:
            raise ValueError(
                "resolved Ollama chat model digest does not match expected "
                "chat model digest"
            )
    smoke = run_model_smoke(config, settings.embedding_model, runtime)

    security_index_root = (args.index_root.resolve() / args.run_id).resolve()
    if security_index_root.parent != args.index_root.resolve():
        raise ValueError("run ID resolves outside security index root")
    index_run_id = "d7-live-" + hashlib.sha256(
        f"{args.split}|{args.run_id}".encode("utf-8")
    ).hexdigest()[:20]
    with LocalOllamaOnlyBoundary(config.llm_endpoint) as index_egress:
        built = build_live_fixture_index(
            dataset=bundle.dataset,
            fixtures=bundle.fixture_manifest,
            root=security_index_root,
            run_id=index_run_id,
            fixture_sha256=bundle.fixture_manifest_sha256,
            embedding_model=settings.embedding_model,
            embed_text=lambda text: _embed_text(settings.embedding_model, text),
        )
    if index_egress.blocked_attempt_count:
        raise RuntimeError("security index build attempted external egress")

    result = evaluate_live_paired(
        dataset=bundle.dataset,
        fixtures=bundle.fixture_manifest,
        snapshot=built.snapshot,
        embed_text=lambda text: _embed_text(settings.embedding_model, text),
        chat_fn=chat_with_ollama,
        config=config,
        arm_order=arm_order,
    )
    if not isinstance(result, LivePairedResultV2):
        raise RuntimeError("future live evaluation did not produce a v2 result")
    _assert_git_provenance_stable(
        git_provenance,
        _git_provenance(BASE_DIR),
    )
    completed_at = datetime.now(timezone.utc)
    canonical_argv = request.canonical_argv or _canonical_argv(args)
    security_index = _security_index_reference(built)
    manifest = _build_manifest(
        args=args,
        bundle=bundle,
        result=result,
        config=config,
        runtime=runtime,
        production_index=production_index,
        security_index=security_index,
        r1_hashes=r1_hashes,
        git_provenance=git_provenance,
        installed_dependencies=installed_dependencies,
        canonical_argv=canonical_argv,
        started_at=started_at,
        completed_at=completed_at,
        index_embedding_call_count=built.embedding_call_count,
        experiment=request.experiment,
        evaluator_path=request.evaluator_path,
    )
    forbidden_texts = _forbidden_fixture_texts(bundle)
    output = publish_live_security_run(
        output_root,
        manifest,
        result,
        paired_evidence=_paired_evidence(result),
        commands=" ".join(canonical_argv) + "\n",
        test_output=_preflight_evidence(
            runtime,
            smoke,
            production_index,
            security_index,
            built,
            index_egress.allowed_http_request_count,
        ),
        forbidden_texts=forbidden_texts,
    )
    verified = verify_live_security_run(output)
    if not isinstance(
        verified,
        (LiveSecurityRunManifestV3, LiveSecurityRunManifestV2),
    ):
        raise RuntimeError("published live run did not verify as a v2/v3 manifest")
    return LiveExecutionOutcome(output_dir=output, manifest=verified)


def _validate_execution_request(request: LiveExecutionRequest) -> None:
    if (
        len(request.expected_chat_digest) != 64
        or not set(request.expected_chat_digest) <= set("0123456789abcdef")
    ):
        raise ValueError("expected chat model digest must be lowercase SHA-256")
    if not request.chat_model:
        raise ValueError("chat model is required")
    if request.experiment is not None and request.args.split != "dev":
        raise ValueError("cross-model live execution requires the dev split")
    if request.canonical_argv is not None and not request.canonical_argv:
        raise ValueError("canonical argv cannot be empty")
    if request.experiment is not None:
        _repository_file(request.evaluator_path, "evaluator path")
        validate_v3_cross_model_plan_binding(
            request.experiment,
            requested_chat_model=request.chat_model,
            expected_chat_digest=request.expected_chat_digest,
        )


def _build_manifest(
    *,
    args: argparse.Namespace,
    bundle,
    result: LivePairedResultV2,
    config: LiveSecurityConfig,
    runtime: OllamaRuntimeSnapshot,
    production_index: LiveIndexReference,
    security_index: LiveIndexReference,
    r1_hashes: dict[str, R1HashPair],
    git_provenance: dict[str, object],
    installed_dependencies: dict[str, object],
    canonical_argv: tuple[str, ...],
    started_at: datetime,
    completed_at: datetime,
    index_embedding_call_count: int,
    experiment: CrossModelExperimentBinding | None,
    evaluator_path: str,
) -> LiveSecurityRunManifestV2 | LiveSecurityRunManifestV3:
    ruleset = BASE_DIR / "app" / "security" / "retrieved_content.py"
    is_cross_model = experiment is not None
    manifest_type = (
        LiveSecurityRunManifestV3 if is_cross_model else LiveSecurityRunManifestV2
    )
    manifest_evaluator_path = (
        evaluator_path
        if is_cross_model
        else "app/evaluation/indirect_injection_live_runner.py"
    )
    evaluator = _repository_file(manifest_evaluator_path, "evaluator path")
    requirements = BASE_DIR / "requirements.txt"
    exit_code = 0 if result.protocol_complete else 1
    payload = {
            "schema_version": (
                "indirect_injection_live_security_run_manifest_v3"
                if is_cross_model
                else "indirect_injection_live_security_run_manifest_v2"
            ),
            "producer": "enterprise_agentic_rag_v2",
            "run_id": args.run_id,
            "suite": "retrieved_content_indirect_injection",
            "split": args.split,
            "mode": (
                "local_live_paired_counterbalanced_cross_model_dev"
                if is_cross_model
                else "local_live_paired_counterbalanced"
            ),
            "started_at_utc": started_at,
            "completed_at_utc": completed_at,
            "status": result.status,
            "git": git_provenance,
            "environment": {
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "dependency_snapshot_path": "requirements.txt",
                "dependency_snapshot_sha256": _sha256(requirements),
                "installed_snapshot_sha256": installed_dependencies[
                    "installed_snapshot_sha256"
                ],
                "installed_package_count": installed_dependencies[
                    "installed_package_count"
                ],
                "ollama_version": runtime.version,
                "ollama_endpoint": config.ollama_origin,
            },
            "models": {
                "embedding": runtime.embedding,
                "chat": runtime.chat,
                "evidence_model": "NOT_USED_D7_LIVE_PAIRED",
                "temperature": 0.0,
                "structured_output_variant": "generation-v2-json-schema",
                "think": False,
                "max_attempts": config.structured_generation_max_attempts,
            },
            "guard": {
                "detector_version": DETECTOR_VERSION,
                "ruleset_path": "app/security/retrieved_content.py",
                "ruleset_sha256": _sha256(ruleset),
                "max_scan_chars": MAX_SCAN_CHARS,
                "max_normalized_chars": MAX_NORMALIZED_CHARS,
                "max_decoded_views": MAX_DECODED_VIEWS,
            },
            "data": {
                "dataset_path": _safe_display_path(bundle.dataset_path, BASE_DIR),
                "dataset_sha256": bundle.dataset_sha256,
                "dataset_case_count": bundle.dataset.case_count,
                "fixture_manifest_path": _safe_display_path(
                    bundle.fixture_manifest_path,
                    BASE_DIR,
                ),
                "fixture_manifest_sha256": bundle.fixture_manifest_sha256,
                "attack_case_count": bundle.dataset.attack_case_count,
                "benign_case_count": bundle.dataset.benign_case_count,
                "r1_frozen_hashes": {
                    path: pair.model_dump(mode="json")
                    for path, pair in r1_hashes.items()
                },
            },
            "evaluator": {
                "path": manifest_evaluator_path,
                "sha256": _sha256(evaluator),
                "argv": canonical_argv,
                "exit_code": exit_code,
            },
            "retrieval": {
                "production_active_index": production_index,
                "security_fixture_index": security_index,
                "chunking": "post-parser-security-fixture-projection-v1",
                "top_k": config.top_k,
                "candidate_k": config.candidate_k,
                "max_search_calls": config.max_search_calls,
                "max_open_calls": config.max_open_calls,
                "max_steps": config.max_steps,
                "max_context_chars": config.max_context_chars,
                "index_embedding_call_count": index_embedding_call_count,
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
            "arm_order": result.arm_order,
            "artifacts": {},
            "limitations": (
                "This is one local model run, not a universal model-safety claim.",
                "The frozen test set is visible regression data, not unseen data.",
                "Guard OFF model resistance is not software-boundary success.",
                "The production active index is provenance only; synthetic attacks use the isolated security index.",
                "Hash-rank counterbalancing reduces one order confounder but does not remove all temporal or model-state effects.",
            ),
        }
    if experiment is not None:
        payload["experiment"] = experiment
    return manifest_type.model_validate(payload)


def _security_index_reference(built: LiveFixtureIndexBuild) -> LiveIndexReference:
    return LiveIndexReference(
        role="security_fixture_runtime",
        run_id=built.manifest.run_id,
        active_pointer_sha256=_sha256(built.index_root / "active.json"),
        manifest_sha256=built.manifest_sha256,
        corpus_sha256=built.manifest.corpus_manifest_hash,
        embedding_model=built.manifest.embedding.model,
        embedding_dimension=built.manifest.embedding.dimension,
        indexed_chunk_count=built.manifest.indexed_chunk_count,
    )


def _paired_evidence(result: LivePairedResultV2) -> str:
    off_security = result.security.guard_off.summary
    on_security = result.security.guard_on.summary
    off_live = result.guard_off_summary
    on_live = result.guard_on_summary
    return (
        "# R2-S1 Future Local Live Counterbalanced Paired Evidence\n\n"
        f"Status: {result.status}\n\n"
        "These counts describe this exact local model run. They are not a "
        "universal model-safety or release claim.\n\n"
        f"Metric semantics: {RAW_FOLLOW_SEMANTICS.semantics_id}\n\n"
        f"{RAW_FOLLOW_SEMANTICS.definition}\n\n"
        f"Arm-order protocol: {result.arm_order.protocol_id}\n"
        f"- OFF then ON cases: {result.arm_order.off_then_on_count}\n"
        f"- ON then OFF cases: {result.arm_order.on_then_off_count}\n"
        f"- Guard OFF model-context exposure: "
        f"{off_security.model_context_exposure.numerator}/"
        f"{off_security.model_context_exposure.denominator}\n"
        f"- Guard OFF raw canary or forbidden-action follow: "
        f"{off_live.raw_canary_or_forbidden_action_follow.numerator}/"
        f"{off_live.raw_canary_or_forbidden_action_follow.denominator}\n"
        f"- Guard OFF user-boundary attack success: "
        f"{off_security.attack_success.numerator}/"
        f"{off_security.attack_success.denominator}\n"
        f"- Guard ON model-context exposure: "
        f"{on_security.model_context_exposure.numerator}/"
        f"{on_security.model_context_exposure.denominator}\n"
        f"- Guard ON raw canary or forbidden-action follow: "
        f"{on_live.raw_canary_or_forbidden_action_follow.numerator}/"
        f"{on_live.raw_canary_or_forbidden_action_follow.denominator}\n"
        f"- Guard ON user-boundary attack success: "
        f"{on_security.attack_success.numerator}/"
        f"{on_security.attack_success.denominator}\n"
        f"- Pair input consistent: {str(result.pair_input_consistent).lower()}\n"
    )


def _preflight_evidence(
    runtime: OllamaRuntimeSnapshot,
    smoke: ModelSmokeEvidence,
    production_index: LiveIndexReference,
    security_index: LiveIndexReference,
    built: LiveFixtureIndexBuild,
    index_allowed_request_count: int,
) -> str:
    return (
        "D7 local preflight completed.\n"
        f"ollama_version={runtime.version}\n"
        f"embedding_model={runtime.embedding.resolved_name}\n"
        f"embedding_digest={runtime.embedding.digest}\n"
        f"chat_model={runtime.chat.resolved_name}\n"
        f"chat_digest={runtime.chat.digest}\n"
        f"smoke_embedding_dimension={smoke.embedding_dimension}\n"
        f"smoke_structured_chat_valid={str(smoke.structured_chat_valid).lower()}\n"
        f"smoke_allowed_http_requests={smoke.allowed_http_request_count}\n"
        f"production_index_run_id={production_index.run_id}\n"
        f"production_index_manifest_sha256={production_index.manifest_sha256}\n"
        f"security_index_run_id={security_index.run_id}\n"
        f"security_index_manifest_sha256={security_index.manifest_sha256}\n"
        f"security_index_embedding_calls={built.embedding_call_count}\n"
        f"security_index_allowed_http_requests={index_allowed_request_count}\n"
        "blocked_external_egress_attempts=0\n"
    )


def _canonical_argv(args: argparse.Namespace) -> tuple[str, ...]:
    return (
        "python",
        "-m",
        "scripts.eval_indirect_injection_live",
        "--split",
        args.split,
        "--run-id",
        args.run_id,
        "--data-root",
        _safe_display_path(args.data_root.resolve(), BASE_DIR),
        "--out-dir",
        _safe_display_path(args.out_dir.resolve(), BASE_DIR),
        "--index-root",
        _safe_display_path(args.index_root.resolve(), BASE_DIR),
    )


def _validate_frozen_models(embedding_model: str, chat_model: str) -> None:
    _validate_frozen_embedding_model(embedding_model)
    if chat_model != "qwen2.5:3b":
        raise ValueError("D7 frozen protocol requires qwen2.5:3b")


def _validate_frozen_embedding_model(embedding_model: str) -> None:
    if embedding_model not in {"bge-m3", "bge-m3:latest"}:
        raise ValueError("D7 frozen protocol requires BGE-M3")


def _repository_file(relative_path: str, label: str) -> Path:
    if "\\" in relative_path:
        raise ValueError(f"{label} must use repository-relative POSIX form")
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be repository-relative")
    resolved = (BASE_DIR / path).resolve()
    try:
        resolved.relative_to(BASE_DIR.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} resolves outside the repository") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} does not exist: {relative_path}")
    return resolved


def _reject_frozen_formal_run_path(
    path: Path,
    *,
    frozen_formal_dir: Path,
    label: str,
) -> None:
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(frozen_formal_dir)
    except ValueError:
        return
    raise ValueError(f"{label} cannot be inside the frozen formal D7 directory")


def _validate_official_test_cohort(
    bundle: LoadedSecurityBundle,
    *,
    split: str,
) -> None:
    if split != "test":
        return
    if (
        bundle.dataset_sha256 != FROZEN_TEST_DATASET_SHA256
        or bundle.fixture_manifest_sha256 != FROZEN_TEST_FIXTURE_SHA256
    ):
        raise ValueError(
            "test split must use the official frozen test cohort hashes"
        )


def _get_json(session: requests.Session, url: str) -> Mapping[str, object]:
    response = session.get(url, timeout=10)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise ValueError("Ollama preflight response must be a JSON object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
