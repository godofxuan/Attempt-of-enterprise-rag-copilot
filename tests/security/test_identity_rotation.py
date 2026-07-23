from __future__ import annotations

from pathlib import Path

import pytest

from app.security.identity import AuthenticationFailure, LocalJwksKeyProvider, LocalJwtIdentityVerifier
from tests.security.identity_test_support import generate_rsa_jwk, issue_token, write_jwks


def _verifier(path: Path) -> LocalJwtIdentityVerifier:
    return LocalJwtIdentityVerifier(
        provider=LocalJwksKeyProvider.load(
            path,
            max_bytes=65_536,
            max_keys=8,
            allow_standalone=True,
        ),
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        algorithm="RS256",
        token_type="at+jwt",
        clock_skew_seconds=30,
        max_lifetime_seconds=900,
        max_token_bytes=8_192,
    )


def test_jwks_rotation_requires_rebuild_and_supports_overlap_then_retirement(
    tmp_path: Path,
) -> None:
    old_private, old_public = generate_rsa_jwk(kid="old-key")
    new_private, new_public = generate_rsa_jwk(kid="new-key")
    path = write_jwks(tmp_path / "jwks.json", [old_public])
    old_snapshot = _verifier(path)
    old_token = issue_token(old_private, kid="old-key")
    new_token = issue_token(new_private, kid="new-key")

    assert old_snapshot.verify_bearer(f"Bearer {old_token}").key_id == "old-key"

    write_jwks(path, [old_public, new_public])
    with pytest.raises(AuthenticationFailure):
        old_snapshot.verify_bearer(f"Bearer {new_token}")

    overlap_snapshot = _verifier(path)
    assert overlap_snapshot.verify_bearer(f"Bearer {old_token}").key_id == "old-key"
    assert overlap_snapshot.verify_bearer(f"Bearer {new_token}").key_id == "new-key"

    write_jwks(path, [new_public])
    retired_snapshot = _verifier(path)
    with pytest.raises(AuthenticationFailure):
        retired_snapshot.verify_bearer(f"Bearer {old_token}")
    assert retired_snapshot.verify_bearer(f"Bearer {new_token}").key_id == "new-key"
