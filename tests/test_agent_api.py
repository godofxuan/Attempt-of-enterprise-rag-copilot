from fastapi.testclient import TestClient

import app.main as main_module
from tests.api_v2.helpers import USER_HEADERS, make_container


def test_legacy_agent_endpoint_is_retired_from_the_deployable_app() -> None:
    assert not hasattr(main_module, "create_compatibility_app")
    response = TestClient(main_module.create_app(make_container())).post(
        "/agent/chat",
        headers=USER_HEADERS,
        json={"question": "test question", "top_k": 3},
    )

    assert response.status_code == 404
