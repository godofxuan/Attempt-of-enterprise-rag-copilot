from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import eval_garak_latent_report


ROOT = Path(__file__).resolve().parents[2]


def test_garak_live_cli_has_bounded_runtime_contract() -> None:
    parser = eval_garak_latent_report.build_parser()
    options = {
        option for action in parser._actions for option in action.option_strings
    }

    assert eval_garak_latent_report.MAX_OUTPUT_TOKENS == 256
    assert eval_garak_latent_report.CACHE_RESET_EVERY_MODEL_CALLS == 12
    assert "--force" not in options
    assert "--execute-live" in options


def test_unload_ollama_model_uses_exact_local_endpoint(monkeypatch) -> None:
    captured = {}

    class FakeSession:
        trust_env = True

        def post(self, url, **kwargs):
            captured.update(url=url, trust_env=self.trust_env, **kwargs)
            return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(eval_garak_latent_report.requests, "Session", FakeSession)

    eval_garak_latent_report.unload_ollama_model(
        "http://127.0.0.1:11434", "qwen3:8b"
    )

    assert captured == {
        "url": "http://127.0.0.1:11434/api/generate",
        "trust_env": False,
        "json": {"model": "qwen3:8b", "keep_alive": 0},
        "timeout": 30,
        "allow_redirects": False,
    }


def test_public_expanded_evidence_recomputes_security_deltas() -> None:
    payload = json.loads(
        (
            ROOT
            / "docs/r3/evidence/garak_latent_report_expanded_v1.json"
        ).read_text(encoding="utf-8")
    )

    assert payload["fixture"] == {
        "attack_case_count": 48,
        "benign_case_count": 4,
        "sha256": "1d45e05e9b28686472afdbeb4a251d41176099013f86948eb96f5afab1b6f7a0",
    }
    assert payload["guard_off"]["attack_success_count"] == 12
    assert payload["guard_on"]["attack_success_count"] == 0
    assert payload["guard_off"]["context_exposure_count"] == 48
    assert payload["guard_on"]["context_exposure_count"] == 0
    assert payload["runtime"]["allowed_local_http_requests"] == (
        payload["runtime"]["observed_model_call_count"]
        + payload["runtime"]["cache_reset_count"]
        + 1
    )
