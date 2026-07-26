from __future__ import annotations

import asyncio
from dataclasses import dataclass
from collections import deque
from typing import Annotated, Awaitable, Callable, Literal

from fastapi import Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette._utils import get_route_path
from starlette.responses import JSONResponse

from app.api.errors import ApiError, error_payload
from app.runtime.request_context import current_request_id
from app.runtime.resources import ServiceContainer
from app.security.identity import AuthenticationFailure, Principal


AccessLevel = Literal["public", "user", "operator"]
MAX_AUTHENTICATED_BODY_BYTES = 128 * 1024
MAX_AUTHENTICATED_BODY_MESSAGES = 256
AUTHENTICATED_BODY_RECEIVE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class ProtectedRoute:
    method: str
    template: str
    access: AccessLevel


@dataclass(frozen=True)
class _BodyReceiveRejected(RuntimeError):
    status_code: int
    code: str
    safe_message: str


_EXACT_ROUTES = {
    ("GET", "/health"): ProtectedRoute(
        method="GET", template="/health", access="public"
    ),
    ("GET", "/health/live"): ProtectedRoute(
        method="GET", template="/health/live", access="public"
    ),
    ("GET", "/health/ready"): ProtectedRoute(
        method="GET", template="/health/ready", access="public"
    ),
    ("GET", "/docs"): ProtectedRoute(
        method="GET", template="/docs", access="public"
    ),
    ("GET", "/docs/oauth2-redirect"): ProtectedRoute(
        method="GET", template="/docs/oauth2-redirect", access="public"
    ),
    ("GET", "/redoc"): ProtectedRoute(
        method="GET", template="/redoc", access="public"
    ),
    ("GET", "/openapi.json"): ProtectedRoute(
        method="GET", template="/openapi.json", access="public"
    ),
    ("POST", "/agent/v2/chat"): ProtectedRoute(
        method="POST", template="/agent/v2/chat", access="user"
    ),
    ("POST", "/feedback"): ProtectedRoute(
        method="POST", template="/feedback", access="user"
    ),
    ("GET", "/identity/me"): ProtectedRoute(
        method="GET", template="/identity/me", access="user"
    ),
    ("GET", "/observability/metrics"): ProtectedRoute(
        method="GET", template="/observability/metrics", access="operator"
    ),
    ("POST", "/operator/lifecycle/preview"): ProtectedRoute(
        method="POST",
        template="/operator/lifecycle/preview",
        access="operator",
    ),
    ("POST", "/operator/lifecycle/build"): ProtectedRoute(
        method="POST",
        template="/operator/lifecycle/build",
        access="operator",
    ),
    ("POST", "/operator/lifecycle/activate"): ProtectedRoute(
        method="POST",
        template="/operator/lifecycle/activate",
        access="operator",
    ),
    ("POST", "/operator/lifecycle/rollback"): ProtectedRoute(
        method="POST",
        template="/operator/lifecycle/rollback",
        access="operator",
    ),
    ("GET", "/operator/lifecycle/status"): ProtectedRoute(
        method="GET",
        template="/operator/lifecycle/status",
        access="operator",
    ),
}
_BEARER_DOCUMENTATION = HTTPBearer(auto_error=False, scheme_name="BearerAuth")


def document_bearer_authentication(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(_BEARER_DOCUMENTATION),
    ],
) -> None:
    # Enforcement happens in middleware before body parsing; this dependency
    # only publishes the authentication contract in OpenAPI.
    return None


