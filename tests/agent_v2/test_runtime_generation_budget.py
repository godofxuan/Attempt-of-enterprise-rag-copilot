from app.agent.generation_v2 import _bounded_default_chat


def test_real_generation_sets_output_limit(monkeypatch):
    seen = {}

    def chat(model, messages, **kwargs):
        seen.update(kwargs)
        return "{}"

    monkeypatch.setattr("app.agent.generation_v2.chat_with_ollama", chat)
    _bounded_default_chat("model", [], think=False)
    assert seen["max_output_tokens"] == 1024
