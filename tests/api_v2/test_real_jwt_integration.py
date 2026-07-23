from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.evidence import AnswerResponse
from app.main import create_app
from app.security.demo_identity import initialize_demo_identity
from app.security.identity import build_identity_verifier
from app.security.token_source import BearerTokenFileSource, PersonaTokenBundleSource
from tests.api_v2.helpers import make_container


def test_real_rs256_persona_and_operator_tokens_cross_the_http_boundary(
    monkeypatch,
    tmp_path: Path,
) -> None:
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
    observed = {}

    def fake_run(question, user, top_k=None):
        observed["user"] = user
        return AnswerResponse(
            mode="not_found",
            answer="No visible evidence.",
            stop_reason="not_found",
            trace={"intent": "fact", "steps": [], "budget": {}},
        )

    monkeypatch.setattr("app.main.run_agent_v2_chat", fake_run)
    container = make_container(identity_verifier=build_identity_verifier(settings))
    client = TestClient(create_app(container))
    persona_token = PersonaTokenBundleSource(tmp_path / "persona_tokens.json").get_token(
        "user_security"
    )
    operator_token = BearerTokenFileSource(tmp_path / "operator_token.txt").get_token()
    tampered_token = _noncanonical_signature_encoding(persona_token)

    chat = client.post(
        "/agent/v2/chat",
        headers={"Authorization": f"Bearer {persona_token}"},
        json={"question": "Policy?"},
    )
    metrics = client.get(
        "/observability/metrics",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    tampered = client.post(
        "/agent/v2/chat",
        headers={"Authorization": f"Bearer {tampered_token}"},
        json={"question": "Policy?"},
    )

    assert chat.status_code == 200
    assert observed["user"].user_id == "user_security"
    assert observed["user"].groups == ["all_employees", "security_ops"]
    assert observed["user"].roles == []
    assert metrics.status_code == 200
    assert tampered.status_code == 401
    assert tampered.json()["error"]["code"] == "invalid_token"


def _noncanonical_signature_encoding(token: str) -> str:
    header, payload, signature = token.split(".")
    padding = "=" * (-len(signature) % 4)
    decoded = base64.urlsafe_b64decode(signature + padding)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    for character in alphabet:
        candidate = signature[:-1] + character
        if candidate == signature:
            continue
        candidate_padding = "=" * (-len(candidate) % 4)
        if base64.urlsafe_b64decode(candidate + candidate_padding) == decoded:
            return f"{header}.{payload}.{candidate}"
    raise AssertionError("signature encoding has no noncanonical alternative")
