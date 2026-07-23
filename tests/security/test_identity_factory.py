from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.security.identity import (
    IdentityConfigurationError,
    build_feedback_actor_hasher,
    build_identity_verifier,
)
from app.security.demo_identity import initialize_demo_identity
from app.security.token_source import BearerTokenFileSource


def test_identity_factories_load_valid_private_runtime_artifacts(tmp_path: Path) -> None:
    initialize_demo_identity(
        tmp_path,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    settings = Settings(
        _env_file=None,
        identity_jwks_path=tmp_path / "jwks.json",
        identity_feedback_hmac_key_path=tmp_path / "feedback_actor_hmac.key",
    )

    verifier = build_identity_verifier(settings)
    hasher = build_feedback_actor_hasher(settings)
    token = BearerTokenFileSource(tmp_path / "load_user_token.txt").get_token()
    principal = verifier.verify_bearer(f"Bearer {token}")

    verifier.ready()
    hasher.ready()
    assert principal.subject == "load-demo-employee"
    assert len(hasher.pseudonym(principal)) == 64


def test_identity_factories_degrade_to_unavailable_without_leaking_paths(
    tmp_path: Path,
) -> None:
    secret_path = tmp_path / "PROJECT_NIGHTFALL" / "missing.json"
    settings = Settings(
        _env_file=None,
        identity_jwks_path=secret_path,
        identity_feedback_hmac_key_path=secret_path.with_suffix(".key"),
    )

    verifier = build_identity_verifier(settings)
    hasher = build_feedback_actor_hasher(settings)

    with pytest.raises(IdentityConfigurationError) as verifier_error:
        verifier.ready()
    with pytest.raises(IdentityConfigurationError) as hasher_error:
        hasher.ready()
    assert "NIGHTFALL" not in str(verifier_error.value)
    assert "NIGHTFALL" not in str(hasher_error.value)
