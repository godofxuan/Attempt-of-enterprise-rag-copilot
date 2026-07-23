from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse

from app.api.errors import error_payload
from app.observability.tracing import RequestTrace, SpanRecord
from app.runtime.request_context import (
    bind_request_context,
    current_request_context,
    reset_request_context,
)
from app.runtime.resources import ServiceContainer


LOGGER = logging.getLogger("enterprise_rag.request")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestContextMiddleware:
    def __init__(self, app, *, container: ServiceContainer) -> None:
        self.app = app
        self.container = container

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id(scope)
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        token = bind_request_context(
            request_id,
            deadline_ms=self.container.settings.api_request_deadline_ms,
        )
        self.container.metrics.request_started()
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_request_id(message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_started = True
                headers = MutableHeaders(scope=message)
                headers.append("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            if response_started:
                raise
            state["error_code"] = "internal_error"
            state["outcome"] = "internal_error"
            response = JSONResponse(
                status_code=500,
                content=error_payload(
                    code="internal_error",
                    message="The service could not complete the request.",
                    request_id=request_id,
                    retryable=False,
                ),
            )
            await response(scope, receive, send_with_request_id)
        finally:
            duration_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
            context = current_request_context()
            route = _route_template(scope)
            outcome = str(state.get("outcome") or state.get("error_code") or f"http_{status_code}")
            model_calls = context.model_calls if context is not None else 0
            model_retries = context.model_retries if context is not None else 0
            model_errors = context.model_errors if context is not None else 0
            spans = [
                SpanRecord.model_validate(item)
                for item in (context.spans if context is not None else [])
            ]
            self.container.metrics.request_finished(
                method=scope["method"],
                route=route,
                status_code=status_code,
                duration_ms=duration_ms,
                model_calls=model_calls,
                model_retries=model_retries,
                model_errors=model_errors,
            )
            if route != "/observability/traces/{request_id}":
                self.container.traces.append(
                    RequestTrace(
                        request_id=request_id,
                        method=scope["method"],
                        route=self.container.metrics.normalize_route(route),
                        status_code=status_code,
                        duration_ms=duration_ms,
                        outcome=outcome,
                        model_calls=model_calls,
                        model_retries=model_retries,
                        model_errors=model_errors,
                        spans=spans,
                    )
                )
            LOGGER.info(
                "request_complete request_id=%s method=%s route=%s status=%s duration_ms=%.3f",
                request_id,
                scope["method"],
                route,
                status_code,
                duration_ms,
            )
            reset_request_context(token)


def _request_id(scope) -> str:
    candidate = Headers(scope=scope).get("x-request-id", "")
    return candidate if REQUEST_ID_PATTERN.fullmatch(candidate) else uuid.uuid4().hex


def _route_template(scope) -> str:
    state_template = scope.get("state", {}).get("route_template")
    if isinstance(state_template, str) and state_template:
        return state_template
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path else "__unmatched__"


__all__ = ["REQUEST_ID_PATTERN", "RequestContextMiddleware"]
