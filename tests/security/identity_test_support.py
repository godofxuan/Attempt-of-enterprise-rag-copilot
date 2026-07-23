from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric import rsa

from app.security.private_fs import harden_private_directory


def generate_rsa_jwk(
    *,
    kid: str = "test-key-1",
    key_size: int = 2_048,
) -> tuple[rsa.RSAPrivateKey, dict[str, object]]:
    private_key = rsa.generate_private_key(
        public_exponent=65_537,
        key_size=key_size,
    )
    numbers = private_key.public_key().public_numbers()
    return private_key, {
        "alg": "RS256",
        "e": _base64url_uint(numbers.e),
        "key_ops": ["verify"],
        "kid": kid,
        "kty": "RSA",
        "n": _base64url_uint(numbers.n),
        "use": "sig",
    }


def write_jwks(path: Path, keys: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"keys": keys}, ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )
    harden_private_directory(path.parent)
    return path


def write_standalone_private_file(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    harden_private_directory(path.parent)
    return path


def issue_token(
    private_key: rsa.RSAPrivateKey,
    *,
    kid: str = "test-key-1",
    issuer: str = "https://identity.localhost/",
    audience: str = "enterprise-rag-api",
    subject: str = "user_employee",
    tenant_id: str = "starbridge-cn",
    region: str = "cn",
    groups: list[str] | None = None,
    roles: list[str] | None = None,
    issued_at: int | None = None,
    expires_at: int | None = None,
    headers: dict[str, object] | None = None,
    claims: dict[str, object] | None = None,
    drop_claims: set[str] | None = None,
) -> str:
    now = int(time.time()) if issued_at is None else issued_at
    payload: dict[str, object] = {
        "aud": audience,
        "exp": now + 300 if expires_at is None else expires_at,
        "groups": groups or ["all_employees"],
        "iat": now,
        "iss": issuer,
        "region": region,
        "roles": roles or [],
        "sub": subject,
        "tenant_id": tenant_id,
    }
    if claims:
        payload.update(claims)
    for claim in drop_claims or set():
        payload.pop(claim, None)
    token_headers: dict[str, object] = {
        "alg": "RS256",
        "kid": kid,
        "typ": "at+jwt",
    }
    if headers:
        token_headers.update(headers)
    return jwt.encode(
        payload,
        private_key,
        algorithm="RS256",
        headers=token_headers,
    )


def sign_raw_jws(
    private_key: rsa.RSAPrivateKey,
    *,
    header_json: str,
    payload_json: str,
) -> str:
    header = _base64url_bytes(header_json.encode("utf-8"))
    payload = _base64url_bytes(payload_json.encode("utf-8"))
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = private_key.sign(
        signing_input,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return f"{header}.{payload}.{_base64url_bytes(signature)}"


def _base64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return _base64url_bytes(raw)


def _base64url_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
