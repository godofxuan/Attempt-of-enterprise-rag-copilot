from __future__ import annotations

import base64
import binascii
import errno
import hashlib
import json
import os
import re
import secrets
import stat
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import IDENTITY_CLOCK_SKEW_MAX_SECONDS
from app.security.identity import (
    IdentityConfigurationError,
    read_private_file_snapshot,
    validate_private_path_ancestors,
)
from app.security.private_fs import (
    PrivatePathError,
    capture_private_directory_identity,
    harden_private_directory,
    hold_private_directory,
    private_directory_identity_is_current,
    private_directory_permissions_are_secure,
    replace_private_file,
    sync_directory,
    validate_private_directory_permissions,
)


_MANIFEST_SCHEMA = "demo-identity-keyring-v3"
_PREVIOUS_MANIFEST_SCHEMA = "demo-identity-keyring-v2"
_LEGACY_MANIFEST_SCHEMA = "demo-identity-keyring-v1"
_BUNDLE_SCHEMA = "persona-token-bundle-v1"
_OPERATION_SCHEMA = "demo-identity-operation-v3"
_MANIFEST_FILE = "identity_manifest.json"
_OPERATION_FILE = ".identity-operation.json"
_LOCK_FILE = ".identity.lock"
_PERSONA_FILE = "persona_tokens.json"
_OPERATOR_FILE = "operator_token.txt"
_LOAD_USER_FILE = "load_user_token.txt"
_JWKS_FILE = "jwks.json"
_HMAC_FILE = "feedback_actor_hmac.key"
_MAX_KEYRING_KEYS = 8
_MAX_RETIRED_KEY_IDS = 64
_MAX_OPERATION_BYTES = 524_288
_MIN_TOKEN_LIFETIME_SECONDS = 60
_MAX_TOKEN_LIFETIME_SECONDS = 900
_MAX_EPOCH_SECONDS = 4_102_444_800
_LOCK_TIMEOUT_SECONDS = 30.0
_LOCK_POLL_SECONDS = 0.05
_DEMO_KID_PATTERN = re.compile(r"^demo-\d{8}T\d{6}Z-[0-9a-f]{8}$")
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_RUNTIME_ARTIFACT_FILES = (
    _JWKS_FILE,
    _PERSONA_FILE,
    _OPERATOR_FILE,
    _LOAD_USER_FILE,
    _HMAC_FILE,
)
_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()
_ACTIVE_DIRECTORY = threading.local()
EMERGENCY_RETIRE_CONFIRMATION = "RETIRE_ACTIVE_TOKENS_NOW"

_PERSONAS: tuple[dict[str, object], ...] = (
    {
        "sub": "user_employee",
        "groups": ["all_employees"],
    },
    {
        "sub": "user_auditor",
        "groups": [
            "all_employees",
            "hr_confidential",
            "finance_ops",
            "security_ops",
            "customer_success",
            "procurement_ops",
            "engineering",
            "legal",
            "audit_all",
        ],
    },
    {
        "sub": "user_security",
        "groups": ["all_employees", "security_ops"],
    },
    {
        "sub": "user_engineer",
        "groups": ["all_employees", "engineering"],
    },
    {
        "sub": "user_contractor",
        "groups": ["external_contractors"],
    },
    {
        "sub": "demo-security-user",
        "groups": ["all_employees"],
    },
    {
        "sub": "load-demo-employee",
        "groups": ["all_employees"],
    },
)


@dataclass(frozen=True)
class DemoIdentityStatus:
    active_kid: str
    key_ids: tuple[str, ...]
    persona_count: int
    restart_required: bool = False
    pending_kid: str | None = None
    retirement_not_before: tuple[tuple[str, int], ...] = ()
    emergency_revocations: tuple[tuple[str, int], ...] = ()

    @property
    def emergency_revocation_count(self) -> int:
        return len(self.emergency_revocations)


@dataclass(frozen=True)
class _ActiveDirectoryBinding:
    root: Path
    descriptor: int | None
    identity: tuple[int, int]


def initialize_demo_identity(
    directory: Path,
    *,
    issuer: str,
    audience: str,
    token_lifetime_seconds: int,
    force: bool = False,
) -> DemoIdentityStatus:
    root = _prepare_directory(directory)
    _validate_lifetime(token_lifetime_seconds)
    with _identity_lock(root):
        _recover_pending_operation(root)
        manifest_path = root / _MANIFEST_FILE
        if manifest_path.exists() and not force:
            raise FileExistsError("demo identity already exists")
        old_private_files = _existing_private_files(root) if force else []
        private_key, record = _generate_key_record()
        private_bytes = _private_key_bytes(private_key)
        record["private_key_sha256"] = hashlib.sha256(private_bytes).hexdigest()
        manifest = {
            "schema_version": _MANIFEST_SCHEMA,
            "issuer": issuer,
            "audience": audience,
            "active_kid": record["kid"],
            "keys": [record],
            "retired_kids": [],
            "retire_not_before": {},
            "emergency_revocations": [],
            "artifacts": {},
        }
        runtime = _render_runtime_artifacts(
            manifest,
            private_key=private_key,
            token_lifetime_seconds=token_lifetime_seconds,
            hmac_key=secrets.token_bytes(32),
        )
        writes = _committed_writes(
            manifest,
            runtime,
            extra={str(record["private_key_file"]): private_bytes},
        )
        deletes = [
            stale.name
            for stale in old_private_files
            if stale.name != record["private_key_file"]
        ]
        _commit_operation(
            root,
            _new_operation(
                kind="init",
                subject_kid=str(record["kid"]),
                writes=writes,
                deletes=deletes,
            ),
        )
        return _status(manifest, restart_required=True)


def rotate_demo_identity(directory: Path) -> DemoIdentityStatus:
    root = _prepare_directory(directory)
    with _identity_lock(root):
        _recover_pending_operation(root)
        manifest = _load_manifest(root)
        if _pending_kid(manifest) is not None:
            raise ValueError(
                "a staged identity key must be activated or retired first"
            )
        if len(manifest["keys"]) >= _MAX_KEYRING_KEYS:
            raise ValueError("demo identity keyring is full; retire an old key first")
        private_key, record = _generate_key_record(
            excluded={str(item["kid"]) for item in manifest["keys"]}
        )
        private_bytes = _private_key_bytes(private_key)
        record["private_key_sha256"] = hashlib.sha256(private_bytes).hexdigest()
        manifest["keys"].append(record)
        runtime = _read_runtime_artifacts(root)
        runtime[_JWKS_FILE] = _json_bytes(_public_jwks(manifest))
        _commit_operation(
            root,
            _new_operation(
                kind="rotate",
                subject_kid=str(record["kid"]),
                writes=_committed_writes(
                    manifest,
                    runtime,
                    extra={str(record["private_key_file"]): private_bytes},
                ),
                deletes=[],
            ),
        )
        return _status(manifest, restart_required=True)


def activate_demo_identity(
    directory: Path,
    *,
    kid: str,
    token_lifetime_seconds: int,
    snapshot_verifier: Callable[[str, str], bool],
) -> DemoIdentityStatus:
    root = _prepare_directory(directory)
    _validate_lifetime(token_lifetime_seconds)
    if not callable(snapshot_verifier):
        raise TypeError("snapshot verifier must be callable")
    with _identity_lock(root):
        _recover_pending_operation(root)
        manifest = _load_manifest(root)
        pending_kid = _pending_kid(manifest)
        if pending_kid is None or kid != pending_kid:
            raise ValueError("identity key is not pending activation")
        private_key = _load_private_key(root, manifest, kid=kid)
        activation_time = _now_epoch()
        probe = _issue_token(
            private_key,
            kid=kid,
            issuer=str(manifest["issuer"]),
            audience=str(manifest["audience"]),
            subject="demo-activation-probe",
            groups=["all_employees"],
            roles=[],
            issued_at=activation_time,
            lifetime=60,
        )
        try:
            accepted = snapshot_verifier(probe, kid)
        except Exception:
            accepted = False
        if accepted is not True:
            raise IdentityConfigurationError(
                "staged identity key is not loaded by the API snapshot"
            )
        previous_active_kid = str(manifest["active_kid"])
        manifest["active_kid"] = kid
        manifest["retire_not_before"][previous_active_kid] = (
            activation_time
            + _MAX_TOKEN_LIFETIME_SECONDS
            + IDENTITY_CLOCK_SKEW_MAX_SECONDS
        )
        manifest["retire_not_before"].pop(kid, None)
        runtime = _render_runtime_artifacts(
            manifest,
            private_key=private_key,
            token_lifetime_seconds=token_lifetime_seconds,
            hmac_key=read_private_file_snapshot(root / _HMAC_FILE, max_bytes=256),
        )
        _commit_operation(
            root,
            _new_operation(
                kind="activate",
                subject_kid=kid,
                writes=_committed_writes(manifest, runtime),
                deletes=[],
                activation_policy={
                    "activated_at": activation_time,
                    "clock_skew_seconds": IDENTITY_CLOCK_SKEW_MAX_SECONDS,
                    "max_token_lifetime_seconds": _MAX_TOKEN_LIFETIME_SECONDS,
                    "previous_active_kid": previous_active_kid,
                },
            ),
        )
        return _status(manifest)


