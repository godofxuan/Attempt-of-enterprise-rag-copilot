from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from http.cookiejar import Cookie, DefaultCookiePolicy
from typing import Any, Literal, Protocol
from urllib.parse import quote, urlsplit

import requests
from pydantic import BaseModel, ConfigDict, Field

from app.api.errors import ApiErrorResponse
from app.domain.evidence import AnswerResponse
from app.observability.tracing import RequestTrace
from app.runtime.resources import ReadinessSnapshot
from app.schemas import FeedbackResponse
from app.security.identity import IdentityConfigurationError
from app.security.token_source import BearerTokenSource


RequestIdFactory = Callable[[], str]
IdentityChannel = Literal["public", "persona", "operator"]


class PersonaTokenSource(Protocol):
    def get_token(self, persona_id: str) -> str: ...


class AskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=64)
    feedback_receipt: str = Field(pattern=r"^[0-9a-f]{64}$")
    response: AnswerResponse


class UiApiError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        safe_message: str,
        request_id: str,
        retryable: bool,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.request_id = request_id
        self.retryable = retryable

    def __str__(self) -> str:
        return self.safe_message


class EnterpriseRagClient:
    def __init__(
        self,
        base_url: str,
        *,
        session: requests.Session | Any | None = None,
        timeout_seconds: float = 30.0,
        request_id_factory: RequestIdFactory | None = None,
        persona_tokens: PersonaTokenSource,
        operator_token: BearerTokenSource,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.base_url = normalize_local_base_url(base_url)
        if session is None:
            self._sessions = {
                channel: _new_cookie_free_session()
                for channel in ("public", "persona", "operator")
            }
        else:
            injected = _configure_cookie_free_session(session)
            self._sessions = {
                channel: injected
                for channel in ("public", "persona", "operator")
            }
        # Kept for callers that inject a recording session in tests.
        self.session = self._sessions["persona"]
        self.timeout_seconds = float(timeout_seconds)
        self.request_id_factory = request_id_factory or (lambda: uuid.uuid4().hex)
        self._persona_tokens = persona_tokens
        self._operator_token = operator_token

    def ask(
        self,
        question: str,
        *,
        persona_id: str,
        top_k: int,
    ) -> AskResult:
        request_id = self._new_request_id()
        response = self._send(
            "POST",
            "/agent/v2/chat",
            identity_channel="persona",
            request_id=request_id,
            json={
                "question": question,
                "top_k": top_k,
            },
            token=self._persona_token(persona_id, request_id),
            accepted_statuses={200},
        )
        payload = self._validated_json(response, AnswerResponse, request_id)
        body_id = payload.trace.get("request_id")
        if body_id != request_id:
            raise _invalid_response(request_id)
        feedback_receipt = _response_header(response, "X-Feedback-Receipt")
        if (
            feedback_receipt is None
            or re.fullmatch(r"[0-9a-f]{64}", feedback_receipt) is None
        ):
            raise _invalid_response(request_id)
        return AskResult(
            request_id=request_id,
            feedback_receipt=feedback_receipt,
            response=payload,
        )

    def readiness(self) -> ReadinessSnapshot:
        request_id = self._new_request_id()
        response = self._send(
            "GET",
            "/health/ready",
            identity_channel="public",
            request_id=request_id,
            accepted_statuses={200, 503},
        )
        return self._validated_json(response, ReadinessSnapshot, request_id)

    def trace(self, request_id: str) -> RequestTrace:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", request_id):
            raise UiApiError(
                code="invalid_request_id",
                safe_message="The request ID is invalid.",
                request_id="untracked",
                retryable=False,
            )
        lookup_id = self._new_request_id()
        response = self._send(
            "GET",
            f"/observability/traces/{quote(request_id, safe='')}",
            identity_channel="operator",
            request_id=lookup_id,
            token=self._operator_bearer(lookup_id),
            accepted_statuses={200},
        )
        trace = self._validated_json(response, RequestTrace, lookup_id)
        if trace.request_id != request_id:
            raise _invalid_response(lookup_id)
        return trace

    def feedback(
        self,
        *,
        persona_id: str,
        target_request_id: str,
        question: str,
        answer: str,
        helpful: bool,
        receipt: str,
    ) -> FeedbackResponse:
        request_id = self._new_request_id()
        if re.fullmatch(r"[0-9a-f]{64}", receipt) is None:
            raise _invalid_response(request_id)
        response = self._send(
            "POST",
            "/feedback",
            identity_channel="persona",
            request_id=request_id,
            json={
                "target_request_id": target_request_id,
                "question": question,
                "answer": answer,
                "helpful": helpful,
                "receipt": receipt,
            },
            token=self._persona_token(persona_id, request_id),
            accepted_statuses={200},
        )
        return self._validated_json(response, FeedbackResponse, request_id)

    def _new_request_id(self) -> str:
        request_id = str(self.request_id_factory())
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", request_id):
            return uuid.uuid4().hex
        return request_id

    def _send(
        self,
        method: str,
        path: str,
        *,
        identity_channel: IdentityChannel,
        request_id: str,
        accepted_statuses: set[int],
        json: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "headers": {"X-Request-ID": request_id},
            "timeout": self.timeout_seconds,
        }
        if token is not None:
            kwargs["headers"]["Authorization"] = f"Bearer {token}"
        if json is not None:
            kwargs["json"] = json
        try:
            response = self._sessions[identity_channel].request(
                method,
                f"{self.base_url}{path}",
                allow_redirects=False,
                **kwargs,
            )
        except Exception:
            raise UiApiError(
                code="service_unavailable",
                safe_message="The service is unavailable.",
                request_id=request_id,
                retryable=True,
            ) from None
        if _response_request_id(response) != request_id:
            raise _invalid_response(request_id)
        if response.status_code not in accepted_statuses:
            self._raise_http_error(response, request_id)
        return response

    def _persona_token(self, persona_id: str, request_id: str) -> str:
        try:
            return self._persona_tokens.get_token(persona_id)
        except (IdentityConfigurationError, OSError, ValueError):
            raise _identity_unavailable(request_id) from None

    def _operator_bearer(self, request_id: str) -> str:
        try:
            return self._operator_token.get_token()
        except (IdentityConfigurationError, OSError, ValueError):
            raise _identity_unavailable(request_id) from None

    def _raise_http_error(self, response: Any, request_id: str) -> None:
        try:
            payload = ApiErrorResponse.model_validate(response.json())
            header_id = _response_request_id(response)
            if header_id is not None and payload.error.request_id != header_id:
                raise ValueError("request ID mismatch")
        except Exception:
            status_code = int(getattr(response, "status_code", 500))
            raise UiApiError(
                code="service_error",
                safe_message="The service could not complete the request.",
                request_id=request_id,
                retryable=status_code >= 500,
            ) from None
        raise UiApiError(
            code=payload.error.code,
            safe_message=payload.error.message,
            request_id=payload.error.request_id,
            retryable=payload.error.retryable,
        )

    @staticmethod
    def _validated_json(response: Any, model: type[BaseModel], request_id: str):
        try:
            return model.model_validate(response.json())
        except Exception:
            raise _invalid_response(request_id) from None


def _response_request_id(response: Any) -> str | None:
    return _response_header(response, "X-Request-ID")


def _response_header(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", {})
    value = headers.get(name)
    if value is None:
        expected = name.casefold()
        for key, candidate in headers.items():
            if str(key).casefold() == expected:
                value = candidate
                break
    return str(value) if value else None


class _RejectAllCookies(DefaultCookiePolicy):
    def set_ok(self, cookie: Cookie, request: Any) -> bool:
        return False

    def return_ok(self, cookie: Cookie, request: Any) -> bool:
        return False


def _new_cookie_free_session() -> requests.Session:
    return _configure_cookie_free_session(requests.Session())


def _configure_cookie_free_session(session: Any) -> Any:
    session.trust_env = False
    if hasattr(session, "cookies"):
        cookies = requests.cookies.RequestsCookieJar()
        cookies.set_policy(_RejectAllCookies())
        session.cookies = cookies
    return session


def _invalid_response(request_id: str) -> UiApiError:
    return UiApiError(
        code="invalid_service_response",
        safe_message="The service returned an invalid response.",
        request_id=request_id,
        retryable=False,
    )


def _identity_unavailable(request_id: str) -> UiApiError:
    return UiApiError(
        code="identity_unavailable",
        safe_message="The local demo identity is unavailable.",
        request_id=request_id,
        retryable=False,
    )


def normalize_local_base_url(value: str) -> str:
    candidate = value.strip()
    if candidate != value:
        raise ValueError("base URL must be canonical")
    parsed = urlsplit(candidate)
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("base URL is invalid") from None
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("base URL must be a numeric IPv4 loopback origin")
    expected_netloc = "127.0.0.1" if port is None else f"127.0.0.1:{port}"
    if parsed.netloc != expected_netloc:
        raise ValueError("base URL must be canonical")
    return f"http://{expected_netloc}"


__all__ = [
    "AskResult",
    "EnterpriseRagClient",
    "UiApiError",
    "normalize_local_base_url",
]
