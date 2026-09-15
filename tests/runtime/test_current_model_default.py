from pathlib import Path

import pytest

from app.config import Settings


@pytest.mark.parametrize("field", ["chat_model", "evidence_model"])
def test_current_generation_model_default(field, monkeypatch):
    monkeypatch.delenv(field.upper(), raising=False)
    assert getattr(Settings(_env_file=None), field) == "qwen3.5:4b"


def test_model_switch_does_not_change_embedding_default(monkeypatch):
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    assert Settings(_env_file=None).embedding_model == "bge-m3"


def test_env_example_matches_current_generation_defaults():
    root = Path(__file__).resolve().parents[2]
    lines = (root / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "CHAT_MODEL=qwen3.5:4b" in lines
    assert "EVIDENCE_MODEL=qwen3.5:4b" in lines


def test_explicit_historical_model_override_remains_supported():
    settings = Settings(_env_file=None, chat_model="qwen2.5:3b")
    assert settings.chat_model == "qwen2.5:3b"


def test_candidate_launcher_uses_current_model():
    root = Path(__file__).resolve().parents[2]
    launcher = (root / "scripts/local_candidate.ps1").read_text(encoding="utf-8")
    assert "$env:CHAT_MODEL = 'qwen3.5:4b'" in launcher
    assert "$env:EVIDENCE_MODEL = 'qwen3.5:4b'" in launcher


def test_deployment_defaults_match_local_model():
    root = Path(__file__).resolve().parents[2]
    compose = (root / "deploy/compose.yaml").read_text(encoding="utf-8")
    example = (root / "deploy/runtime.env.example").read_text(encoding="utf-8")
    for key in ("CHAT_MODEL", "EVIDENCE_MODEL"):
        assert f"${{{key}:-qwen3.5:4b}}" in compose
        assert f"{key}=qwen3.5:4b" in example.splitlines()