def retire_demo_identity_key(
    directory: Path,
    *,
    kid: str,
    emergency_revoke: bool = False,
    emergency_confirmation: str | None = None,
) -> DemoIdentityStatus:
    if not isinstance(emergency_revoke, bool):
        raise TypeError("emergency revoke must be a boolean")
    if emergency_revoke and emergency_confirmation != EMERGENCY_RETIRE_CONFIRMATION:
        raise ValueError(
            "emergency revocation requires the exact confirmation phrase"
        )
    if not emergency_revoke and emergency_confirmation is not None:
        raise ValueError(
            "emergency confirmation is only valid with emergency revocation"
        )
    root = _prepare_directory(directory)
    with _identity_lock(root):
        _recover_pending_operation(root)
        manifest = _load_manifest(root)
        if kid == manifest["active_kid"]:
            raise ValueError("the active identity key cannot be retired")
        if kid in manifest["retired_kids"]:
            return _status(manifest, restart_required=True)
        matching = [item for item in manifest["keys"] if item["kid"] == kid]
        if len(matching) != 1:
            raise ValueError("identity key was not found")
        now = _now_epoch()
        retire_not_before = manifest["retire_not_before"].get(kid)
        emergency_used = (
            isinstance(retire_not_before, int)
            and now < retire_not_before
            and emergency_revoke
        )
        if (
            isinstance(retire_not_before, int)
            and now < retire_not_before
            and not emergency_revoke
        ):
            deadline = datetime.fromtimestamp(
                retire_not_before,
                tz=timezone.utc,
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            raise ValueError(
                f"identity key overlap window remains active until {deadline}"
            )
        if len(manifest["retired_kids"]) >= _MAX_RETIRED_KEY_IDS:
            raise ValueError("demo identity retired-key history is full")
        manifest["keys"] = [
            item for item in manifest["keys"] if item["kid"] != kid
        ]
        manifest["retired_kids"].append(kid)
        manifest["retire_not_before"].pop(kid, None)
        if emergency_used:
            manifest["emergency_revocations"].append(
                {"kid": kid, "revoked_at": now}
            )
        runtime = _read_runtime_artifacts(root)
        runtime[_JWKS_FILE] = _json_bytes(_public_jwks(manifest))
        _commit_operation(
            root,
            _new_operation(
                kind="retire",
                subject_kid=kid,
                writes=_committed_writes(manifest, runtime),
                deletes=[str(matching[0]["private_key_file"])],
                retirement_authorization={
                    "mode": "emergency" if emergency_used else "scheduled",
                    "authorized_at": now,
                },
            ),
        )
        return _status(manifest, restart_required=True)


def demo_identity_status(directory: Path) -> DemoIdentityStatus:
    root = _prepare_status_directory(directory)
    with _identity_lock(root):
        recovered = _recover_pending_operation(root)
        upgraded: list[bool] = []
        manifest = _load_manifest(root, upgraded=upgraded)
        return _status(
            manifest,
            restart_required=recovered is not None or bool(upgraded),
        )


def _render_runtime_artifacts(
    manifest: dict[str, Any],
    *,
    private_key: rsa.RSAPrivateKey,
    token_lifetime_seconds: int,
    hmac_key: bytes,
) -> dict[str, bytes]:
    active_kid = str(manifest["active_kid"])
    now = _now_epoch()
    tokens = {
        str(persona["sub"]): _issue_token(
            private_key,
            kid=active_kid,
            issuer=str(manifest["issuer"]),
            audience=str(manifest["audience"]),
            subject=str(persona["sub"]),
            groups=list(persona["groups"]),
            roles=[],
            issued_at=now,
            lifetime=token_lifetime_seconds,
        )
        for persona in _PERSONAS
    }
    operator_token = _issue_token(
        private_key,
        kid=active_kid,
        issuer=str(manifest["issuer"]),
        audience=str(manifest["audience"]),
        subject="demo-operator",
        groups=["all_employees"],
        roles=["rag.operator"],
        issued_at=now,
        lifetime=token_lifetime_seconds,
    )
    return {
        _JWKS_FILE: _json_bytes(_public_jwks(manifest)),
        _PERSONA_FILE: _json_bytes(
            {"schema_version": _BUNDLE_SCHEMA, "tokens": tokens}
        ),
        _LOAD_USER_FILE: (tokens["load-demo-employee"] + "\n").encode("ascii"),
        _OPERATOR_FILE: (operator_token + "\n").encode("ascii"),
        _HMAC_FILE: hmac_key,
    }


def _generate_key_record(
    *,
    excluded: set[str] | None = None,
) -> tuple[rsa.RSAPrivateKey, dict[str, Any]]:
    excluded = excluded or set()
    while True:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        kid = f"demo-{stamp}-{secrets.token_hex(4)}"
        if kid not in excluded:
            break
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    numbers = private_key.public_key().public_numbers()
    public_jwk = {
        "alg": "RS256",
        "e": _base64url_uint(numbers.e),
        "key_ops": ["verify"],
        "kid": kid,
        "kty": "RSA",
        "n": _base64url_uint(numbers.n),
        "use": "sig",
    }
    return private_key, {
        "kid": kid,
        "private_key_file": f"private-{kid}.pem",
        "public_jwk": public_jwk,
    }


def _load_private_key(
    root: Path,
    manifest: dict[str, Any],
    *,
    kid: str,
) -> rsa.RSAPrivateKey:
    matching = [item for item in manifest["keys"] if item["kid"] == kid]
    if len(matching) != 1:
        raise IdentityConfigurationError("identity private key is unavailable")
    raw = read_private_file_snapshot(
        root / str(matching[0]["private_key_file"]),
        max_bytes=32_768,
    )
    try:
        private_key = serialization.load_pem_private_key(raw, None)
    except (TypeError, ValueError):
        raise IdentityConfigurationError(
            "identity private key is unavailable"
        ) from None
    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise IdentityConfigurationError("identity private key is unavailable")
    return private_key


def _issue_token(
    private_key: rsa.RSAPrivateKey,
    *,
    kid: str,
    issuer: str,
    audience: str,
    subject: str,
    groups: list[str],
    roles: list[str],
    issued_at: int,
    lifetime: int,
) -> str:
    return jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "sub": subject,
            "tenant_id": "starbridge-cn",
            "region": "cn",
            "groups": groups,
            "roles": roles,
            "iat": issued_at,
            "exp": issued_at + lifetime,
        },
        private_key,
        algorithm="RS256",
        headers={"alg": "RS256", "kid": kid, "typ": "at+jwt"},
    )