class TrustedIdentityMiddleware:
    def __init__(self, app, *, container: ServiceContainer) -> None:
        self.app = app
        self.container = container

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Match the same application-relative path Starlette uses for mounted
        # apps and root_path deployments; the raw scope path includes prefixes.
        route = route_access_policy(
            scope.get("method", ""),
            get_route_path(scope),
        )
        state = scope.setdefault("state", {})
        state["route_template"] = route.template
        if route.access == "public":
            await self.app(scope, receive, send)
            return

        authorization_values = [
            value.decode("latin-1")
            for name, value in scope.get("headers", [])
            if name.lower() == b"authorization"
        ]
        if len(authorization_values) > 1:
            await _send_auth_error(
                scope,
                receive,
                send,
                status_code=401,
                code="invalid_token",
                message="Bearer token authentication failed.",
                retryable=False,
                authenticate=True,
            )
            return

        authorization_header = (
            authorization_values[0] if authorization_values else None
        )
        try:
            principal = self.container.identity_verifier.verify_bearer(
                authorization_header
            )
        except AuthenticationFailure as exc:
            if exc.code == "identity_unavailable":
                await _send_auth_error(
                    scope,
                    receive,
                    send,
                    status_code=503,
                    code="identity_unavailable",
                    message="The identity service is unavailable.",
                    retryable=True,
                    authenticate=False,
                )
            else:
                await _send_auth_error(
                    scope,
                    receive,
                    send,
                    status_code=401,
                    code=exc.code,
                    message="Bearer token authentication failed.",
                    retryable=False,
                    authenticate=True,
                )
            return
        except Exception:
            await _send_auth_error(
                scope,
                receive,
                send,
                status_code=503,
                code="identity_unavailable",
                message="The identity service is unavailable.",
                retryable=True,
                authenticate=False,
            )
            return

        if (
            route.access == "operator"
            and self.container.settings.identity_operator_role not in principal.roles
        ):
            await _send_auth_error(
                scope,
                receive,
                send,
                status_code=403,
                code="insufficient_role",
                message="The authenticated principal lacks the required role.",
                retryable=False,
                authenticate=False,
            )
            return

        state["principal"] = principal
        content_length_error = _content_length_error(scope.get("headers", []))
        if content_length_error is not None:
            status_code, code, message = content_length_error
            await _send_auth_error(
                scope,
                receive,
                send,
                status_code=status_code,
                code=code,
                message=message,
                retryable=False,
                authenticate=False,
            )
            return

        try:
            bounded_receive = await _bounded_request_receive(receive)
        except _BodyReceiveRejected as exc:
            await _send_auth_error(
                scope,
                receive,
                send,
                status_code=exc.status_code,
                code=exc.code,
                message=exc.safe_message,
                retryable=False,
                authenticate=False,
            )
            return
        await self.app(scope, bounded_receive, send)


def authenticated_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        raise ApiError(
            status_code=503,
            code="identity_unavailable",
            message="The identity service is unavailable.",
            retryable=True,
        )
    return principal


def route_access_policy(method: str, path: str) -> ProtectedRoute:
    exact = _EXACT_ROUTES.get((method.upper(), path))
    if exact is not None:
        return exact
    prefix = "/observability/traces/"
    if method.upper() == "GET" and path.startswith(prefix) and len(path) > len(prefix):
        return ProtectedRoute(
            method="GET",
            template="/observability/traces/{request_id}",
            access="operator",
        )
    return ProtectedRoute(
        method=method.upper(),
        template="/{unmatched}",
        access="user",
    )


def _content_length_error(
    headers: list[tuple[bytes, bytes]],
) -> tuple[int, str, str] | None:
    values = [
        value
        for name, value in headers
        if name.lower() == b"content-length"
    ]
    transfer_encoding = any(
        name.lower() == b"transfer-encoding" for name, _ in headers
    )
    if len(values) > 1 or (values and transfer_encoding):
        return (
            400,
            "invalid_content_length",
            "The request body framing is invalid.",
        )
    if not values:
        return None
    try:
        rendered = values[0].decode("ascii")
    except UnicodeDecodeError:
        rendered = ""
    if not rendered.isdigit():
        return (
            400,
            "invalid_content_length",
            "The request body framing is invalid.",
        )
    normalized = rendered.lstrip("0") or "0"
    maximum = str(MAX_AUTHENTICATED_BODY_BYTES)
    if len(normalized) > len(maximum) or (
        len(normalized) == len(maximum) and normalized > maximum
    ):
        return (
            413,
            "request_body_too_large",
            "The authenticated request body is too large.",
        )
    return None


