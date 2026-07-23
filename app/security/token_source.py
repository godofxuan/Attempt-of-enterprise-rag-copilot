from __future__ import annotations

import hmac
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.security.identity import (
    IdentityConfigurationError,
    read_private_file_snapshot,
    verify_committed_identity_artifact,
)


_COMPACT_TOKEN = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_PERSONA_ID = re.compile(r"[A-Za-z0-9._:@/-]{1,200}")


class BearerTokenSource(Protocol):
    def get_token(self) -> str: ...


@dataclass(frozen=True)
class StaticBearerTokenSource:
    _token: str = field(repr=False)

    def __post_init__(self) -> None:
        _validate_token(self._token)

    def get_token(self) -> str:
        return self._token


@dataclass(frozen=True)
class BearerTokenFileSource:
    path: Path = field(repr=False)
    max_bytes: int = 16_384
    allow_standalone: bool = False

    def get_token(self) -> str:
        raw = read_private_file_snapshot(Path(self.path), max_bytes=self.max_bytes)
        verify_committed_identity_artifact(
            Path(self.path),
            raw,
            allow_standalone=self.allow_standalone,
        )
        return _decode_token_file(raw)


@dataclass(frozen=True)
class PersonaTokenBundleSource:
    path: Path = field(repr=False)
    max_bytes: int = 65_536
    allow_standalone: bool = False

    def get_token(self, persona_id: str) -> str:
        if not isinstance(persona_id, str) or not _PERSONA_ID.fullmatch(persona_id):
            raise IdentityConfigurationError("persona token is unavailable")
        tokens = self._load_tokens()
        try:
            return tokens[persona_id]
        except KeyError:
            raise IdentityConfigurationError("persona token is unavailable") from None

    def _load_tokens(self) -> dict[str, str]:
        raw = read_private_file_snapshot(Path(self.path), max_bytes=self.max_bytes)
        verify_committed_identity_artifact(
            Path(self.path),
            raw,
            allow_standalone=self.allow_standalone,
        )
        try:
            payload = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_unique_object,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise IdentityConfigurationError("persona token bundle is invalid") from None
        if not isinstance(payload, dict) or set(payload) != {
            "schema_version",
            "tokens",
        }:
            raise IdentityConfigurationError("persona token bundle is invalid")
        if payload["schema_version"] != "persona-token-bundle-v1":
            raise IdentityConfigurationError("persona token bundle is invalid")
        tokens = payload["tokens"]
        if not isinstance(tokens, dict) or not 1 <= len(tokens) <= 50:
            raise IdentityConfigurationError("persona token bundle is invalid")
        if any(
            not isinstance(key, str)
            or not _PERSONA_ID.fullmatch(key)
            or not isinstance(value, str)
            for key, value in tokens.items()
        ):
            raise IdentityConfigurationError("persona token bundle is invalid")
        for token in tokens.values():
            _validate_token(token)
        return tokens


def resolve_single_token_source(
    *,
    token: str | None,
    token_file: Path | None,
) -> BearerTokenSource:
    configured = int(token is not None) + int(token_file is not None)
    if configured != 1:
        raise ValueError("configure exactly one bearer token source")
    if token is not None:
        return StaticBearerTokenSource(token)
    return BearerTokenFileSource(
        Path(token_file),
        allow_standalone=True,
    )


def ensure_distinct_bearer_token_sources(
    user_source: BearerTokenSource,
    operator_source: BearerTokenSource,
) -> None:
    user_token = user_source.get_token()
    operator_token = operator_source.get_token()
    if hmac.compare_digest(user_token, operator_token):
        raise IdentityConfigurationError(
            "user and operator bearer tokens must differ"
        )


def ensure_distinct_persona_operator_token_sources(
    persona_source: PersonaTokenBundleSource,
    operator_source: BearerTokenSource,
) -> None:
    operator_token = operator_source.get_token()
    matches = 0
    for persona_token in persona_source._load_tokens().values():
        matches |= int(hmac.compare_digest(persona_token, operator_token))
    if matches:
        raise IdentityConfigurationError(
            "persona and operator bearer tokens must differ"
        )


def _decode_token_file(raw: bytes) -> str:
    if raw.endswith(b"\r\n"):
        raw = raw[:-2]
    elif raw.endswith(b"\n"):
        raw = raw[:-1]
    try:
        token = raw.decode("ascii")
    except UnicodeDecodeError:
        raise IdentityConfigurationError("bearer token file is invalid") from None
    _validate_token(token)
    return token


def _validate_token(token: str) -> None:
    if (
        not isinstance(token, str)
        or not 1 <= len(token) <= 16_384
        or not token.isascii()
        or not _COMPACT_TOKEN.fullmatch(token)
    ):
        raise IdentityConfigurationError("bearer token is invalid")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


__all__ = [
    "BearerTokenFileSource",
    "BearerTokenSource",
    "ensure_distinct_bearer_token_sources",
    "ensure_distinct_persona_operator_token_sources",
    "PersonaTokenBundleSource",
    "StaticBearerTokenSource",
    "resolve_single_token_source",
]