def _load_manifest(
    root: Path,
    *,
    upgraded: list[bool] | None = None,
) -> dict[str, Any]:
    raw = read_private_file_snapshot(root / _MANIFEST_FILE, max_bytes=131_072)
    try:
        manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise IdentityConfigurationError("demo identity manifest is invalid") from None
    if not isinstance(manifest, dict):
        raise IdentityConfigurationError("demo identity manifest is invalid")
    if manifest.get("schema_version") == _LEGACY_MANIFEST_SCHEMA:
        manifest = _upgrade_legacy_manifest(root, manifest)
    if manifest.get("schema_version") == _PREVIOUS_MANIFEST_SCHEMA:
        manifest, runtime = _upgrade_previous_manifest(root, manifest)
        _commit_operation(
            root,
            _new_operation(
                kind="upgrade",
                subject_kid=str(manifest["active_kid"]),
                writes=_committed_writes(manifest, runtime),
                deletes=[],
            ),
        )
        if upgraded is not None:
            upgraded.append(True)
    if set(manifest) != {
        "schema_version",
        "issuer",
        "audience",
        "active_kid",
        "keys",
        "retired_kids",
        "retire_not_before",
        "emergency_revocations",
        "artifacts",
    } or manifest["schema_version"] != _MANIFEST_SCHEMA:
        raise IdentityConfigurationError("demo identity manifest is invalid")
    keys = manifest["keys"]
    if not isinstance(keys, list) or not 1 <= len(keys) <= _MAX_KEYRING_KEYS:
        raise IdentityConfigurationError("demo identity manifest is invalid")
    key_ids: set[str] = set()
    for item in keys:
        if not isinstance(item, dict) or set(item) != {
            "kid",
            "private_key_file",
            "private_key_sha256",
            "public_jwk",
        }:
            raise IdentityConfigurationError("demo identity manifest is invalid")
        kid = item["kid"]
        private_key_file = item["private_key_file"]
        private_key_sha256 = item["private_key_sha256"]
        public_jwk = item["public_jwk"]
        if (
            not isinstance(kid, str)
            or not _DEMO_KID_PATTERN.fullmatch(kid)
            or not isinstance(private_key_file, str)
            or private_key_file != f"private-{kid}.pem"
            or Path(private_key_file).name != private_key_file
            or not isinstance(private_key_sha256, str)
            or not _DIGEST_PATTERN.fullmatch(private_key_sha256)
            or not isinstance(public_jwk, dict)
            or public_jwk.get("kid") != kid
        ):
            raise IdentityConfigurationError("demo identity manifest is invalid")
        if kid in key_ids:
            raise IdentityConfigurationError("demo identity manifest is invalid")
        private_bytes = read_private_file_snapshot(
            root / private_key_file,
            max_bytes=32_768,
        )
        if not secrets.compare_digest(
            hashlib.sha256(private_bytes).hexdigest(),
            private_key_sha256,
        ):
            raise IdentityConfigurationError("demo identity manifest is invalid")
        key_ids.add(kid)
    if not isinstance(manifest["active_kid"], str) or manifest[
        "active_kid"
    ] not in key_ids:
        raise IdentityConfigurationError("demo identity manifest is invalid")
    if not isinstance(manifest["issuer"], str) or not isinstance(
        manifest["audience"], str
    ):
        raise IdentityConfigurationError("demo identity manifest is invalid")
    retired = manifest["retired_kids"]
    if (
        not isinstance(retired, list)
        or len(retired) > _MAX_RETIRED_KEY_IDS
        or len(retired) != len(set(retired))
        or any(
            not isinstance(value, str) or not _DEMO_KID_PATTERN.fullmatch(value)
            for value in retired
        )
        or key_ids.intersection(retired)
    ):
        raise IdentityConfigurationError("demo identity manifest is invalid")
    _validate_retirement_metadata(
        manifest,
        key_ids,
        error_message="demo identity manifest is invalid",
    )
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != set(
        _RUNTIME_ARTIFACT_FILES
    ):
        raise IdentityConfigurationError("demo identity manifest is invalid")
    runtime = _read_runtime_artifacts(root)
    for name, payload in runtime.items():
        expected = artifacts.get(name)
        if (
            not isinstance(expected, str)
            or not _DIGEST_PATTERN.fullmatch(expected)
            or not secrets.compare_digest(hashlib.sha256(payload).hexdigest(), expected)
        ):
            raise IdentityConfigurationError("demo identity manifest is invalid")
    return manifest


def _upgrade_legacy_manifest(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if set(manifest) != {
        "schema_version",
        "issuer",
        "audience",
        "active_kid",
        "keys",
    } or not isinstance(manifest.get("keys"), list):
        raise IdentityConfigurationError("demo identity manifest is invalid")
    if (
        not isinstance(manifest.get("active_kid"), str)
        or not isinstance(manifest.get("issuer"), str)
        or not isinstance(manifest.get("audience"), str)
        or not 1 <= len(manifest["keys"]) <= _MAX_KEYRING_KEYS
    ):
        raise IdentityConfigurationError("demo identity manifest is invalid")
    upgraded_keys: list[dict[str, Any]] = []
    observed_kids: set[str] = set()
    for item in manifest["keys"]:
        if not isinstance(item, dict) or set(item) != {
            "kid",
            "private_key_file",
            "public_jwk",
        }:
            raise IdentityConfigurationError("demo identity manifest is invalid")
        kid = item.get("kid")
        private_key_file = item.get("private_key_file")
        public_jwk = item.get("public_jwk")
        if (
            not isinstance(kid, str)
            or not _DEMO_KID_PATTERN.fullmatch(kid)
            or kid in observed_kids
            or not isinstance(private_key_file, str)
            or private_key_file != f"private-{kid}.pem"
            or Path(private_key_file).name != private_key_file
            or not isinstance(public_jwk, dict)
            or public_jwk.get("kid") != kid
        ):
            raise IdentityConfigurationError("demo identity manifest is invalid")
        observed_kids.add(kid)
        private_bytes = read_private_file_snapshot(
            root / private_key_file,
            max_bytes=32_768,
        )
        upgraded_keys.append(
            {
                **item,
                "private_key_sha256": hashlib.sha256(private_bytes).hexdigest(),
            }
        )
    if manifest["active_kid"] not in observed_kids:
        raise IdentityConfigurationError("demo identity manifest is invalid")
    runtime = _read_runtime_artifacts(root)
    return {
        **manifest,
        "schema_version": _PREVIOUS_MANIFEST_SCHEMA,
        "keys": upgraded_keys,
        "retired_kids": [],
        "artifacts": {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in runtime.items()
        },
    }


def _upgrade_previous_manifest(
    root: Path,
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, bytes]]:
    if set(manifest) != {
        "schema_version",
        "issuer",
        "audience",
        "active_kid",
        "keys",
        "retired_kids",
        "artifacts",
    } or manifest.get("schema_version") != _PREVIOUS_MANIFEST_SCHEMA:
        raise IdentityConfigurationError("demo identity manifest is invalid")
    keys = manifest.get("keys")
    if not isinstance(keys, list) or any(not isinstance(item, dict) for item in keys):
        raise IdentityConfigurationError("demo identity manifest is invalid")
    key_ids = [item.get("kid") for item in keys]
    if any(not isinstance(kid, str) for kid in key_ids):
        raise IdentityConfigurationError("demo identity manifest is invalid")
    active_kid = manifest.get("active_kid")
    pending_kid = _pending_kid(manifest)
    retirement_deadline = (
        _now_epoch()
        + _MAX_TOKEN_LIFETIME_SECONDS
        + IDENTITY_CLOCK_SKEW_MAX_SECONDS
    )
    upgraded = {
        **manifest,
        "schema_version": _MANIFEST_SCHEMA,
        "retire_not_before": {
            str(kid): retirement_deadline
            for kid in key_ids
            if kid != active_kid and kid != pending_kid
        },
        "emergency_revocations": [],
    }
    runtime = _read_runtime_artifacts(root)
    _validate_staged_manifest(root, upgraded, runtime)
    return upgraded, runtime


def _public_jwks(manifest: dict[str, Any]) -> dict[str, Any]:
    return {"keys": [item["public_jwk"] for item in manifest["keys"]]}


def _status(
    manifest: dict[str, Any],
    *,
    restart_required: bool = False,
) -> DemoIdentityStatus:
    return DemoIdentityStatus(
        active_kid=str(manifest["active_kid"]),
        key_ids=tuple(sorted(str(item["kid"]) for item in manifest["keys"])),
        persona_count=len(_PERSONAS),
        pending_kid=_pending_kid(manifest),
        restart_required=restart_required or _pending_kid(manifest) is not None,
        retirement_not_before=tuple(
            sorted(
                (str(kid), int(deadline))
                for kid, deadline in manifest["retire_not_before"].items()
            )
        ),
        emergency_revocations=tuple(
            (
                str(event["kid"]),
                int(event["revoked_at"]),
            )
            for event in manifest["emergency_revocations"]
        ),
    )


