from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Mapping, Protocol

import jwt
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.queries import UserContext
from app.security.private_fs import (
    PrivatePathError,
    validate_private_directory_permissions,
)

if TYPE_CHECKING:
    from app.config import Settings


_RSA_PRIVATE_MEMBERS = frozenset({"d", "p", "q", "dp", "dq", "qi", "oth"})
_IDENTITY_VALUE = re.compile(r"^[A-Za-z0-9._:@/-]+$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_HMAC_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMITTED_IDENTITY_SCHEMA = "demo-identity-keyring-v3"
_PREVIOUS_IDENTITY_SCHEMA = "demo-identity-keyring-v2"
_LEGACY_IDENTITY_SCHEMA = "demo-identity-keyring-v1"
_IDENTITY_MANIFEST_FILE = "identity_manifest.json"
_IDENTITY_OPERATION_FILE = ".identity-operation.json"
AuthenticationCode = Literal[
    "authentication_required",
    "invalid_token",
    "identity_unavailable",
]


class IdentityConfigurationError(RuntimeError):
    pass


class AuthenticationFailure(RuntimeError):
    def __init__(self, code: AuthenticationCode) -> None:
        super().__init__("token authentication failed")
        self.code = code


class Principal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    subject: str = Field(min_length=1, max_length=200)
    tenant_id: str = Field(min_length=1, max_length=200)
    region: str = Field(min_length=1, max_length=100)
    groups: list[str] = Field(min_length=1, max_length=50)
    roles: list[str] = Field(default_factory=list, max_length=50)
    issuer: str = Field(min_length=1, max_length=500)
    audience: str = Field(min_length=1, max_length=200)
    key_id: str = Field(min_length=1, max_length=128)
    issued_at: datetime
    expires_at: datetime

    @field_validator("subject", "tenant_id", "region", "key_id")
    @classmethod
    def validate_identity_value(cls, value: str) -> str:
        if value != value.strip() or not _IDENTITY_VALUE.fullmatch(value):
            raise ValueError("identity value is invalid")
        return value

    @field_validator("groups", "roles")
    @classmethod
    def validate_identity_list(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("identity list values must be unique")
        if any(
            not isinstance(value, str)
            or not 1 <= len(value) <= 200
            or value != value.strip()
            or not _IDENTITY_VALUE.fullmatch(value)
            for value in values
        ):
            raise ValueError("identity list value is invalid")
        return values

    @model_validator(mode="after")
    def validate_time_window(self) -> Principal:
        if self.expires_at <= self.issued_at:
            raise ValueError("identity token expiry must follow issuance")
        return self

    def to_user_context(self) -> UserContext:
        return UserContext(
            user_id=self.subject,
            tenant_id=self.tenant_id,
            region=self.region,
            groups=list(self.groups),
            roles=[],
        )


class IdentityVerifier(Protocol):
    def verify_bearer(self, authorization: str | None) -> Principal: ...

    def ready(self) -> None: ...


class FeedbackActorPseudonymizer(Protocol):
    def pseudonym(self, principal: Principal) -> str: ...

    def content_digest(self, kind: Literal["question", "answer"], value: str) -> str: ...

    def issue_feedback_receipt(
        self,
        principal: Principal,
        *,
        target_request_id: str,
        question: str,
        answer: str,
    ) -> str: ...

    def verify_feedback_receipt(
        self,
        principal: Principal,
        *,
        target_request_id: str,
        question: str,
        answer: str,
        receipt: str,
    ) -> bool: ...

    def ready(self) -> None: ...


@dataclass(frozen=True)
class FeedbackActorHasher:
    _key: bytes = field(repr=False)

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        max_bytes: int,
        allow_standalone: bool = False,
    ) -> FeedbackActorHasher:
        raw = read_private_file_snapshot(Path(path), max_bytes=max_bytes)
        verify_committed_identity_artifact(
            Path(path),
            raw,
            allow_standalone=allow_standalone,
        )
        if len(raw) < 32:
            raise IdentityConfigurationError("feedback actor HMAC key is too short")
        return cls(_key=raw)

    def ready(self) -> None:
        if len(self._key) < 32:
            raise IdentityConfigurationError("feedback actor hasher is unavailable")

    def pseudonym(self, principal: Principal) -> str:
        return self._digest(
            b"r2-s5-feedback-actor-v1",
            principal.issuer,
            principal.subject,
        )

    def content_digest(
        self,
        kind: Literal["question", "answer"],
        value: str,
    ) -> str:
        if kind not in {"question", "answer"} or not isinstance(value, str):
            raise ValueError("feedback content digest input is invalid")
        return self._digest(b"r2-s5-feedback-content-v1", kind, value)

    def issue_feedback_receipt(
        self,
        principal: Principal,
        *,
        target_request_id: str,
        question: str,
        answer: str,
    ) -> str:
        _validate_feedback_binding_input(target_request_id, question, answer)
        return self._digest(
            b"r2-s5-feedback-receipt-v1",
            principal.issuer,
            principal.audience,
            principal.tenant_id,
            principal.subject,
            target_request_id,
            self.content_digest("question", question),
            self.content_digest("answer", answer),
        )

    def verify_feedback_receipt(
        self,
        principal: Principal,
        *,
        target_request_id: str,
        question: str,
        answer: str,
        receipt: str,
    ) -> bool:
        if not isinstance(receipt, str) or not _HMAC_SHA256.fullmatch(receipt):
            return False
        try:
            expected = self.issue_feedback_receipt(
                principal,
                target_request_id=target_request_id,
                question=question,
                answer=answer,
            )
        except ValueError:
            return False
        return hmac.compare_digest(expected, receipt)

    def _digest(self, domain: bytes, *values: str) -> str:
        message = bytearray(domain)
        for value in values:
            encoded = value.encode("utf-8")
            message.extend(len(encoded).to_bytes(4, "big"))
            message.extend(encoded)
        return hmac.new(self._key, bytes(message), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class UnavailableFeedbackActorHasher:
    def ready(self) -> None:
        raise IdentityConfigurationError("feedback actor hasher is unavailable")

    def pseudonym(self, principal: Principal) -> str:
        raise IdentityConfigurationError("feedback actor hasher is unavailable")

    def content_digest(
        self,
        kind: Literal["question", "answer"],
        value: str,
    ) -> str:
        raise IdentityConfigurationError("feedback actor hasher is unavailable")

    def issue_feedback_receipt(
        self,
        principal: Principal,
        *,
        target_request_id: str,
        question: str,
        answer: str,
    ) -> str:
        raise IdentityConfigurationError("feedback actor hasher is unavailable")

    def verify_feedback_receipt(
        self,
        principal: Principal,
        *,
        target_request_id: str,
        question: str,
        answer: str,
        receipt: str,
    ) -> bool:
        raise IdentityConfigurationError("feedback actor hasher is unavailable")


@dataclass(frozen=True)
class LocalJwksKeyProvider:
    path: Path
    _keys: Mapping[str, jwt.PyJWK]

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        max_bytes: int,
        max_keys: int,
        allow_standalone: bool = False,
    ) -> LocalJwksKeyProvider:
        if max_bytes < 1 or max_keys < 1:
            raise ValueError("JWKS limits must be positive")
        source = Path(path)
        raw = read_private_file_snapshot(source, max_bytes=max_bytes)
        verify_committed_identity_artifact(
            source,
            raw,
            allow_standalone=allow_standalone,
        )
        try:
            payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise IdentityConfigurationError("identity JWKS is invalid") from None
        if not isinstance(payload, dict) or set(payload) != {"keys"}:
            raise IdentityConfigurationError("identity JWKS is invalid")
        entries = payload["keys"]
        if not isinstance(entries, list) or not 1 <= len(entries) <= max_keys:
            raise IdentityConfigurationError("identity JWKS key count is invalid")

        keys: dict[str, jwt.PyJWK] = {}
        for entry in entries:
            kid, parsed = _parse_public_rsa_jwk(entry)
            if kid in keys:
                raise IdentityConfigurationError("identity JWKS key IDs must be unique")
            keys[kid] = parsed
        return cls(
            path=source.resolve(),
            _keys=MappingProxyType(keys),
        )

    @property
    def key_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._keys))

    def get(self, kid: str) -> jwt.PyJWK:
        try:
            return self._keys[kid]
        except KeyError:
            raise AuthenticationFailure("invalid_token") from None