async def _bounded_request_receive(
    receive: Callable[[], Awaitable[dict]],
) -> Callable[[], Awaitable[dict]]:
    messages: deque[dict] = deque()
    total = 0
    message_count = 0
    loop = asyncio.get_running_loop()
    deadline = loop.time() + AUTHENTICATED_BODY_RECEIVE_TIMEOUT_SECONDS
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise _BodyReceiveRejected(
                status_code=408,
                code="request_body_timeout",
                safe_message=(
                    "The authenticated request body was not received in time."
                ),
            )
        try:
            message = await asyncio.wait_for(receive(), timeout=remaining)
        except TimeoutError:
            raise _BodyReceiveRejected(
                status_code=408,
                code="request_body_timeout",
                safe_message=(
                    "The authenticated request body was not received in time."
                ),
            ) from None
        if not isinstance(message, dict):
            raise _BodyReceiveRejected(
                status_code=400,
                code="invalid_request_body",
                safe_message="The authenticated request body framing is invalid.",
            )
        message_count += 1
        if message_count > MAX_AUTHENTICATED_BODY_MESSAGES:
            raise _BodyReceiveRejected(
                status_code=413,
                code="request_body_too_large",
                safe_message="The authenticated request body is too large.",
            )
        messages.append(message)
        if message.get("type") == "http.disconnect":
            break
        if message.get("type") != "http.request":
            raise _BodyReceiveRejected(
                status_code=400,
                code="invalid_request_body",
                safe_message="The authenticated request body framing is invalid.",
            )
        body = message.get("body", b"")
        if not isinstance(body, bytes):
            raise _BodyReceiveRejected(
                status_code=400,
                code="invalid_request_body",
                safe_message="The authenticated request body framing is invalid.",
            )
        total += len(body)
        if total > MAX_AUTHENTICATED_BODY_BYTES:
            raise _BodyReceiveRejected(
                status_code=413,
                code="request_body_too_large",
                safe_message="The authenticated request body is too large.",
            )
        more_body = message.get("more_body", False)
        if not isinstance(more_body, bool):
            raise _BodyReceiveRejected(
                status_code=400,
                code="invalid_request_body",
                safe_message="The authenticated request body framing is invalid.",
            )
        if not more_body:
            break
        if message_count >= MAX_AUTHENTICATED_BODY_MESSAGES:
            raise _BodyReceiveRejected(
                status_code=413,
                code="request_body_too_large",
                safe_message="The authenticated request body is too large.",
            )

    async def replay() -> dict:
        if messages:
            return messages.popleft()
        return {"type": "http.request", "body": b"", "more_body": False}

    return replay


async def _send_auth_error(
    scope,
    receive,
    send,
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool,
    authenticate: bool,
) -> None:
    state = scope.setdefault("state", {})
    state["error_code"] = code
    state["outcome"] = code
    request_id = state.get("request_id") or current_request_id() or "untracked"
    headers = {"WWW-Authenticate": "Bearer"} if authenticate else None
    response = JSONResponse(
        status_code=status_code,
        content=error_payload(
            code=code,
            message=message,
            request_id=request_id,
            retryable=retryable,
        ),
        headers=headers,
    )
    await response(scope, receive, send)


__all__ = [
    "AUTHENTICATED_BODY_RECEIVE_TIMEOUT_SECONDS",
    "MAX_AUTHENTICATED_BODY_BYTES",
    "MAX_AUTHENTICATED_BODY_MESSAGES",
    "TrustedIdentityMiddleware",
    "authenticated_principal",
    "document_bearer_authentication",
    "route_access_policy",
]