def _pending_kid(manifest: dict[str, Any]) -> str | None:
    keys = manifest.get("keys")
    active = manifest.get("active_kid")
    if not isinstance(keys, list) or not keys:
        return None
    candidate = keys[-1]
    if not isinstance(candidate, dict):
        return None
    kid = candidate.get("kid")
    if isinstance(kid, str) and kid != active:
        return kid
    return None


def _validate_retirement_metadata(
    manifest: dict[str, Any],
    key_ids: set[str],
    *,
    error_message: str,
) -> None:
    active_kid = manifest.get("active_kid")
    pending_kid = _pending_kid(manifest)
    expected_deadline_keys = key_ids - {active_kid}
    if pending_kid is not None:
        expected_deadline_keys.discard(pending_kid)
    deadlines = manifest.get("retire_not_before")
    if (
        not isinstance(deadlines, dict)
        or set(deadlines) != expected_deadline_keys
        or any(
            not isinstance(kid, str)
            or not _DEMO_KID_PATTERN.fullmatch(kid)
            or isinstance(deadline, bool)
            or not isinstance(deadline, int)
            or not 0 < deadline <= _MAX_EPOCH_SECONDS
            for kid, deadline in deadlines.items()
        )
    ):
        raise IdentityConfigurationError(error_message)

    retired = manifest.get("retired_kids")
    emergency = manifest.get("emergency_revocations")
    if not isinstance(retired, list) or not isinstance(emergency, list):
        raise IdentityConfigurationError(error_message)
    observed_emergency_kids: set[str] = set()
    for event in emergency:
        if not isinstance(event, dict) or set(event) != {"kid", "revoked_at"}:
            raise IdentityConfigurationError(error_message)
        kid = event["kid"]
        revoked_at = event["revoked_at"]
        if (
            not isinstance(kid, str)
            or kid not in retired
            or kid in observed_emergency_kids
            or isinstance(revoked_at, bool)
            or not isinstance(revoked_at, int)
            or not 0 < revoked_at <= _MAX_EPOCH_SECONDS
        ):
            raise IdentityConfigurationError(error_message)
        observed_emergency_kids.add(kid)


def _private_key_bytes(private_key: rsa.RSAPrivateKey) -> bytes:
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("ascii")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write(path, _json_bytes(payload))


def _read_runtime_artifacts(root: Path) -> dict[str, bytes]:
    limits = {
        _JWKS_FILE: 131_072,
        _PERSONA_FILE: 262_144,
        _OPERATOR_FILE: 32_768,
        _LOAD_USER_FILE: 32_768,
        _HMAC_FILE: 256,
    }
    return {
        name: read_private_file_snapshot(root / name, max_bytes=limits[name])
        for name in _RUNTIME_ARTIFACT_FILES
    }


def _committed_writes(
    manifest: dict[str, Any],
    runtime: dict[str, bytes],
    *,
    extra: dict[str, bytes] | None = None,
) -> dict[str, bytes]:
    if set(runtime) != set(_RUNTIME_ARTIFACT_FILES):
        raise IdentityConfigurationError("identity runtime artifact set is invalid")
    manifest["schema_version"] = _MANIFEST_SCHEMA
    manifest["artifacts"] = {
        name: hashlib.sha256(runtime[name]).hexdigest()
        for name in _RUNTIME_ARTIFACT_FILES
    }
    writes = dict(runtime)
    writes.update(extra or {})
    writes[_MANIFEST_FILE] = _json_bytes(manifest)
    return writes


def _new_operation(
    *,
    kind: str,
    subject_kid: str,
    writes: dict[str, bytes],
    deletes: list[str],
    activation_policy: dict[str, Any] | None = None,
    retirement_authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if kind not in {"init", "rotate", "activate", "retire", "upgrade"}:
        raise ValueError("identity operation kind is invalid")
    if not _DEMO_KID_PATTERN.fullmatch(subject_kid):
        raise ValueError("identity operation key ID is invalid")
    required = set(_RUNTIME_ARTIFACT_FILES) | {_MANIFEST_FILE}
    if not required.issubset(writes) or len(writes) > len(required) + 1:
        raise ValueError("identity operation write set is invalid")
    if any(not _safe_operation_filename(name, allow_manifest=True) for name in writes):
        raise ValueError("identity operation write path is invalid")
    if len(deletes) != len(set(deletes)) or any(
        not _private_key_filename(name) for name in deletes
    ):
        raise ValueError("identity operation delete path is invalid")
    if kind == "activate":
        if (
            not isinstance(activation_policy, dict)
            or set(activation_policy)
            != {
                "activated_at",
                "clock_skew_seconds",
                "max_token_lifetime_seconds",
                "previous_active_kid",
            }
            or isinstance(activation_policy["activated_at"], bool)
            or not isinstance(activation_policy["activated_at"], int)
            or not 0 < activation_policy["activated_at"] <= _MAX_EPOCH_SECONDS
            or activation_policy["clock_skew_seconds"]
            != IDENTITY_CLOCK_SKEW_MAX_SECONDS
            or activation_policy["max_token_lifetime_seconds"]
            != _MAX_TOKEN_LIFETIME_SECONDS
            or not isinstance(activation_policy["previous_active_kid"], str)
            or not _DEMO_KID_PATTERN.fullmatch(
                activation_policy["previous_active_kid"]
            )
            or activation_policy["previous_active_kid"] == subject_kid
        ):
            raise ValueError("identity activation policy is invalid")
    elif activation_policy is not None:
        raise ValueError("identity activation policy is only valid for activation")
    if kind == "retire":
        if (
            not isinstance(retirement_authorization, dict)
            or set(retirement_authorization) != {"mode", "authorized_at"}
            or retirement_authorization["mode"] not in {"scheduled", "emergency"}
            or isinstance(retirement_authorization["authorized_at"], bool)
            or not isinstance(retirement_authorization["authorized_at"], int)
            or not 0
            < retirement_authorization["authorized_at"]
            <= _MAX_EPOCH_SECONDS
        ):
            raise ValueError("identity retirement authorization is invalid")
    elif retirement_authorization is not None:
        raise ValueError(
            "identity retirement authorization is only valid for retirement"
        )
    return {
        "schema_version": _OPERATION_SCHEMA,
        "operation_id": secrets.token_hex(16),
        "kind": kind,
        "subject_kid": subject_kid,
        "activation_policy": activation_policy,
        "retirement_authorization": retirement_authorization,
        "writes": {
            name: base64.b64encode(payload).decode("ascii")
            for name, payload in sorted(writes.items())
        },
        "deletes": sorted(deletes),
    }


def _commit_operation(root: Path, operation: dict[str, Any]) -> None:
    validated = _validate_operation(operation, root=root)
    journal_payload = _json_bytes(operation)
    if len(journal_payload) > _MAX_OPERATION_BYTES:
        raise IdentityConfigurationError(
            "identity operation journal exceeds the recovery size limit"
        )
    _atomic_write(root / _OPERATION_FILE, journal_payload)
    _apply_operation(root, validated)


def _recover_pending_operation(root: Path) -> dict[str, Any] | None:
    journal = root / _OPERATION_FILE
    try:
        journal.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise IdentityConfigurationError("identity operation journal is unavailable") from None
    raw = read_private_file_snapshot(journal, max_bytes=_MAX_OPERATION_BYTES)
    try:
        payload = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise IdentityConfigurationError("identity operation journal is invalid") from None
    operation = _validate_operation(payload, root=root)
    _apply_operation(root, operation)
    return operation


def _validate_operation(
    payload: Any,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "operation_id",
        "kind",
        "subject_kid",
        "activation_policy",
        "retirement_authorization",
        "writes",
        "deletes",
    }:
        raise IdentityConfigurationError("identity operation journal is invalid")
    if (
        payload["schema_version"] != _OPERATION_SCHEMA
        or not isinstance(payload["operation_id"], str)
        or not re.fullmatch(r"[0-9a-f]{32}", payload["operation_id"])
        or payload["kind"] not in {
            "init",
            "rotate",
            "activate",
            "retire",
            "upgrade",
        }
        or not isinstance(payload["subject_kid"], str)
        or not _DEMO_KID_PATTERN.fullmatch(payload["subject_kid"])
        or not isinstance(payload["writes"], dict)
        or not isinstance(payload["deletes"], list)
    ):
        raise IdentityConfigurationError("identity operation journal is invalid")
    activation_policy = payload["activation_policy"]
    if payload["kind"] == "activate":
        if (
            not isinstance(activation_policy, dict)
            or set(activation_policy)
            != {
                "activated_at",
                "clock_skew_seconds",
                "max_token_lifetime_seconds",
                "previous_active_kid",
            }
            or isinstance(activation_policy["activated_at"], bool)
            or not isinstance(activation_policy["activated_at"], int)
            or not 0 < activation_policy["activated_at"] <= _MAX_EPOCH_SECONDS
            or activation_policy["clock_skew_seconds"]
            != IDENTITY_CLOCK_SKEW_MAX_SECONDS
            or activation_policy["max_token_lifetime_seconds"]
            != _MAX_TOKEN_LIFETIME_SECONDS
            or not isinstance(activation_policy["previous_active_kid"], str)
            or not _DEMO_KID_PATTERN.fullmatch(
                activation_policy["previous_active_kid"]
            )
            or activation_policy["previous_active_kid"]
            == payload["subject_kid"]
        ):
            raise IdentityConfigurationError(
                "identity operation journal is invalid"
            )
    elif activation_policy is not None:
        raise IdentityConfigurationError("identity operation journal is invalid")
    retirement_authorization = payload["retirement_authorization"]
    if payload["kind"] == "retire":
        if (
            not isinstance(retirement_authorization, dict)
            or set(retirement_authorization) != {"mode", "authorized_at"}
            or retirement_authorization["mode"] not in {"scheduled", "emergency"}
            or isinstance(retirement_authorization["authorized_at"], bool)
            or not isinstance(retirement_authorization["authorized_at"], int)
            or not 0
            < retirement_authorization["authorized_at"]
            <= _MAX_EPOCH_SECONDS
        ):
            raise IdentityConfigurationError(
                "identity operation journal is invalid"
            )
    elif retirement_authorization is not None:
        raise IdentityConfigurationError("identity operation journal is invalid")
    encoded_writes = payload["writes"]
    required = set(_RUNTIME_ARTIFACT_FILES) | {_MANIFEST_FILE}
    if (
        not required.issubset(encoded_writes)
        or len(encoded_writes) > len(required) + 1
        or any(
            not isinstance(name, str)
            or not _safe_operation_filename(name, allow_manifest=True)
            or not isinstance(value, str)
            for name, value in encoded_writes.items()
        )
    ):
        raise IdentityConfigurationError("identity operation journal is invalid")
    writes: dict[str, bytes] = {}
    try:
        for name, value in encoded_writes.items():
            writes[name] = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError):
        raise IdentityConfigurationError("identity operation journal is invalid") from None
    deletes = payload["deletes"]
    if len(deletes) != len(set(deletes)) or any(
        not isinstance(name, str) or not _private_key_filename(name)
        for name in deletes
    ):
        raise IdentityConfigurationError("identity operation journal is invalid")
    total_bytes = sum(len(value) for value in writes.values())
    if total_bytes > _MAX_OPERATION_BYTES:
        raise IdentityConfigurationError("identity operation journal is invalid")
    operation = {**payload, "writes": writes, "deletes": list(deletes)}
    if root is not None:
        _validate_operation_semantics(root, operation)
    return operation


