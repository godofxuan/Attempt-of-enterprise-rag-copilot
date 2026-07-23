from __future__ import annotations

import time
import base64
from pathlib import Path

import pytest

from app.security.identity import (
    AuthenticationFailure,
    LocalJwksKeyProvider,
    LocalJwtIdentityVerifier,
)
from tests.security.identity_test_support import (
    generate_rsa_jwk,
    issue_token,
    sign_raw_jws,
    write_jwks,
)


def test_valid_bearer_token_derives_server_owned_principal_and_user_context(
    tmp_path: Path,
) -> None:
    private_key, public_jwk = generate_rsa_jwk()
    provider = LocalJwksKeyProvider.load(
        write_jwks(tmp_path / "jwks.json", [public_jwk]),
        max_bytes=65_536,
        max_keys=8,
        allow_standalone=True,
    )
    verifier = LocalJwtIdentityVerifier(
        provider=provider,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        algorithm="RS256",
        token_type="at+jwt",
        clock_skew_seconds=30,
        max_lifetime_seconds=900,
        max_token_bytes=8_192,
    )

    principal = verifier.verify_bearer(f"Bearer {issue_token(private_key)}")

    assert principal.model_dump(mode="json", exclude={"issued_at", "expires_at"}) == {
        "audience": "enterprise-rag-api",
        "groups": ["all_employees"],
        "issuer": "https://identity.localhost/",
        "key_id": "test-key-1",
        "region": "cn",
        "roles": [],
        "subject": "user_employee",
        "tenant_id": "starbridge-cn",
    }
    assert principal.to_user_context().model_dump(mode="json") == {
        "user_id": "user_employee",
        "tenant_id": "starbridge-cn",
        "region": "cn",
        "groups": ["all_employees"],
        "roles": [],
    }


@pytest.mark.parametrize(
    ("authorization", "code"),
    [
        (None, "authentication_required"),
        ("", "invalid_token"),
        ("Basic abc", "invalid_token"),
        ("Bearer", "invalid_token"),
        ("Bearer one two", "invalid_token"),
        ("Bearer token\nforged", "invalid_token"),
        ("Bearer é", "invalid_token"),
        (f"Bearer {'a' * 8_193}", "invalid_token"),
    ],
)
def test_missing_malformed_and_oversized_bearer_values_fail_closed(
    tmp_path: Path,
    authorization: str | None,
    code: str,
) -> None:
    verifier, _ = _verifier_and_key(tmp_path)

    with pytest.raises(AuthenticationFailure) as captured:
        verifier.verify_bearer(authorization)

    assert captured.value.code == code
    assert str(captured.value) == "token authentication failed"


def test_untrusted_header_signature_and_key_selection_fail_closed(
    tmp_path: Path,
) -> None:
    verifier, trusted_private_key = _verifier_and_key(tmp_path)
    attacker_private_key, _ = generate_rsa_jwk(kid="test-key-1")
    candidates = [
        issue_token(attacker_private_key),
        issue_token(trusted_private_key, kid="unknown-key"),
        issue_token(trusted_private_key, headers={"typ": "JWT"}),
        issue_token(
            trusted_private_key,
            headers={"jku": "https://attacker.invalid/jwks.json"},
        ),
        issue_token(trusted_private_key, headers={"jwk": {"kty": "RSA"}}),
        issue_token(
            trusted_private_key,
            headers={"x5u": "https://attacker.invalid/certificate"},
        ),
        issue_token(trusted_private_key, headers={"x5c": ["attacker"]}),
        issue_token(trusted_private_key, headers={"crit": ["exp"]}),
        issue_token(trusted_private_key, headers={"zip": "DEF"}),
    ]

    for candidate in candidates:
        with pytest.raises(AuthenticationFailure) as captured:
            verifier.verify_bearer(f"Bearer {candidate}")
        assert captured.value.code == "invalid_token"


