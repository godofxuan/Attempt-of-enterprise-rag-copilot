import pytest

from app.config import Settings
from app.runtime.resources import RuntimeResources
from app.runtime.serving_resources import ServingRuntimeResources


def test_periodic_probe_does_not_regenerate(monkeypatch):
    calls = []
    monkeypatch.setattr(RuntimeResources, "_probe_models", lambda *a: calls.append("inference"))
    monkeypatch.setattr(ServingRuntimeResources, "_model_digests", lambda self: {"model": "digest"})
    resources = ServingRuntimeResources(Settings())
    resources._probe_models(None)
    resources._probe_models(None)
    assert calls == ["inference"]


def test_changed_model_does_not_silently_revalidate(monkeypatch):
    monkeypatch.setattr(RuntimeResources, "_probe_models", lambda *a: None)
    values = iter(({"model": "old"}, {"model": "new"}))
    monkeypatch.setattr(ServingRuntimeResources, "_model_digests", lambda self: next(values))
    resources = ServingRuntimeResources(Settings())
    resources._probe_models(None)
    with pytest.raises(RuntimeError, match="changed"):
        resources._probe_models(None)


@pytest.mark.parametrize("defect", ["short_digest", "duplicate_alias"])
def test_model_identity_probe_rejects_ambiguous_or_invalid_identity(monkeypatch, defect):
    settings = Settings(_env_file=None)
    tags = [
        {"name": name, "digest": "a" * 64}
        for name in dict.fromkeys(
            (settings.chat_model, settings.evidence_model, settings.embedding_model)
        )
    ]
    if defect == "short_digest":
        tags[0]["digest"] = "not-a-model-digest"
    else:
        tags.append(dict(tags[0]))

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def get(self, *_, **kwargs):
            from types import SimpleNamespace

            return SimpleNamespace(status_code=200, json=lambda: {"models": tags})

    monkeypatch.setattr("app.runtime.serving_resources.requests.Session", Session)
    with pytest.raises(RuntimeError):
        ServingRuntimeResources(settings)._model_digests()