def _apply_operation(root: Path, operation: dict[str, Any]) -> None:
    writes = operation["writes"]
    if writes and isinstance(next(iter(writes.values())), str):
        operation = _validate_operation(operation, root=root)
        writes = operation["writes"]
    ordered = sorted(name for name in writes if name != _MANIFEST_FILE)
    ordered.append(_MANIFEST_FILE)
    for name in ordered:
        _atomic_write(root / name, writes[name])
    for name in operation["deletes"]:
        _unlink_private_key(root, name)
    journal = root / _OPERATION_FILE
    try:
        metadata = _active_entry_metadata(journal)
    except FileNotFoundError:
        return
    if not _secure_regular_entry(metadata):
        raise IdentityConfigurationError("identity operation journal is unsafe")
    _unlink_active_entry(journal)
    sync_directory(getattr(_ACTIVE_DIRECTORY, "descriptor", None))


def _validate_operation_semantics(
    root: Path,
    operation: dict[str, Any],
) -> None:
    try:
        writes = operation["writes"]
        manifest_raw = writes[_MANIFEST_FILE]
        manifest = json.loads(
            manifest_raw.decode("ascii"),
            object_pairs_hook=_unique_object,
        )
        _validate_staged_manifest(root, manifest, writes)
        jwks = json.loads(
            writes[_JWKS_FILE].decode("ascii"),
            object_pairs_hook=_unique_object,
        )
    except (
        KeyError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        IdentityConfigurationError,
    ):
        raise IdentityConfigurationError("identity operation journal is invalid") from None
    if jwks != _public_jwks(manifest):
        raise IdentityConfigurationError("identity operation journal is invalid")

    kind = operation["kind"]
    subject = operation["subject_kid"]
    keys = {str(item["kid"]): item for item in manifest["keys"]}
    extra_writes = set(writes) - set(_RUNTIME_ARTIFACT_FILES) - {_MANIFEST_FILE}
    subject_private = f"private-{subject}.pem"
    if kind in {"init", "rotate"}:
        if extra_writes != {subject_private}:
            raise IdentityConfigurationError("identity operation journal is invalid")
    elif extra_writes:
        raise IdentityConfigurationError("identity operation journal is invalid")
    if subject not in keys and kind != "retire":
        raise IdentityConfigurationError("identity operation journal is invalid")
    if any(name in {item["private_key_file"] for item in keys.values()} for name in operation["deletes"]):
        raise IdentityConfigurationError("identity operation journal is invalid")

    current = _current_manifest_metadata(root)
    if current is not None and current["raw"] == manifest_raw:
        _validate_completed_operation_semantics(manifest, operation)
        return
    current_ids = set(current["key_ids"]) if current is not None else set()
    new_ids = set(keys)
    deletes = set(operation["deletes"])
    current_deadlines = (
        dict(current["retire_not_before"]) if current is not None else {}
    )
    target_deadlines = dict(manifest["retire_not_before"])
    current_emergency = (
        list(current["emergency_revocations"]) if current is not None else []
    )
    target_emergency = list(manifest["emergency_revocations"])
    current_retired = list(current["retired_kids"]) if current is not None else []
    if kind == "init":
        expected_deletes = set(current["private_files"]) if current is not None else set()
        if new_ids != {subject} or manifest["active_kid"] != subject or deletes != expected_deletes:
            raise IdentityConfigurationError("identity operation journal is invalid")
    elif kind == "rotate":
        staged_transition = (
            current is not None
            and current["schema"] == _MANIFEST_SCHEMA
            and current["pending_kid"] is None
            and new_ids == current_ids | {subject}
            and len(new_ids) == len(current_ids) + 1
            and manifest["active_kid"] == current["active_kid"]
            and _pending_kid(manifest) == subject
            and target_deadlines == current_deadlines
            and target_emergency == current_emergency
            and manifest["retired_kids"] == current_retired
            and not deletes
        )
        if not staged_transition:
            raise IdentityConfigurationError("identity operation journal is invalid")
    elif kind == "activate":
        expected_deadline_keys = set(current_deadlines)
        activation_policy = operation["activation_policy"]
        expected_added_deadline = (
            activation_policy["activated_at"]
            + activation_policy["max_token_lifetime_seconds"]
            + activation_policy["clock_skew_seconds"]
        )
        if current is not None:
            expected_deadline_keys.add(str(current["active_kid"]))
        if (
            current is None
            or current["schema"] != _MANIFEST_SCHEMA
            or current["pending_kid"] != subject
            or current["active_kid"]
            != activation_policy["previous_active_kid"]
            or new_ids != current_ids
            or manifest["active_kid"] != subject
            or _pending_kid(manifest) is not None
            or set(target_deadlines) != expected_deadline_keys
            or any(
                target_deadlines.get(existing_kid) != deadline
                for existing_kid, deadline in current_deadlines.items()
            )
            or (
                current is not None
                and target_deadlines.get(str(current["active_kid"]))
                != expected_added_deadline
            )
            or target_emergency != current_emergency
            or manifest["retired_kids"] != current_retired
            or deletes
        ):
            raise IdentityConfigurationError("identity operation journal is invalid")
    elif kind == "retire":
        current_deadline = current_deadlines.get(subject)
        retirement_grant = operation["retirement_authorization"]
        grant_mode = retirement_grant["mode"]
        authorized_at = retirement_grant["authorized_at"]
        emergency_append = (
            grant_mode == "emergency"
            and isinstance(current_deadline, int)
            and authorized_at < current_deadline
            and len(target_emergency) == len(current_emergency) + 1
            and target_emergency[:-1] == current_emergency
            and target_emergency[-1]
            == {"kid": subject, "revoked_at": authorized_at}
        )
        scheduled_retirement = (
            grant_mode == "scheduled"
            and target_emergency == current_emergency
            and (
                current_deadline is None
                or authorized_at >= current_deadline
            )
        )
        if (
            current is None
            or current["schema"] != _MANIFEST_SCHEMA
            or subject not in current_ids
            or new_ids != current_ids - {subject}
            or deletes != {f"private-{subject}.pem"}
            or manifest["retired_kids"] != [*current_retired, subject]
            or target_deadlines
            != {
                existing_kid: deadline
                for existing_kid, deadline in current_deadlines.items()
                if existing_kid != subject
            }
            or (
                target_emergency != current_emergency
                and not emergency_append
            )
            or not (scheduled_retirement or emergency_append)
        ):
            raise IdentityConfigurationError("identity operation journal is invalid")
    elif (
        current is None
        or current["schema"]
        not in {_LEGACY_MANIFEST_SCHEMA, _PREVIOUS_MANIFEST_SCHEMA}
        or new_ids != current_ids
        or manifest["active_kid"] != subject
        or manifest["retired_kids"] != current_retired
        or target_emergency
        or deletes
    ):
        raise IdentityConfigurationError("identity operation journal is invalid")


