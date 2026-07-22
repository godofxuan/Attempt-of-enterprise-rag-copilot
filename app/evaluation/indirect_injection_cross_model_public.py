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

from app.evaluation import indirect_injection_cross_model_public_verifier as verifier
from app.evaluation.indirect_injection_cross_model_public_verifier import (
    CHECKSUM_CONTENT_NAMES,
    COMMANDS_TEXT,
    LIMITATIONS,
    PACKAGE_NAME,
    PUBLIC_CROSS_MODEL_FILES,
    _json_bytes,
    _json_line,
    _manifest_normalized_sha256,
    _sha256_bytes,
    build_public_readme,
    recompute_public_evidence,
    verify_public_package,
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
_TOKEN_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
)
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|secret|password|authorization)"
    r"\b\s*[:=]\s*[\"']?[^\s\"',;]{4,}"
)
_IDENTITY_ASSIGNMENT = re.compile(
    r"(?i)\b(?:tenant(?:_id)?|user(?:_id)?|group(?:_ids?)?)\b\s*[:=]"
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
    snapshot.assert_unchanged()
    rows = tuple(_project_row(snapshot, row) for row in snapshot.rows)
    verifier_path = Path(verifier.__file__)
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
        verify_public_package(stage)
        snapshot.assert_unchanged()
        _atomic_publish_no_replace(stage, target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target.resolve()


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
        "input_fingerprint": row.input_fingerprint,
        "nonce_fingerprint": row.nonce_fingerprint,
        "candidate_order_sha256": row.candidate_order_sha256,
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


def _build_public_package_bytes(
    snapshot: VerifiedCrossModelRunSnapshot,
    rows: tuple[dict[str, object], ...],
    verifier_bytes: bytes,
) -> dict[str, bytes]:
    model_digests = {
        role: snapshot.manifest.components[role].model_digest
        for role in ("baseline", "replication")
    }
    recomputed = recompute_public_evidence(rows, model_digests)
    if recomputed["decision"] != snapshot.manifest.decision:
        raise ValueError("public row decision contradicts the verified private matrix")
    summary = {
        "schema_version": "indirect_injection_cross_model_public_summary_v1",
        "package_name": verifier.PACKAGE_NAME,
        "experiment_id": verifier.EXPERIMENT_ID,
        "row_count": 72,
        "model_digests": model_digests,
        "summaries": recomputed["summaries"],
        "deltas": recomputed["deltas"],
        "decision": recomputed["decision"],
        "decision_reasons": recomputed["decision_reasons"],
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
        "experiment_id": verifier.EXPERIMENT_ID,
        "split": "dev",
        "only_changed_variable": "chat_model_identity",
        "plan_sha256": snapshot.manifest.plan_sha256,
        "row_count": 72,
        "model_digests": model_digests,
        "private_matrix_manifest_sha256": snapshot.manifest_sha256,
        "component_manifest_sha256": component_hashes,
        "decision": recomputed["decision"],
        "evidence_status": "OBSERVATION_ONLY",
        "verifier_sha256": _sha256_bytes(verifier_bytes),
        "artifacts": {},
        "limitations": list(LIMITATIONS),
    }
    readme_bytes = build_public_readme(manifest).encode("utf-8")
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
        "decision": recomputed["decision"],
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
    values.update(
        value
        for value in os.environ.values()
        if value and len(value.strip()) >= 8
    )
    for key in ("USERNAME", "USER"):
        value = os.environ.get(key)
        if value and len(value) >= 3:
            values.add(value)
    values.add(str(Path.home()))
    return tuple(sorted(value for value in values if value))


def _assert_public_bytes_safe(
    name: str,
    payload: bytes,
    forbidden_values: tuple[str, ...],
) -> None:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"public privacy scan requires UTF-8: {name}") from exc
    normalized = unicodedata.normalize("NFKC", text).casefold()
    for value in forbidden_values:
        candidate = unicodedata.normalize("NFKC", value).casefold()
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
