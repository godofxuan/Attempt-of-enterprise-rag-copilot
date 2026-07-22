from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from app.evaluation import (
    indirect_injection_cross_model_public_verifier as trusted_verifier,
)
from app.evaluation.indirect_injection_cross_model import (
    CLEAN_GIT_STATE_SHA256,
    COMPARISON_METRIC_IDS,
)
from app.evaluation.indirect_injection_cross_model_writer import (
    VerifiedCrossModelRunSnapshot,
    _validated_cross_model_publication_root,
    load_verified_cross_model_run_snapshot,
)
from app.evaluation.indirect_injection_dataset import load_security_bundle
from app.evaluation.indirect_injection_sensitive_values import (
    collect_security_sensitive_values,
)
from app.evaluation.publication_paths import _atomic_publish_no_replace


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SECURITY_DATA_ROOT = _REPO_ROOT / "data" / "v2" / "security"
_PROMPT_FRAGMENTS = (
    "You are a grounded enterprise knowledge-base answer generator operating ",
    "Evaluator synthetic system canary: ",
)
PACKAGE_NAME = "r2_s4_cross_model"
EXPERIMENT_ID = "r2-s4-cross-model-dev-v1"
PUBLIC_CROSS_MODEL_FILES = frozenset(
    {
        "README.md",
        "manifest.json",
        "summary.json",
        "per_case_redacted.jsonl",
        "checksums.sha256",
        "verify.py",
        "verification_witness.json",
        "commands.txt",
    }
)
CHECKSUM_CONTENT_NAMES = tuple(
    sorted(PUBLIC_CROSS_MODEL_FILES - {"manifest.json", "checksums.sha256"})
)
LIMITATIONS = (
    "This is one local two-model dev observation, not a production certification.",
    "The visible dev set is regression evidence and is not an independent holdout.",
    "Only chat-model identity was intentionally varied; latency is host-specific.",
    "Integrity hashes are audit witnesses, not signatures from an external authority.",
)
COMMANDS_TEXT = (
    "python verify.py .\n"
    "python -m scripts.verify_indirect_injection_cross_model_public "
    "data/v2/public/r2_s4_cross_model\n"
)
ZERO_SHA256 = "0" * 64
_TOKEN_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
)
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|secret|password|authorization)"
    r"\b[\"']?\s*[:=]\s*[\"']?[^\s\"',;]{4,}"
)
_IDENTITY_ASSIGNMENT = re.compile(
    r"(?i)\b(?:tenant(?:_id)?|user(?:_id)?|group(?:_ids?)?)\b[\"']?\s*[:=]"
    r"\s*[\"']?[A-Za-z0-9._:-]{3,}"
)
_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/]")
_UNC_PATH = re.compile(r"(?:\\){2,}[A-Za-z0-9._$-]+[\\/]")
_POSIX_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9/])/(?:Users|home|tmp|var|etc)/[^\s\"'<>]+"
)
_PRIVATE_RUNTIME = re.compile(
    r"(?i)(?<![A-Za-z0-9_.-])(?:security_runs|cross_model_runs)(?:[\\/]|$)"
)