def _validate_completed_operation_semantics(
    manifest: dict[str, Any],
    operation: dict[str, Any],
) -> None:
    kind = operation["kind"]
    subject = operation["subject_kid"]
    key_ids = {str(item["kid"]) for item in manifest["keys"]}
    active = str(manifest["active_kid"])
    pending = _pending_kid(manifest)
    deadlines = dict(manifest["retire_not_before"])
    retired = list(manifest["retired_kids"])
    emergency = list(manifest["emergency_revocations"])
    deletes = set(operation["deletes"])

    if kind == "init":
        valid = (
            key_ids == {subject}
            and active == subject
            and pending is None
            and not deadlines
            and not retired
            and not emergency
        )
    elif kind == "rotate":
        valid = (
            subject in key_ids
            and active != subject
            and pending == subject
            and not deletes
        )
    elif kind == "activate":
        policy = operation["activation_policy"]
        previous_active = policy["previous_active_kid"]
        expected_deadline = (
            policy["activated_at"]
            + policy["max_token_lifetime_seconds"]
            + policy["clock_skew_seconds"]
        )
        valid = (
            active == subject
            and pending is None
            and previous_active in key_ids
            and previous_active != subject
            and deadlines.get(previous_active) == expected_deadline
            and not deletes
        )
    elif kind == "retire":
        authorization = operation["retirement_authorization"]
        expected_emergency_event = {
            "kid": subject,
            "revoked_at": authorization["authorized_at"],
        }
        event_matches = (
            bool(emergency)
            and emergency[-1] == expected_emergency_event
            if authorization["mode"] == "emergency"
            else all(event["kid"] != subject for event in emergency)
        )
        valid = (
            subject not in key_ids
            and bool(retired)
            and retired[-1] == subject
            and subject not in deadlines
            and deletes == {f"private-{subject}.pem"}
            and event_matches
        )
    else:
        valid = (
            kind == "upgrade"
            and subject in key_ids
            and active == subject
            and not deletes
        )

    if not valid:
        raise IdentityConfigurationError("identity operation journal is invalid")


def _validate_staged_manifest(
    root: Path,
    manifest: Any,
    writes: dict[str, bytes],
) -> None:
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version",
        "issuer",
        "audience",
        "active_kid",
        "keys",
        "retired_kids",
        "retire_not_before",
        "emergency_revocations",
        "artifacts",
    } or manifest["schema_version"] != _MANIFEST_SCHEMA:
        raise IdentityConfigurationError("staged manifest is invalid")
    if not isinstance(manifest["issuer"], str) or not isinstance(manifest["audience"], str):
        raise IdentityConfigurationError("staged manifest is invalid")
    keys = manifest["keys"]
    if not isinstance(keys, list) or not 1 <= len(keys) <= _MAX_KEYRING_KEYS:
        raise IdentityConfigurationError("staged manifest is invalid")
    key_ids: set[str] = set()
    for item in keys:
        if not isinstance(item, dict) or set(item) != {
            "kid",
            "private_key_file",
            "private_key_sha256",
            "public_jwk",
        }:
            raise IdentityConfigurationError("staged manifest is invalid")
        kid = item["kid"]
        private_file = item["private_key_file"]
        digest = item["private_key_sha256"]
        jwk = item["public_jwk"]
        if (
            not isinstance(kid, str)
            or not _DEMO_KID_PATTERN.fullmatch(kid)
            or kid in key_ids
            or private_file != f"private-{kid}.pem"
            or not isinstance(digest, str)
            or not _DIGEST_PATTERN.fullmatch(digest)
            or not isinstance(jwk, dict)
            or set(jwk) != {"alg", "e", "key_ops", "kid", "kty", "n", "use"}
            or jwk.get("alg") != "RS256"
            or jwk.get("kid") != kid
            or jwk.get("kty") != "RSA"
            or jwk.get("use") != "sig"
            or jwk.get("key_ops") != ["verify"]
        ):
            raise IdentityConfigurationError("staged manifest is invalid")
        private_bytes = writes.get(private_file)
        if private_bytes is None:
            private_bytes = read_private_file_snapshot(root / private_file, max_bytes=32_768)
        if not secrets.compare_digest(hashlib.sha256(private_bytes).hexdigest(), digest):
            raise IdentityConfigurationError("staged manifest is invalid")
        try:
            private_key = serialization.load_pem_private_key(
                private_bytes,
                None,
            )
        except (TypeError, ValueError):
            raise IdentityConfigurationError("staged manifest is invalid") from None
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise IdentityConfigurationError("staged manifest is invalid")
        numbers = private_key.public_key().public_numbers()
        if jwk.get("e") != _base64url_uint(numbers.e) or jwk.get("n") != _base64url_uint(numbers.n):
            raise IdentityConfigurationError("staged manifest is invalid")
        key_ids.add(kid)
    if manifest["active_kid"] not in key_ids:
        raise IdentityConfigurationError("staged manifest is invalid")
    retired = manifest["retired_kids"]
    if (
        not isinstance(retired, list)
        or len(retired) > _MAX_RETIRED_KEY_IDS
        or len(retired) != len(set(retired))
        or any(not isinstance(kid, str) or not _DEMO_KID_PATTERN.fullmatch(kid) for kid in retired)
        or key_ids.intersection(retired)
    ):
        raise IdentityConfigurationError("staged manifest is invalid")
    _validate_retirement_metadata(
        manifest,
        key_ids,
        error_message="staged manifest is invalid",
    )
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != set(_RUNTIME_ARTIFACT_FILES):
        raise IdentityConfigurationError("staged manifest is invalid")
    for name in _RUNTIME_ARTIFACT_FILES:
        expected = artifacts.get(name)
        if (
            not isinstance(expected, str)
            or not _DIGEST_PATTERN.fullmatch(expected)
            or not secrets.compare_digest(hashlib.sha256(writes[name]).hexdigest(), expected)
        ):
            raise IdentityConfigurationError("staged manifest is invalid")
    if not 32 <= len(writes[_HMAC_FILE]) <= 256:
        raise IdentityConfigurationError("staged manifest is invalid")


