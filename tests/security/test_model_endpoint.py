from __future__ import annotations

import pytest

from app.config import Settings
from app.security.model_endpoint import parse_pinned_model_endpoint


@pytest.mark.parametrize(
    ("value", "origin", "openai_base_url"),
    [
        (
            "http://localhost:11434/v1",
            "http://127.0.0.1:11434",
            "http://127.0.0.1:11434/v1",
        ),
        (
            "http://127.0.0.1:11434",
            "http://127.0.0.1:11434",
            "http://127.0.0.1:11434/v1",
        ),
        (
            "http://[::1]:11434/v1/",
            "http://[::1]:11434",
            "http://[::1]:11434/v1",
        ),
    ],
)
def test_model_endpoint_canonicalizes_only_explicit_loopback_origins(
    value: str,
    origin: str,
    openai_base_url: str,
) -> None:
    endpoint = parse_pinned_model_endpoint(value)

    assert endpoint.origin == origin
    assert endpoint.openai_base_url == openai_base_url


@pytest.mark.parametrize(
    "value",
    [
        "https://127.0.0.1:11434/v1",
        "http://ollama:11434/v1",
        "http://192.168.1.10:11434/v1",
        "http://127.0.0.1/v1",
        "http://127.0.0.1:0/v1",
        "http://127.0.0.1:65536/v1",
        "http://user@127.0.0.1:11434/v1",
        "http://127.0.0.1:11434/admin",
        "http://127.0.0.1:11434/v1?target=remote",
        " http://127.0.0.1:11434/v1",
    ],
)
def test_model_endpoint_rejects_remote_ambiguous_or_unpinned_values(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="pinned local Ollama origin"):
        parse_pinned_model_endpoint(value)


def test_deployment_binding_is_all_or_nothing() -> None:
    with pytest.raises(
        ValueError,
        match="release and expected index binding must be set together",
    ):
        Settings(deployment_release_id="release-one")


def test_deployment_binding_accepts_exact_release_and_index_identity() -> None:
    settings = Settings(
        deployment_release_id="release-one",
        deployment_expected_index_run_id="index-one",
        deployment_expected_index_manifest_sha256="a" * 64,
    )

    assert settings.deployment_release_id == "release-one"
    assert settings.deployment_expected_index_run_id == "index-one"
    assert settings.deployment_expected_index_manifest_sha256 == "a" * 64
