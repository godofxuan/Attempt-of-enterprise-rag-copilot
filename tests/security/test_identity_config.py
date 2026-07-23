from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import BASE_DIR, Settings


def test_identity_settings_default_to_pinned_local_jwks_contract() -> None:
    settings = Settings(_env_file=None)

    assert settings.identity_jwks_path == (
        BASE_DIR / ".private" / "identity" / "jwks.json"
    ).resolve()
    assert settings.identity_feedback_hmac_key_path == (
        BASE_DIR / ".private" / "identity" / "feedback_actor_hmac.key"
    ).resolve()
    assert settings.identity_issuer == "https://identity.localhost/"
    assert settings.identity_audience == "enterprise-rag-api"
    assert settings.identity_algorithm == "RS256"
    assert settings.identity_token_type == "at+jwt"
    assert settings.identity_operator_role == "rag.operator"
    assert settings.identity_clock_skew_seconds == 30
    assert settings.identity_max_token_lifetime_seconds == 900
    assert settings.identity_max_token_bytes == 8_192
    assert settings.identity_jwks_max_bytes == 65_536
    assert settings.identity_jwks_max_keys == 8
    assert settings.identity_feedback_hmac_key_max_bytes == 256


@pytest.mark.parametrize(
    "issuer",
    [
        "",
        "not-a-url",
        "http://identity.localhost/",
        "https://user@identity.invalid/",
        "https://identity.localhost/?source=attacker",
        "https://identity.localhost/#fragment",
    ],
)
def test_identity_settings_reject_unsafe_issuer(issuer: str) -> None:
    with pytest.raises(ValidationError, match="identity issuer"):
        Settings(_env_file=None, identity_issuer=issuer)


def test_relative_identity_jwks_path_resolves_under_private_directory() -> None:
    settings = Settings(
        _env_file=None,
        identity_jwks_path=".private/rotated-identity/jwks.json",
    )

    assert settings.identity_jwks_path == (
        BASE_DIR / ".private" / "rotated-identity" / "jwks.json"
    ).resolve()


def test_identity_jwks_path_inside_repository_must_be_private() -> None:
    with pytest.raises(ValidationError, match="identity private file path"):
        Settings(
            _env_file=None,
            identity_jwks_path=BASE_DIR / "data" / "public-jwks.json",
        )


@pytest.mark.parametrize(
    "audience",
    ["", " enterprise-rag-api", "a" * 201, "aud ience", "aud\x00ience"],
)
def test_identity_settings_reject_invalid_audience(audience: str) -> None:
    with pytest.raises(ValidationError, match="identity audience"):
        Settings(_env_file=None, identity_audience=audience)


def test_identity_operator_role_is_not_runtime_configurable() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, identity_operator_role="tenant.admin")


def test_feedback_hmac_path_inside_repository_must_be_private() -> None:
    with pytest.raises(ValidationError, match="identity private file path"):
        Settings(
            _env_file=None,
            identity_feedback_hmac_key_path=BASE_DIR / "data" / "actor.key",
        )


def test_identity_config_preserves_symlink_for_runtime_rejection(tmp_path) -> None:
    target = tmp_path / "target.json"
    target.write_text('{"keys":[]}', encoding="utf-8")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is not available")

    settings = Settings(_env_file=None, identity_jwks_path=link)

    assert settings.identity_jwks_path == link.absolute()