@dataclass(frozen=True)
class LocalJwtIdentityVerifier:
    provider: LocalJwksKeyProvider
    issuer: str
    audience: str
    algorithm: str
    token_type: str
    clock_skew_seconds: int
    max_lifetime_seconds: int
    max_token_bytes: int

    def ready(self) -> None:
        if not self.provider.key_ids:
            raise IdentityConfigurationError("identity verifier is unavailable")

    def verify_bearer(self, authorization: str | None) -> Principal:
        token = _extract_bearer_token(authorization, self.max_token_bytes)
        try:
            header, _ = _parse_compact_jwt(token)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise AuthenticationFailure("invalid_token") from None
        if set(header) != {"alg", "kid", "typ"}:
            raise AuthenticationFailure("invalid_token")
        if (
            header.get("alg") != self.algorithm
            or header.get("typ") != self.token_type
            or not isinstance(header.get("kid"), str)
            or not 1 <= len(header["kid"]) <= 128
            or not header["kid"].isascii()
            or not _IDENTITY_VALUE.fullmatch(header["kid"])
        ):
            raise AuthenticationFailure("invalid_token")
        kid = header["kid"]
        key = self.provider.get(kid)
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=[self.algorithm],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.clock_skew_seconds,
                options={
                    "require": [
                        "aud",
                        "exp",
                        "groups",
                        "iat",
                        "iss",
                        "region",
                        "roles",
                        "sub",
                        "tenant_id",
                    ],
                    "strict_aud": True,
                },
            )
            return self._principal_from_claims(claims, kid=kid)
        except (jwt.PyJWTError, ValueError, TypeError):
            raise AuthenticationFailure("invalid_token") from None

    def _principal_from_claims(
        self,
        claims: Mapping[str, Any],
        *,
        kid: str,
    ) -> Principal:
        issued_at = _strict_numeric_date(claims.get("iat"))
        expires_at = _strict_numeric_date(claims.get("exp"))
        if "nbf" in claims:
            _strict_numeric_date(claims["nbf"])
        if not 0 < expires_at - issued_at <= self.max_lifetime_seconds:
            raise ValueError("token lifetime is invalid")
        groups = _strict_string_list(claims.get("groups"), required=True)
        roles = _strict_string_list(claims.get("roles"), required=False)
        return Principal(
            subject=_strict_string(claims.get("sub")),
            tenant_id=_strict_string(claims.get("tenant_id")),
            region=_strict_string(claims.get("region")),
            groups=groups,
            roles=roles,
            issuer=_strict_string(claims.get("iss")),
            audience=_strict_string(claims.get("aud")),
            key_id=kid,
            issued_at=datetime.fromtimestamp(issued_at, tz=timezone.utc),
            expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
        )