def test_invalid_registered_and_identity_claims_fail_closed(
    tmp_path: Path,
) -> None:
    verifier, private_key = _verifier_and_key(tmp_path)
    now = int(time.time())
    candidates = [
        issue_token(private_key, issuer="https://attacker.invalid/"),
        issue_token(private_key, audience="other-api"),
        issue_token(private_key, issued_at=now - 400, expires_at=now - 100),
        issue_token(private_key, claims={"nbf": now + 300}),
        issue_token(private_key, issued_at=now + 300, expires_at=now + 600),
        issue_token(private_key, issued_at=now, expires_at=now + 901),
        issue_token(private_key, drop_claims={"sub"}),
        issue_token(private_key, drop_claims={"tenant_id"}),
        issue_token(private_key, claims={"groups": []}),
        issue_token(private_key, claims={"groups": ["all_employees"] * 2}),
        issue_token(private_key, claims={"roles": "rag.operator"}),
        issue_token(private_key, claims={"iat": True}),
        issue_token(private_key, claims={"nbf": True}),
        issue_token(private_key, claims={"aud": ["enterprise-rag-api"]}),
        issue_token(private_key, claims={"exp": float(now + 300)}),
        issue_token(private_key, claims={"sub": ""}),
        issue_token(private_key, claims={"tenant_id": 123}),
        issue_token(private_key, claims={"region": "cn\nadmin"}),
        issue_token(private_key, claims={"groups": [f"group-{i}" for i in range(51)]}),
        issue_token(private_key, claims={"roles": [f"role-{i}" for i in range(51)]}),
        issue_token(private_key, claims={"roles": ["rag.operator", "rag.operator"]}),
    ]

    for candidate in candidates:
        with pytest.raises(AuthenticationFailure) as captured:
            verifier.verify_bearer(f"Bearer {candidate}")
        assert captured.value.code == "invalid_token"


def test_service_roles_authorize_routes_but_do_not_enter_agent_user_context(
    tmp_path: Path,
) -> None:
    verifier, private_key = _verifier_and_key(tmp_path)

    principal = verifier.verify_bearer(
        f"Bearer {issue_token(private_key, roles=['rag.operator'])}"
    )

    assert principal.roles == ["rag.operator"]
    assert principal.to_user_context().roles == []


def test_duplicate_jwt_header_and_payload_keys_fail_closed(
    tmp_path: Path,
) -> None:
    verifier, private_key = _verifier_and_key(tmp_path)
    valid = issue_token(private_key)
    _, payload_segment, _ = valid.split(".")
    payload_json = base64.urlsafe_b64decode(
        payload_segment + "=" * (-len(payload_segment) % 4)
    ).decode("utf-8")
    duplicate_header = sign_raw_jws(
        private_key,
        header_json=(
            '{"alg":"RS256","kid":"test-key-1",'
            '"kid":"test-key-1","typ":"at+jwt"}'
        ),
        payload_json=payload_json,
    )
    duplicate_payload = sign_raw_jws(
        private_key,
        header_json='{"alg":"RS256","kid":"test-key-1","typ":"at+jwt"}',
        payload_json=payload_json.replace(
            '"tenant_id":"starbridge-cn"',
            '"tenant_id":"starbridge-cn","tenant_id":"starbridge-cn"',
        ),
    )

    for candidate in (duplicate_header, duplicate_payload):
        with pytest.raises(AuthenticationFailure) as captured:
            verifier.verify_bearer(f"Bearer {candidate}")
        assert captured.value.code == "invalid_token"


def _verifier_and_key(
    tmp_path: Path,
) -> tuple[LocalJwtIdentityVerifier, object]:
    private_key, public_jwk = generate_rsa_jwk()
    provider = LocalJwksKeyProvider.load(
        write_jwks(tmp_path / "jwks.json", [public_jwk]),
        max_bytes=65_536,
        max_keys=8,
        allow_standalone=True,
    )
    return (
        LocalJwtIdentityVerifier(
            provider=provider,
            issuer="https://identity.localhost/",
            audience="enterprise-rag-api",
            algorithm="RS256",
            token_type="at+jwt",
            clock_skew_seconds=30,
            max_lifetime_seconds=900,
            max_token_bytes=8_192,
        ),
        private_key,
    )