def export_cross_model_public(private_run: Path, output_dir: Path) -> Path:
    """Verify a private matrix, project safe fields, and publish once."""

    snapshot = load_verified_cross_model_run_snapshot(Path(private_run))
    _require_public_source_eligible(snapshot.manifest)
    snapshot.assert_unchanged()
    rows = tuple(_project_row(snapshot, row) for row in snapshot.rows)
    verifier_path = Path(trusted_verifier.__file__)
    verifier_bytes = verifier_path.read_bytes()
    files = _build_public_package_bytes(snapshot, rows, verifier_bytes)
    forbidden_values = _sensitive_values(snapshot)
    for name, payload in files.items():
        _assert_public_bytes_safe(name, payload, forbidden_values)
    snapshot.assert_unchanged()

    requested = Path(output_dir)
    if not requested.name or requested.name in {".", ".."}:
        raise ValueError("public output directory requires a final name")
    parent = _validated_cross_model_publication_root(
        requested.parent,
        "public cross-model output parent",
    )
    target = parent / requested.name
    if target.parent != parent:
        raise ValueError("public output resolves outside its parent")
    try:
        target.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise FileExistsError("public output cannot be inspected") from exc
    else:
        raise FileExistsError(f"public output already exists: {target}")

    stage = Path(
        tempfile.mkdtemp(prefix=f".{requested.name}.staging-", dir=parent)
    ).resolve()
    try:
        for name, payload in files.items():
            (stage / name).write_bytes(payload)
        trusted_verifier.verify_public_package(stage)
        snapshot.assert_unchanged()
        _atomic_publish_no_replace(stage, target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target.resolve()


def _require_public_source_eligible(manifest: Any) -> None:
    components = manifest.components
    if (
        manifest.decision == "INCONCLUSIVE"
        or set(components) != {"baseline", "replication"}
        or any(
            not components[role].protocol_complete
            for role in ("baseline", "replication")
        )
    ):
        raise ValueError(
            "public evidence source is not eligible: private observation is "
            "inconclusive or has an incomplete component"
        )


def _project_row(
    snapshot: VerifiedCrossModelRunSnapshot,
    row: object,
) -> dict[str, object]:
    role = row.model_role
    return {
        "schema_version": "indirect_injection_cross_model_public_case_v1",
        "row_ordinal": row.row_ordinal,
        "case_ordinal": row.case_ordinal,
        "case_class": {
            "label": row.case_class.label,
            "category": row.case_class.category,
            "variant_id": row.case_class.variant_id,
            "utility_bucket": row.case_class.utility_bucket,
        },
        "model_role": role,
        "model_digest": row.model_digest,
        "arm_order": row.arm_order,
        "component_protocol_complete": snapshot.manifest.components[
            role
        ].protocol_complete,
        "non_chat_invariants_match": not snapshot.manifest.invariant_mismatches,
        "off": _project_arm(row.off),
        "on": _project_arm(row.on),
    }


def _project_arm(arm: object) -> dict[str, object]:
    return {
        "guard_mode": arm.guard_mode,
        "retrieval_completed": arm.retrieval_completed,
        "candidate_count": arm.candidate_count,
        "attack_unit_count": arm.attack_unit_count,
        "attack_unit_reached_guard_count": arm.attack_unit_reached_guard_count,
        "attack_unit_quarantined_count": arm.attack_unit_quarantined_count,
        "benign_unit_count": arm.benign_unit_count,
        "benign_unit_quarantined_count": arm.benign_unit_quarantined_count,
        "model_call_count": arm.model_call_count,
        "successful_model_call_count": arm.successful_model_call_count,
        "model_error_codes": list(arm.model_error_codes),
        "model_latency_ms": arm.model_latency_ms,
        "allowed_local_model_http_request_count": (
            arm.allowed_local_model_http_request_count
        ),
        "blocked_egress_attempt_count": arm.blocked_egress_attempt_count,
        "user_boundary_attack_success": arm.user_boundary_attack_success,
        "raw_follow_signal": arm.raw_follow_signal,
        "model_context_exposure": arm.model_context_exposure,
        "raw_document_canary_exposure": arm.raw_document_canary_exposure,
        "raw_system_canary_exposure": arm.raw_system_canary_exposure,
        "raw_trace_canary_exposure": arm.raw_trace_canary_exposure,
        "task_applicable": arm.task_applicable,
        "task_success": arm.task_success,
        "security_filtered_correct": arm.security_filtered_correct,
        "generation_system_error": arm.generation_system_error,
    }


def _project_metric(metric: object) -> dict[str, object]:
    return {
        "kind": metric.kind,
        "numerator": metric.numerator,
        "denominator": metric.denominator,
        "rate": metric.rate,
        "value": metric.value,
    }


def _project_diagnostic(diagnostic: object) -> dict[str, object]:
    return {
        "diagnostic_id": diagnostic.diagnostic_id,
        "release_pass": diagnostic.release_pass,
        "on_attack_success_zero_of_24": (
            diagnostic.on_attack_success_zero_of_24
        ),
        "on_conditional_quarantine_15_of_15": (
            diagnostic.on_conditional_quarantine_15_of_15
        ),
        "on_benign_quarantine_zero_of_32": (
            diagnostic.on_benign_quarantine_zero_of_32
        ),
        "model_errors_zero": diagnostic.model_errors_zero,
        "blocked_egress_zero": diagnostic.blocked_egress_zero,
        "passed": diagnostic.passed,
    }


def _project_model_summary(summary: object) -> dict[str, object]:
    return {
        "model_role": summary.model_role,
        "model_digest": summary.model_digest,
        "case_count": summary.case_count,
        "protocol_complete": summary.protocol_complete,
        "non_release_safety_diagnostic": _project_diagnostic(
            summary.non_release_safety_diagnostic
        ),
        "metrics": {
            metric_id: _project_metric(summary.metrics[metric_id])
            for metric_id in COMPARISON_METRIC_IDS
        },
    }


def _project_verified_private_evidence(
    snapshot: VerifiedCrossModelRunSnapshot,
) -> dict[str, object]:
    source = snapshot.summary
    if source.decision != snapshot.manifest.decision:
        raise ValueError("verified private summary contradicts its manifest")
    return {
        "summaries": {
            role: _project_model_summary(source.summaries[role])
            for role in ("baseline", "replication")
        },
        "deltas": {
            metric_id: {
                "baseline": _project_metric(source.deltas[metric_id].baseline),
                "replication": _project_metric(
                    source.deltas[metric_id].replication
                ),
                "delta": source.deltas[metric_id].delta,
            }
            for metric_id in COMPARISON_METRIC_IDS
        },
        "decision": source.decision,
        "decision_reasons": list(source.decision_reasons),
    }


def _project_common_git(
    snapshot: VerifiedCrossModelRunSnapshot,
) -> dict[str, object]:
    source = snapshot.manifest.git
    projected = {
        "head": source.head,
        "branch": source.branch,
        "dirty": source.dirty,
        "status_entry_count": source.status_entry_count,
        "dirty_state_sha256": source.dirty_state_sha256,
    }
    if (
        projected["dirty"] is not False
        or projected["status_entry_count"] != 0
        or projected["dirty_state_sha256"] != CLEAN_GIT_STATE_SHA256
    ):
        raise ValueError("public evidence requires exact clean Git provenance")
    return projected


def _build_public_package_bytes(
    snapshot: VerifiedCrossModelRunSnapshot,
    rows: tuple[dict[str, object], ...],
    verifier_bytes: bytes,
) -> dict[str, bytes]:
    model_digests = {
        role: snapshot.manifest.components[role].model_digest
        for role in ("baseline", "replication")
    }
    private_evidence = _project_verified_private_evidence(snapshot)
    common_git = _project_common_git(snapshot)
    summary = {
        "schema_version": "indirect_injection_cross_model_public_summary_v1",
        "package_name": PACKAGE_NAME,
        "experiment_id": EXPERIMENT_ID,
        "row_count": 72,
        "model_digests": model_digests,
        "common_git": common_git,
        "summaries": private_evidence["summaries"],
        "deltas": private_evidence["deltas"],
        "decision": private_evidence["decision"],
        "decision_reasons": private_evidence["decision_reasons"],
        "evidence_status": "OBSERVATION_ONLY",
        "limitations": list(LIMITATIONS),
    }
    summary_bytes = _json_bytes(summary)
    rows_bytes = b"".join(_json_line(row) for row in rows)
    commands_bytes = COMMANDS_TEXT.encode("utf-8")
    component_hashes = {
        role: snapshot.manifest.components[role].manifest_sha256
        for role in ("baseline", "replication")
    }
    manifest: dict[str, Any] = {
        "schema_version": "indirect_injection_cross_model_public_manifest_v1",
        "producer": "enterprise_agentic_rag_v2",
        "package_name": PACKAGE_NAME,
        "experiment_id": EXPERIMENT_ID,
        "split": "dev",
        "only_changed_variable": "chat_model_identity",
        "plan_sha256": snapshot.manifest.plan_sha256,
        "row_count": 72,
        "model_digests": model_digests,
        "common_git": common_git,
        "private_matrix_manifest_sha256": snapshot.manifest_sha256,
        "component_manifest_sha256": component_hashes,
        "decision": private_evidence["decision"],
        "evidence_status": "OBSERVATION_ONLY",
        "verifier_sha256": _sha256_bytes(verifier_bytes),
        "artifacts": {},
        "limitations": list(LIMITATIONS),
    }
    readme_bytes = _build_public_readme(manifest).encode("utf-8")
    files: dict[str, bytes] = {
        "README.md": readme_bytes,
        "summary.json": summary_bytes,
        "per_case_redacted.jsonl": rows_bytes,
        "verify.py": verifier_bytes,
        "commands.txt": commands_bytes,
    }
    for name in sorted(PUBLIC_CROSS_MODEL_FILES):
        payload = files.get(name)
        manifest["artifacts"][name] = {
            "path": name,
            "bytes": len(payload) if payload is not None else 1,
            "sha256": _sha256_bytes(payload) if payload is not None else "0" * 64,
            "hash_mode": (
                "canonical_manifest_self_normalized_v1"
                if name == "manifest.json"
                else "actual_sha256"
            ),
        }
    manifest["artifacts"]["manifest.json"]["sha256"] = (
        _manifest_normalized_sha256(manifest)
    )
    witness = {
        "schema_version": "indirect_injection_cross_model_public_witness_v1",
        "package_name": PACKAGE_NAME,
        "plan_sha256": snapshot.manifest.plan_sha256,
        "private_matrix_manifest_sha256": snapshot.manifest_sha256,
        "component_manifest_sha256": component_hashes,
        "common_git": common_git,
        "manifest_normalized_sha256": manifest["artifacts"]["manifest.json"][
            "sha256"
        ],
        "readme_sha256": _sha256_bytes(readme_bytes),
        "summary_sha256": _sha256_bytes(summary_bytes),
        "rows_sha256": _sha256_bytes(rows_bytes),
        "commands_sha256": _sha256_bytes(commands_bytes),
        "verifier_sha256": _sha256_bytes(verifier_bytes),
        "row_count": 72,
        "model_digests": model_digests,
        "decision": private_evidence["decision"],
        "evidence_status": "OBSERVATION_ONLY",
    }
    witness_bytes = _json_bytes(witness)
    files["verification_witness.json"] = witness_bytes
    manifest["artifacts"]["verification_witness.json"].update(
        {"bytes": len(witness_bytes), "sha256": _sha256_bytes(witness_bytes)}
    )
    checksum_bytes = _checksum_bytes(files)
    files["checksums.sha256"] = checksum_bytes
    manifest["artifacts"]["checksums.sha256"].update(
        {"bytes": len(checksum_bytes), "sha256": _sha256_bytes(checksum_bytes)}
    )
    manifest["artifacts"]["manifest.json"]["sha256"] = (
        _manifest_normalized_sha256(manifest)
    )
    for _ in range(8):
        manifest_bytes = _json_bytes(manifest)
        if manifest["artifacts"]["manifest.json"]["bytes"] == len(manifest_bytes):
            files["manifest.json"] = manifest_bytes
            break
        manifest["artifacts"]["manifest.json"]["bytes"] = len(manifest_bytes)
    else:
        raise RuntimeError("public manifest size did not converge")
    if set(files) != set(PUBLIC_CROSS_MODEL_FILES):
        raise RuntimeError("public package builder produced the wrong artifact set")
    return files


def _build_public_readme(manifest: dict[str, object]) -> str:
    digests = manifest["model_digests"]
    common_git = manifest["common_git"]
    branch = common_git["branch"] if common_git["branch"] is not None else "DETACHED"
    return (
        "# R2-S4 Cross-Model Observation Evidence\n\n"
        "This eight-file package contains content-free, independently recomputable "
        "dev evidence.\n\n"
        "- Evidence status: `OBSERVATION_ONLY`\n"
        f"- Decision: `{manifest['decision']}`\n"
        f"- Baseline model digest: `{digests['baseline']}`\n"
        f"- Replication model digest: `{digests['replication']}`\n"
        f"- Source Git HEAD: `{common_git['head']}`\n"
        f"- Source Git branch: `{branch}`\n"
        "- Source Git state: `clean` (0 status entries; dirty-state SHA-256 "
        f"`{common_git['dirty_state_sha256']}`)\n"
        f"- Private matrix manifest witness: "
        f"`{manifest['private_matrix_manifest_sha256']}`\n\n"
        "Verify from this directory with:\n\n"
        "```text\n"
        "python verify.py .\n"
        "```\n\n"
        "The verifier uses only the Python standard library and recomputes model "
        "summaries, deltas, and the observation decision from 72 redacted rows. "
        "Public rows intentionally omit private input, nonce, and candidate-order "
        "hashes; cross-role checks align by opaque ordinal, public case class, "
        "arm order, and public-safe arm fields only. "
        "This package is not a production certification or release gate.\n"
    )


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _json_line(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _manifest_normalized_sha256(manifest: dict[str, object]) -> str:
    normalized = json.loads(json.dumps(manifest, allow_nan=False))
    evidence = normalized["artifacts"]
    for name in (
        "manifest.json",
        "verification_witness.json",
        "checksums.sha256",
    ):
        evidence[name]["bytes"] = 0
        evidence[name]["sha256"] = ZERO_SHA256
    return _sha256_bytes(_json_bytes(normalized))


def _checksum_bytes(files: dict[str, bytes]) -> bytes:
    return "".join(
        f"{_sha256_bytes(files[name])}  {name}\n"
        for name in CHECKSUM_CONTENT_NAMES
    ).encode("utf-8")


def _sensitive_values(snapshot: VerifiedCrossModelRunSnapshot) -> tuple[str, ...]:
    bundles = tuple(
        load_security_bundle(_SECURITY_DATA_ROOT, split)
        for split in ("dev", "test")
    )
    corpus = collect_security_sensitive_values(
        datasets=(bundle.dataset for bundle in bundles),
        fixture_manifests=(bundle.fixture_manifest for bundle in bundles),
    )
    values = set(corpus.values(include_case_ids=True))
    for bundle in bundles:
        for case in bundle.dataset.cases:
            values.add(
                "R2SYS_"
                + hashlib.sha256(case.case_id.encode("utf-8"))
                .hexdigest()[:24]
                .upper()
            )
    values.update(_PROMPT_FRAGMENTS)
    values.add(snapshot.manifest.matrix_run_id)
    values.update(
        snapshot.manifest.components[role].run_id
        for role in ("baseline", "replication")
    )
    public_provenance_keys = _public_provenance_keys(snapshot)
    values.update(
        value.strip()
        for value in os.environ.values()
        if value
        and len(value.strip()) >= 8
        and _privacy_key(value.strip()) not in public_provenance_keys
    )
    for key in ("USERNAME", "USER"):
        value = os.environ.get(key)
        if value and len(value) >= 3:
            values.add(value)
    values.add(str(Path.home()))
    return tuple(sorted(value for value in values if value))


def _public_provenance_keys(
    snapshot: VerifiedCrossModelRunSnapshot,
) -> frozenset[str]:
    manifest = snapshot.manifest
    values = {
        manifest.git.head,
        manifest.git.dirty_state_sha256,
        manifest.plan_sha256,
        snapshot.manifest_sha256,
    }
    if manifest.git.branch is not None:
        values.add(manifest.git.branch)
    for role in ("baseline", "replication"):
        component = manifest.components[role]
        values.add(component.manifest_sha256)
        values.add(component.model_digest)
    return frozenset(_privacy_key(value) for value in values)


def _privacy_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _assert_public_bytes_safe(
    name: str,
    payload: bytes,
    forbidden_values: tuple[str, ...],
) -> None:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"public privacy scan requires UTF-8: {name}") from exc
    normalized = _privacy_key(text)
    for value in forbidden_values:
        candidate = _privacy_key(value)
        if candidate and candidate in normalized:
            raise ValueError(f"public privacy policy found forbidden content in {name}")
    if (
        any(pattern.search(text) for pattern in _TOKEN_PATTERNS)
        or _CREDENTIAL_ASSIGNMENT.search(text)
    ):
        raise ValueError(f"public credential privacy policy failed for {name}")
    if _IDENTITY_ASSIGNMENT.search(text):
        raise ValueError(f"public identity privacy policy failed for {name}")
    if (
        _WINDOWS_ABSOLUTE_PATH.search(text)
        or _UNC_PATH.search(text)
        or _POSIX_ABSOLUTE_PATH.search(text)
    ):
        raise ValueError(f"public absolute-path privacy policy failed for {name}")
    if _PRIVATE_RUNTIME.search(text):
        raise ValueError(f"public private-runtime privacy policy failed for {name}")


__all__ = ["export_cross_model_public"]