@dataclass(frozen=True)
class UnavailableIdentityVerifier:
    def ready(self) -> None:
        raise IdentityConfigurationError("identity verifier is unavailable")

    def verify_bearer(self, authorization: str | None) -> Principal:
        raise AuthenticationFailure("identity_unavailable")


def build_identity_verifier(settings: Settings) -> IdentityVerifier:
    try:
        provider = LocalJwksKeyProvider.load(
            settings.identity_jwks_path,
            max_bytes=settings.identity_jwks_max_bytes,
            max_keys=settings.identity_jwks_max_keys,
        )
        return LocalJwtIdentityVerifier(
            provider=provider,
            issuer=settings.identity_issuer,
            audience=settings.identity_audience,
            algorithm=settings.identity_algorithm,
            token_type=settings.identity_token_type,
            clock_skew_seconds=settings.identity_clock_skew_seconds,
            max_lifetime_seconds=settings.identity_max_token_lifetime_seconds,
            max_token_bytes=settings.identity_max_token_bytes,
        )
    except IdentityConfigurationError:
        return UnavailableIdentityVerifier()


def build_feedback_actor_hasher(settings: Settings) -> FeedbackActorPseudonymizer:
    try:
        return FeedbackActorHasher.load(
            settings.identity_feedback_hmac_key_path,
            max_bytes=settings.identity_feedback_hmac_key_max_bytes,
        )
    except IdentityConfigurationError:
        return UnavailableFeedbackActorHasher()


def _parse_public_rsa_jwk(value: Any) -> tuple[str, jwt.PyJWK]:
    if not isinstance(value, dict):
        raise IdentityConfigurationError("identity JWKS key is invalid")
    if _RSA_PRIVATE_MEMBERS.intersection(value):
        raise IdentityConfigurationError("identity JWKS must contain public keys only")
    kid = value.get("kid")
    if (
        not isinstance(kid, str)
        or not 1 <= len(kid) <= 128
        or kid != kid.strip()
        or not kid.isascii()
        or not _IDENTITY_VALUE.fullmatch(kid)
    ):
        raise IdentityConfigurationError("identity JWKS key ID is invalid")
    if value.get("kty") != "RSA" or value.get("alg") != "RS256":
        raise IdentityConfigurationError("identity JWKS key type is invalid")
    if value.get("use", "sig") != "sig":
        raise IdentityConfigurationError("identity JWKS key use is invalid")
    key_ops = value.get("key_ops", ["verify"])
    if key_ops != ["verify"]:
        raise IdentityConfigurationError("identity JWKS key operations are invalid")
    try:
        parsed = jwt.PyJWK.from_dict(value, algorithm="RS256")
    except Exception:
        raise IdentityConfigurationError("identity JWKS key is invalid") from None
    key_size = getattr(parsed.key, "key_size", 0)
    if not isinstance(key_size, int) or key_size < 2_048:
        raise IdentityConfigurationError("identity JWKS RSA key is too small")
    return kid, parsed


