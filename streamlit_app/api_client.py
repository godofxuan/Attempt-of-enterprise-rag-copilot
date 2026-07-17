from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import requests
from pydantic import BaseModel, ConfigDict, Field

from app.api.errors import ApiErrorResponse
from app.domain.evidence import AnswerResponse
from app.domain.queries import UserContext
from app.observability.tracing import RequestTrace
from app.runtime.resources import ReadinessSnapshot
from app.schemas import FeedbackResponse


RequestIdFactory = Callable[[], str]


class AskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=64)
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
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.base_url = base_url.rstrip("/")
        if not self.base_url:
            raise ValueError("base_url must not be empty")
        self.session = session or requests.Session()
        self.session.trust_env = False
        self.timeout_seconds = float(timeout_seconds)
        self.request_id_factory = request_id_factory or (lambda: uuid.uuid4().hex)

    def ask(
        self,
        question: str,
        user: UserContext,
        top_k: int,
    ) -> AskResult:
        request_id = self._new_request_id()
        response = self._send(
            "POST",
            "/agent/v2/chat",
            request_id=request_id,
            json={
                "question": question,
                "user_context": user.model_dump(mode="json"),
                "top_k": top_k,
            },
            accepted_statuses={200},
        )
        payload = self._validated_json(response, AnswerResponse, request_id)
        body_id = payload.trace.get("request_id")
        if body_id != request_id:
            raise _invalid_response(request_id)
        return AskResult(request_id=request_id, response=payload)

    def readiness(self) -> ReadinessSnapshot:
        request_id = self._new_request_id()
        response = self._send(
            "GET",
            "/health/ready",
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
            request_id=lookup_id,
            accepted_statuses={200},
        )
        trace = self._validated_json(response, RequestTrace, lookup_id)
        if trace.request_id != request_id:
            raise _invalid_response(lookup_id)
        return trace

    def feedback(
        self,
        *,
        question: str,
        answer: str,
        helpful: bool,
    ) -> FeedbackResponse:
        request_id = self._new_request_id()
        response = self._send(
            "POST",
            "/feedback",
            request_id=request_id,
            json={
                "question": question,
                "answer": answer,
                "helpful": helpful,
            },
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
        request_id: str,
        accepted_statuses: set[int],
        json: dict[str, Any] | None = None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "headers": {"X-Request-ID": request_id},
            "timeout": self.timeout_seconds,
        }
        if json is not None:
            kwargs["json"] = json
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
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
    headers = getattr(response, "headers", {})
    value = headers.get("X-Request-ID") or headers.get("x-request-id")
    return str(value) if value else None


def _invalid_response(request_id: str) -> UiApiError:
    return UiApiError(
        code="invalid_service_response",
        safe_message="The service returned an invalid response.",
        request_id=request_id,
        retryable=False,
    )


__all__ = [
    "AskResult",
    "EnterpriseRagClient",
    "UiApiError",
]
