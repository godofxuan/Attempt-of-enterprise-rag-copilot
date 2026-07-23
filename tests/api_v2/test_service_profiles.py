from __future__ import annotations

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import app.main as main_module
from app.api.identity import route_access_policy
from tests.api_v2.helpers import USER_HEADERS
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
    ("GET", "/identity/me"),
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
    client = TestClient(application)
    assert client.post("/ingest").status_code == 401
    assert client.post("/chat", json={"question": "test"}).status_code == 401
    assert (
        client.post("/agent/chat", json={"question": "test"}).status_code
        == 401
    )
    assert (
        client.post(
            "/agent/chat",
            headers=USER_HEADERS,
            json={"question": "test"},
        ).status_code
        == 404
    )


def test_production_module_has_no_deployable_legacy_factory() -> None:
    assert not hasattr(main_module, "create_compatibility_app")


def test_route_policy_is_public_by_exception_and_user_by_default() -> None:
    assert route_access_policy("GET", "/health/live").access == "public"
    assert route_access_policy("GET", "/openapi.json").access == "public"
    assert route_access_policy("POST", "/agent/v2/chat").access == "user"
    assert route_access_policy("GET", "/observability/metrics").access == "operator"
    assert route_access_policy("POST", "/future-business-route").access == "user"