def _current_manifest_metadata(root: Path) -> dict[str, Any] | None:
    manifest_path = root / _MANIFEST_FILE
    try:
        raw = read_private_file_snapshot(manifest_path, max_bytes=131_072)
    except IdentityConfigurationError:
        if not manifest_path.exists():
            return None
        raise
    try:
        manifest = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise IdentityConfigurationError("identity operation journal is invalid") from None
    if not isinstance(manifest, dict) or manifest.get("schema_version") not in {
        _MANIFEST_SCHEMA,
        _PREVIOUS_MANIFEST_SCHEMA,
        _LEGACY_MANIFEST_SCHEMA,
    } or not isinstance(manifest.get("keys"), list):
        raise IdentityConfigurationError("identity operation journal is invalid")
    key_ids: list[str] = []
    private_files: list[str] = []
    for item in manifest["keys"]:
        if not isinstance(item, dict):
            raise IdentityConfigurationError("identity operation journal is invalid")
        kid = item.get("kid")
        private_file = item.get("private_key_file")
        if (
            not isinstance(kid, str)
            or not _DEMO_KID_PATTERN.fullmatch(kid)
            or private_file != f"private-{kid}.pem"
        ):
            raise IdentityConfigurationError("identity operation journal is invalid")
        key_ids.append(kid)
        private_files.append(private_file)
    return {
        "raw": raw,
        "schema": manifest["schema_version"],
        "key_ids": key_ids,
        "private_files": private_files,
        "active_kid": manifest.get("active_kid"),
        "pending_kid": _pending_kid(manifest),
        "retired_kids": (
            list(manifest.get("retired_kids", []))
            if isinstance(manifest.get("retired_kids", []), list)
            else []
        ),
        "retire_not_before": (
            dict(manifest.get("retire_not_before", {}))
            if isinstance(manifest.get("retire_not_before", {}), dict)
            else {}
        ),
        "emergency_revocations": (
            list(manifest.get("emergency_revocations", []))
            if isinstance(manifest.get("emergency_revocations", []), list)
            else []
        ),
    }


def _safe_operation_filename(name: str, *, allow_manifest: bool) -> bool:
    fixed = set(_RUNTIME_ARTIFACT_FILES)
    if allow_manifest:
        fixed.add(_MANIFEST_FILE)
    return name in fixed or _private_key_filename(name)


def _private_key_filename(name: str) -> bool:
    return bool(
        isinstance(name, str)
        and re.fullmatch(r"private-demo-\d{8}T\d{6}Z-[0-9a-f]{8}\.pem", name)
        and Path(name).name == name
    )


def _unlink_private_key(root: Path, name: str) -> None:
    if not _private_key_filename(name):
        raise IdentityConfigurationError("identity key path is invalid")
    target = root / name
    validate_private_path_ancestors(target)
    try:
        metadata = _active_entry_metadata(target)
    except FileNotFoundError:
        return
    if not _secure_regular_entry(metadata):
        raise IdentityConfigurationError("identity key path is invalid")
    _unlink_active_entry(target)
    sync_directory(getattr(_ACTIVE_DIRECTORY, "descriptor", None))


