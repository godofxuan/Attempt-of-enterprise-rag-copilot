import asyncio

from app.api.middleware import RequestContextMiddleware
from app.runtime.request_context import (
    bind_request_context,
    current_request_context,
    remaining_seconds,
    reset_request_context,
)
from tests.api_v2.helpers import make_container


def test_disconnect_is_observed_while_endpoint_is_not_reading_body():
    async def scenario():
        delivered = False
        observed = []

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"{}", "more_body": False}
            return {"type": "http.disconnect"}

        async def endpoint(scope, receive, send):
            await receive()
            for _ in range(20):
                await asyncio.sleep(0.001)
                if remaining_seconds() == 0:
                    break
            assert remaining_seconds() == 0
            assert current_request_context().cancelled.is_set()
            await send({"type": "http.response.start", "status": 499, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        async def send(message):
            observed.append(message)

        scope = {"type": "http", "method": "POST", "path": "/agent/v2/chat", "headers": []}
        await RequestContextMiddleware(endpoint, container=make_container())(scope, receive, send)
        assert observed[0]["status"] == 499
        assert current_request_context() is None

    asyncio.run(scenario())


def test_cancelled_context_does_not_leak_into_next_request():
    token = bind_request_context("cancelled", deadline_ms=1000)
    try:
        current_request_context().cancelled.set()
        assert remaining_seconds() == 0
    finally:
        reset_request_context(token)
    token = bind_request_context("next", deadline_ms=1000)
    try:
        assert remaining_seconds() > 0
    finally:
        reset_request_context(token)
