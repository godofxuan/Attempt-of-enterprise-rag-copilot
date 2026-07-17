from __future__ import annotations

from inspect import signature

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import app.main as main_module
from tests.api_v2.helpers import make_container


LEGACY_POST_ROUTES = {
    ("POST", "/ingest"),
    ("POST", "/chat"),
    ("POST", "/agent/chat"),
}
SECURE_REQUIRED_ROUTES = {
    ("GET", "/health/live"),
    ("GET", "/health/ready"),
    ("POST", "/agent/v2/chat"),
    ("POST", "/feedback"),
    ("GET", "/observability/metrics"),
    ("GET", "/observability/traces/{request_id}"),
}


def route_contract(application) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for route in application.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            result.add((method, route.path))
    return result


def test_default_factory_has_a_fixed_secure_route_profile() -> None:
    application = main_module.create_app(make_container())
    routes = route_contract(application)

    assert LEGACY_POST_ROUTES.isdisjoint(routes)
    assert SECURE_REQUIRED_ROUTES.issubset(routes)
    assert set(signature(main_module.create_app).parameters) == {"container"}
    client = TestClient(application)
    assert client.post("/ingest").status_code == 404
    assert client.post("/chat", json={"question": "test"}).status_code == 404
    assert (
        client.post("/agent/chat", json={"question": "test"}).status_code
        == 404
    )


def test_explicit_compatibility_factory_is_the_only_legacy_route_profile() -> None:
    assert hasattr(main_module, "create_compatibility_app")

    application = main_module.create_compatibility_app(make_container())
    routes = route_contract(application)

    assert LEGACY_POST_ROUTES.issubset(routes)
    assert SECURE_REQUIRED_ROUTES.issubset(routes)
    assert set(signature(main_module.create_compatibility_app).parameters) == {
        "container"
    }