@contextmanager
def _identity_lock(root: Path):
    key = os.path.normcase(str(root))
    with _PROCESS_LOCKS_GUARD:
        process_lock = _PROCESS_LOCKS.setdefault(key, threading.RLock())
    with process_lock:
        guard = None
        guard_entered = False
        try:
            guard = hold_private_directory(root)
            directory_descriptor = guard.__enter__()
            guard_entered = True
            validate_private_directory_permissions(root)
            directory_identity = capture_private_directory_identity(
                root,
                directory_descriptor,
            )
        except PrivatePathError:
            if guard is not None and guard_entered:
                guard.__exit__(None, None, None)
            raise IdentityConfigurationError("identity directory is unsafe") from None
        previous_directory_descriptor = getattr(_ACTIVE_DIRECTORY, "descriptor", None)
        previous_directory_binding = getattr(_ACTIVE_DIRECTORY, "binding", None)
        try:
            _ACTIVE_DIRECTORY.descriptor = directory_descriptor
            _ACTIVE_DIRECTORY.binding = _ActiveDirectoryBinding(
                root=root,
                descriptor=directory_descriptor,
                identity=directory_identity,
            )
            lock_path = root / _LOCK_FILE
            _assert_active_directory_target(lock_path)
            validate_private_path_ancestors(lock_path)
            create_flags = (
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0)
            )
            try:
                descriptor = _open_active_entry(
                    lock_path,
                    create_flags,
                    0o600,
                )
            except FileExistsError:
                metadata = _active_entry_metadata(lock_path)
                if not _secure_regular_entry(metadata):
                    raise IdentityConfigurationError("identity lock file is unsafe")
                descriptor = _open_active_entry(
                    lock_path,
                    os.O_RDWR
                    | getattr(os, "O_BINARY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                )
            try:
                descriptor_metadata = os.fstat(descriptor)
                path_metadata = _active_entry_metadata(lock_path)
                if (
                    not _secure_regular_entry(descriptor_metadata)
                    or _is_reparse_point(path_metadata)
                    or (descriptor_metadata.st_dev, descriptor_metadata.st_ino)
                    != (path_metadata.st_dev, path_metadata.st_ino)
                ):
                    raise IdentityConfigurationError(
                        "identity lock file is unsafe"
                    )
                if descriptor_metadata.st_size < 1:
                    _assert_active_directory_target(lock_path)
                    os.write(descriptor, b"\0")
                    os.fsync(descriptor)
                _lock_descriptor(descriptor)
                try:
                    _assert_active_directory_path(root)
                    _validate_identity_directory(root)
                    _cleanup_stale_temporary_files(root)
                    yield
                finally:
                    _unlock_descriptor(descriptor)
            finally:
                os.close(descriptor)
        finally:
            _ACTIVE_DIRECTORY.descriptor = previous_directory_descriptor
            _ACTIVE_DIRECTORY.binding = previous_directory_binding
            guard.__exit__(None, None, None)


def _lock_descriptor(descriptor: int) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        while True:
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise IdentityConfigurationError(
                        "identity lifecycle lock timed out"
                    ) from None
                time.sleep(_LOCK_POLL_SECONDS)
        return
    import fcntl

    _lock_posix_descriptor(
        descriptor,
        flock=fcntl.flock,
        lock_ex=fcntl.LOCK_EX,
        lock_nonblocking=fcntl.LOCK_NB,
    )


def _lock_posix_descriptor(
    descriptor: int,
    *,
    flock: Callable[[int, int], Any],
    lock_ex: int,
    lock_nonblocking: int,
) -> None:
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    while True:
        try:
            flock(descriptor, lock_ex | lock_nonblocking)
            return
        except BlockingIOError:
            pass
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise IdentityConfigurationError(
                    "identity lifecycle lock failed"
                ) from None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise IdentityConfigurationError(
                "identity lifecycle lock timed out"
            )
        time.sleep(min(_LOCK_POLL_SECONDS, remaining))


def _unlock_descriptor(descriptor: int) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


def _atomic_write(path: Path, payload: bytes) -> None:
    target = Path(path)
    validate_private_path_ancestors(target)
    try:
        metadata = _active_entry_metadata(target)
    except FileNotFoundError:
        metadata = None
    if metadata is not None:
        if not _secure_regular_entry(metadata):
            raise IdentityConfigurationError("identity artifact target is unsafe")
    temporary = target.parent / f".{target.name}.tmp-{secrets.token_hex(8)}"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
    )
    descriptor: int | None = _open_active_entry(temporary, flags, 0o600)
    try:
        handle = os.fdopen(descriptor, "wb")
        descriptor = None
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _chmod_active_entry(temporary, 0o600)
        _replace_active_entry(temporary, target)
        sync_directory(getattr(_ACTIVE_DIRECTORY, "descriptor", None))
    finally:
        if descriptor is not None:
            os.close(descriptor)
        _unlink_active_entry(
            temporary,
            missing_ok=True,
            require_current_path=False,
        )


def _prepare_directory(directory: Path) -> Path:
    root = Path(os.path.abspath(directory))
    validate_private_path_ancestors(root, allow_missing=True)
    root.mkdir(parents=True, exist_ok=True)
    validate_private_path_ancestors(root)
    _validate_identity_directory(root)
    try:
        harden_private_directory(root)
    except PrivatePathError:
        raise IdentityConfigurationError(
            "identity private directory permissions are unsafe"
        ) from None
    return root


def _prepare_status_directory(directory: Path) -> Path:
    root = Path(os.path.abspath(directory))
    validate_private_path_ancestors(root)
    try:
        _validate_identity_directory(root)
    except OSError:
        raise IdentityConfigurationError("demo identity is unavailable") from None
    if not _status_target_has_valid_identity_state(root):
        raise IdentityConfigurationError("demo identity is unavailable")
    try:
        harden_private_directory(root)
    except PrivatePathError:
        raise IdentityConfigurationError(
            "identity private directory permissions are unsafe"
        ) from None
    return root


def _safe_existing_identity_marker(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        raise IdentityConfigurationError("demo identity is unavailable") from None
    if not _secure_regular_entry(metadata):
        raise IdentityConfigurationError("demo identity is unavailable")
    return True


def _status_target_has_valid_identity_state(root: Path) -> bool:
    manifest_path = root / _MANIFEST_FILE
    manifest_present = _safe_existing_identity_marker(manifest_path)
    manifest_invalid = False
    if manifest_present:
        try:
            metadata = _current_manifest_metadata(root)
            if metadata is not None:
                if metadata["schema"] == _MANIFEST_SCHEMA:
                    _load_manifest(root)
                return True
        except IdentityConfigurationError:
            manifest_invalid = True

    journal_path = root / _OPERATION_FILE
    journal_present = _safe_existing_identity_marker(journal_path)
    if journal_present:
        try:
            raw = read_private_file_snapshot(
                journal_path,
                max_bytes=_MAX_OPERATION_BYTES,
            )
            payload = json.loads(
                raw.decode("ascii"),
                object_pairs_hook=_unique_object,
            )
            _validate_operation(payload, root=root)
            return True
        except (
            IdentityConfigurationError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
        ):
            pass
    if manifest_invalid:
        raise IdentityConfigurationError(
            "demo identity manifest is invalid"
        )
    if journal_present:
        raise IdentityConfigurationError(
            "identity operation journal is invalid"
        )
    return False


def _validate_identity_directory(root: Path) -> None:
    metadata = root.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or _is_reparse_point(metadata)
    ):
        raise IdentityConfigurationError("identity directory is unsafe")
    resolved = root.resolve(strict=True)
    if os.path.normcase(str(resolved)) != os.path.normcase(str(root)):
        raise IdentityConfigurationError("identity directory is unsafe")


def _existing_private_files(root: Path) -> list[Path]:
    if not (root / _MANIFEST_FILE).exists():
        return []
    manifest = _load_manifest(root)
    return [root / str(item["private_key_file"]) for item in manifest["keys"]]


def _cleanup_stale_temporary_files(root: Path) -> None:
    for entry in _active_directory_entries(root):
        match = re.fullmatch(r"\.(.+)\.tmp-[0-9a-f]{16}", entry.name)
        if match is None or not _managed_atomic_target(match.group(1)):
            continue
        metadata = _active_entry_metadata(entry)
        if not _secure_regular_entry(metadata):
            raise IdentityConfigurationError("identity temporary artifact is unsafe")
        _unlink_active_entry(entry)
        sync_directory(getattr(_ACTIVE_DIRECTORY, "descriptor", None))


def _managed_atomic_target(name: str) -> bool:
    return (
        name == _OPERATION_FILE
        or _safe_operation_filename(name, allow_manifest=True)
    )


def _active_directory_path_is_current(root: Path) -> bool:
    binding = getattr(_ACTIVE_DIRECTORY, "binding", None)
    candidate = Path(root).absolute()
    if not isinstance(binding, _ActiveDirectoryBinding) or (
        os.path.normcase(str(candidate))
        != os.path.normcase(str(binding.root))
    ):
        return False
    return private_directory_identity_is_current(
        binding.root,
        binding.descriptor,
        binding.identity,
    )


def _assert_active_directory_path(root: Path) -> None:
    if not _active_directory_path_is_current(root):
        raise IdentityConfigurationError(
            "identity directory changed while locked"
        )


def _assert_active_directory_target(path: Path) -> None:
    target = Path(path).absolute()
    binding = getattr(_ACTIVE_DIRECTORY, "binding", None)
    if not isinstance(binding, _ActiveDirectoryBinding) or (
        os.path.normcase(str(target.parent))
        != os.path.normcase(str(binding.root))
    ):
        raise IdentityConfigurationError(
            "identity directory changed while locked"
        )
    _assert_active_directory_path(binding.root)


def _active_posix_directory_descriptor() -> int | None:
    binding = getattr(_ACTIVE_DIRECTORY, "binding", None)
    if (
        os.name != "nt"
        and isinstance(binding, _ActiveDirectoryBinding)
        and binding.descriptor is not None
    ):
        return binding.descriptor
    return None


def _active_entry_metadata(path: Path) -> os.stat_result:
    target = Path(path)
    _assert_active_directory_target(target)
    descriptor = _active_posix_directory_descriptor()
    if descriptor is not None:
        return os.stat(
            target.name,
            dir_fd=descriptor,
            follow_symlinks=False,
        )
    return target.lstat()


def _open_active_entry(path: Path, flags: int, mode: int = 0o600) -> int:
    target = Path(path)
    _assert_active_directory_target(target)
    descriptor = _active_posix_directory_descriptor()
    if descriptor is not None:
        return os.open(target.name, flags, mode, dir_fd=descriptor)
    return os.open(target, flags, mode)


def _replace_active_entry(source: Path, target: Path) -> None:
    _assert_active_directory_target(source)
    _assert_active_directory_target(target)
    descriptor = _active_posix_directory_descriptor()
    if descriptor is not None:
        os.replace(
            source.name,
            target.name,
            src_dir_fd=descriptor,
            dst_dir_fd=descriptor,
        )
        return
    replace_private_file(source, target)


def _chmod_active_entry(path: Path, mode: int) -> None:
    target = Path(path)
    _assert_active_directory_target(target)
    descriptor = _active_posix_directory_descriptor()
    if descriptor is not None:
        os.chmod(
            target.name,
            mode,
            dir_fd=descriptor,
            follow_symlinks=False,
        )
        return
    os.chmod(target, mode)


def _unlink_active_entry(
    path: Path,
    *,
    missing_ok: bool = False,
    require_current_path: bool = True,
) -> None:
    target = Path(path)
    binding = getattr(_ACTIVE_DIRECTORY, "binding", None)
    if not isinstance(binding, _ActiveDirectoryBinding) or (
        os.path.normcase(str(target.absolute().parent))
        != os.path.normcase(str(binding.root))
    ):
        raise IdentityConfigurationError(
            "identity directory changed while locked"
        )
    if require_current_path:
        _assert_active_directory_path(binding.root)
    descriptor = _active_posix_directory_descriptor()
    try:
        if descriptor is not None:
            os.unlink(target.name, dir_fd=descriptor)
        else:
            target.unlink()
    except FileNotFoundError:
        if not missing_ok:
            raise


def _active_directory_entries(root: Path) -> list[Path]:
    _assert_active_directory_path(root)
    descriptor = _active_posix_directory_descriptor()
    if descriptor is None:
        return list(root.iterdir())
    with os.scandir(descriptor) as entries:
        names = [entry.name for entry in entries]
    return [root / name for name in names]


def _secure_regular_entry(metadata: os.stat_result) -> bool:
    return (
        stat.S_ISREG(metadata.st_mode)
        and not _is_reparse_point(metadata)
        and metadata.st_nlink == 1
        and (
            os.name == "nt"
            or metadata.st_uid == os.geteuid()
        )
    )


def _private_directory_permissions_are_secure(path: Path) -> bool:
    return private_directory_permissions_are_secure(path)


def _validate_lifetime(value: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not _MIN_TOKEN_LIFETIME_SECONDS
        <= value
        <= _MAX_TOKEN_LIFETIME_SECONDS
    ):
        raise ValueError("demo token lifetime must be between 60 and 900 seconds")


def _now_epoch() -> int:
    return int(time.time())


def _base64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _is_reparse_point(metadata: os.stat_result) -> bool:
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(attributes & reparse)


__all__ = [
    "DemoIdentityStatus",
    "EMERGENCY_RETIRE_CONFIRMATION",
    "activate_demo_identity",
    "demo_identity_status",
    "initialize_demo_identity",
    "retire_demo_identity_key",
    "rotate_demo_identity",
]
