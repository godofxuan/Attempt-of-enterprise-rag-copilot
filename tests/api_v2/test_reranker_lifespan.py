import pytest
from fastapi.testclient import TestClient

from tests.api_v2.helpers import make_container


def test_reranker_is_warmed_before_first_request(monkeypatch):
    from app.serving import create_app

    calls = []

    class Scorer:
        def warmup(self):
            calls.append("warm")

    monkeypatch.setenv("V2_RETRIEVAL_PROFILE", "safe_dense_raw20_bge")
    monkeypatch.setattr("app.serving.get_local_cross_encoder", lambda *a: Scorer())
    with TestClient(create_app(make_container())) as client:
        assert calls == ["warm"]
        assert client.get("/health/live").status_code == 200


def test_failed_warmup_prevents_startup(monkeypatch):
    from app.serving import create_app

    class Scorer:
        def warmup(self):
            raise RuntimeError("model unavailable")

    monkeypatch.setenv("V2_RETRIEVAL_PROFILE", "safe_dense_raw20_bge")
    monkeypatch.setattr("app.serving.get_local_cross_encoder", lambda *a: Scorer())
    with pytest.raises(RuntimeError, match="model unavailable"):
        with TestClient(create_app(make_container())):
            pytest.fail("failed scorer must not accept requests")
