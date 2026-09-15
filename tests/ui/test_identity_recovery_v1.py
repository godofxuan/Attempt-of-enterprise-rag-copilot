import pytest

from streamlit_app.api_client import EnterpriseRagClient, UiApiError
from tests.ui.test_api_client import FakeResponse, FakeSession, OperatorToken, PersonaTokens


def test_invalid_token_has_actionable_nonsecret_recovery_without_post_retry():
    session = FakeSession(
        [
            FakeResponse(
                401,
                {
                    "error": {
                        "code": "invalid_token",
                        "message": "Bearer token authentication failed.",
                        "request_id": "req-ui",
                        "retryable": False,
                    }
                },
            )
        ]
    )
    client = EnterpriseRagClient(
        "http://127.0.0.1:8000",
        session=session,
        persona_tokens=PersonaTokens(),
        operator_token=OperatorToken(),
        request_id_factory=lambda: "req-ui",
    )
    with pytest.raises(UiApiError) as caught:
        client.ask("Question", persona_id="demo-employee", top_k=5)
    assert "renew" in caught.value.safe_message
    assert "expired" in caught.value.safe_message
    assert len(session.calls) == 1 and not caught.value.retryable
