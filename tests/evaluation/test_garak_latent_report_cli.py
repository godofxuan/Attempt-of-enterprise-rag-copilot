from __future__ import annotations

from types import SimpleNamespace

from scripts import eval_garak_latent_report


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