def _extract_bearer_token(authorization: str | None, max_token_bytes: int) -> str:
    if authorization is None:
        raise AuthenticationFailure("authentication_required")
    if not isinstance(authorization, str) or any(
        character in authorization for character in "\r\n\t"
    ):
        raise AuthenticationFailure("invalid_token")
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].casefold() != "bearer" or not parts[1]:
        raise AuthenticationFailure("invalid_token")
    token = parts[1]
    if len(token.encode("ascii", errors="ignore")) != len(token) or not (
        1 <= len(token) <= max_token_bytes
    ):
        raise AuthenticationFailure("invalid_token")
    return token


def _parse_compact_jwt(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    segments = token.split(".")
    if len(segments) != 3 or any(not segment for segment in segments):
        raise ValueError("JWT compact serialization is invalid")
    header = _decode_unique_json_object(segments[0])
    payload = _decode_unique_json_object(segments[1])
    _decode_base64url_segment(segments[2])
    return header, payload


def _decode_unique_json_object(segment: str) -> dict[str, Any]:
    value = json.loads(
        _decode_base64url_segment(segment).decode("utf-8"),
        object_pairs_hook=_unique_object,
    )
    if not isinstance(value, dict):
        raise ValueError("JWT segment must contain a JSON object")
    return value


def _decode_base64url_segment(segment: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", segment):
        raise ValueError("JWT segment is not base64url")
    padded = segment + "=" * (-len(segment) % 4)
    try:
        decoded = base64.b64decode(
            padded.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError):
        raise ValueError("JWT segment is not base64url") from None
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if canonical != segment:
        raise ValueError("JWT segment is not canonical base64url")
    return decoded


def _strict_string(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("identity claim must be a string")
    return value


def _strict_string_list(value: Any, *, required: bool) -> list[str]:
    if not isinstance(value, list) or (required and not value):
        raise ValueError("identity claim must be a string list")
    if any(not isinstance(item, str) for item in value):
        raise ValueError("identity claim must be a string list")
    return list(value)


def _strict_numeric_date(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("identity timestamp must be an integer")
    return value


def _validate_feedback_binding_input(
    target_request_id: str,
    question: str,
    answer: str,
) -> None:
    if not isinstance(target_request_id, str) or not _REQUEST_ID.fullmatch(
        target_request_id
    ):
        raise ValueError("feedback target request ID is invalid")
    if not isinstance(question, str) or not 1 <= len(question) <= 2_000:
        raise ValueError("feedback question is invalid")
    if not isinstance(answer, str) or not 1 <= len(answer) <= 20_000:
        raise ValueError("feedback answer is invalid")


def read_private_file_snapshot(path: Path, *, max_bytes: int) -> bytes:
    lexical = Path(path).absolute()
    validate_private_path_ancestors(lexical)
    try:
        before_path = lexical.lstat()
    except OSError:
        raise IdentityConfigurationError("identity private file is unavailable") from None
    if (
        not stat.S_ISREG(before_path.st_mode)
        or _is_reparse_point(before_path)
        or before_path.st_nlink != 1
        or (
            os.name != "nt"
            and before_path.st_uid != os.geteuid()
        )
    ):
        raise IdentityConfigurationError("identity private file must be a regular file")
    if before_path.st_size > max_bytes:
        raise IdentityConfigurationError("identity private file exceeds the size limit")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lexical, flags)
    except OSError:
        raise IdentityConfigurationError("identity private file is unavailable") from None
    try:
        before_descriptor = os.fstat(descriptor)
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after_descriptor = os.fstat(descriptor)
    except OSError:
        raise IdentityConfigurationError("identity private file is unavailable") from None
    finally:
        os.close(descriptor)

    raw = b"".join(chunks)
    if len(raw) > max_bytes:
        raise IdentityConfigurationError("identity private file exceeds the size limit")
    try:
        after_path = lexical.lstat()
    except OSError:
        raise IdentityConfigurationError("identity private file changed while loading") from None
    if not (
        _same_file(before_path, before_descriptor)
        and _same_file(before_descriptor, after_descriptor)
        and _same_file(after_descriptor, after_path)
    ):
        raise IdentityConfigurationError("identity private file changed while loading")
    return raw


def validate_private_path_ancestors(
    path: Path,
    *,
    allow_missing: bool = False,
) -> None:
    lexical = Path(path).absolute()
    missing_seen = False
    for component in reversed(lexical.parents):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            if allow_missing:
                missing_seen = True
                continue
            raise IdentityConfigurationError(
                "identity private path is unavailable"
            ) from None
        except OSError:
            raise IdentityConfigurationError(
                "identity private path is unavailable"
            ) from None
        if missing_seen or not stat.S_ISDIR(metadata.st_mode) or _is_reparse_point(
            metadata
        ) or stat.S_ISLNK(metadata.st_mode):
            raise IdentityConfigurationError("identity private path is unsafe")
        if os.name != "nt":
            owner = metadata.st_uid
            mode = stat.S_IMODE(metadata.st_mode)
            trusted_owner = owner in {0, os.geteuid()}
            writable_by_others = bool(mode & 0o022)
            sticky_directory = bool(mode & stat.S_ISVTX)
            if (
                not trusted_owner
                or (writable_by_others and not sticky_directory)
            ):
                raise IdentityConfigurationError(
                    "identity private path is unsafe"
                )


def verify_committed_identity_artifact(
    path: Path,
    payload: bytes,
    *,
    allow_standalone: bool = False,
) -> None:
    source = Path(path).absolute()
    if source.name == _IDENTITY_MANIFEST_FILE:
        raise IdentityConfigurationError("identity artifact set is not committed")
    manifest_path = source.parent / _IDENTITY_MANIFEST_FILE
    journal_path = source.parent / _IDENTITY_OPERATION_FILE
    try:
        manifest_path.lstat()
    except FileNotFoundError:
        try:
            journal_path.lstat()
        except FileNotFoundError:
            if not allow_standalone:
                raise IdentityConfigurationError(
                    "identity artifact set is not committed"
                ) from None
            try:
                validate_private_directory_permissions(source.parent)
            except PrivatePathError:
                raise IdentityConfigurationError(
                    "identity private directory permissions are unsafe"
                ) from None
            return
        except OSError:
            raise IdentityConfigurationError(
                "identity artifact commit metadata is unavailable"
            ) from None
        raise IdentityConfigurationError("identity artifact set is not committed")
    except OSError:
        raise IdentityConfigurationError(
            "identity artifact commit metadata is unavailable"
        ) from None
    try:
        validate_private_directory_permissions(source.parent)
    except PrivatePathError:
        raise IdentityConfigurationError(
            "identity private directory permissions are unsafe"
        ) from None
    manifest_raw = read_private_file_snapshot(manifest_path, max_bytes=131_072)
    try:
        manifest = json.loads(
            manifest_raw.decode("ascii"),
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise IdentityConfigurationError(
            "identity artifact commit metadata is invalid"
        ) from None
    if not isinstance(manifest, dict):
        raise IdentityConfigurationError(
            "identity artifact commit metadata is invalid"
        )
    schema = manifest.get("schema_version")
    if schema in {_LEGACY_IDENTITY_SCHEMA, _PREVIOUS_IDENTITY_SCHEMA}:
        raise IdentityConfigurationError(
            "legacy identity artifacts require a managed upgrade"
        )
    artifacts = manifest.get("artifacts")
    if schema != _COMMITTED_IDENTITY_SCHEMA or not isinstance(artifacts, dict):
        raise IdentityConfigurationError(
            "identity artifact commit metadata is invalid"
        )
    expected = artifacts.get(source.name)
    actual = hashlib.sha256(payload).hexdigest()
    if (
        not isinstance(expected, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected)
        or not hmac.compare_digest(expected, actual)
    ):
        raise IdentityConfigurationError("identity artifact set is not committed")


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_size,
        left.st_mtime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_size,
        right.st_mtime_ns,
    )


def _is_reparse_point(metadata: os.stat_result) -> bool:
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(attributes & reparse)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


__all__ = [
    "AuthenticationFailure",
    "FeedbackActorHasher",
    "FeedbackActorPseudonymizer",
    "IdentityVerifier",
    "IdentityConfigurationError",
    "LocalJwksKeyProvider",
    "LocalJwtIdentityVerifier",
    "Principal",
    "UnavailableFeedbackActorHasher",
    "UnavailableIdentityVerifier",
    "build_feedback_actor_hasher",
    "build_identity_verifier",
    "read_private_file_snapshot",
    "validate_private_path_ancestors",
    "verify_committed_identity_artifact",
]
