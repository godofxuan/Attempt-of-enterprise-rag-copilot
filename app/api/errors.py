from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.runtime.request_context import current_request_id


LOGGER = logging.getLogger("enterprise_rag.api")


class ApiErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)
    request_id: str = Field(min_length=1, max_length=64)
    retryable: bool = False


class ApiErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ApiErrorDetail


class ApiError(RuntimeError):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.safe_message = message
        self.retryable = retryable


def error_payload(
    *,
    code: str,
    message: str,
    request_id: str,
    retryable: bool,
) -> dict:
    return ApiErrorResponse(
        error=ApiErrorDetail(
            code=code,
            message=message,
            request_id=request_id,
            retryable=retryable,
        )
    ).model_dump(mode="json")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or current_request_id() or "untracked"


def _response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
) -> JSONResponse:
    request.state.error_code = code
    request.state.outcome = code
    return JSONResponse(
        status_code=status_code,
        content=error_payload(
            code=code,
            message=message,
            request_id=_request_id(request),
            retryable=retryable,
        ),
    )


async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return _response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.safe_message,
        retryable=exc.retryable,
    )


async def _validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return _response(
        request,
        status_code=422,
        code="request_validation_failed",
        message="Request validation failed.",
    )


async def _http_error_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    if exc.status_code == 404:
        return _response(
            request,
            status_code=404,
            code="not_found",
            message="The requested resource was not found.",
        )
    return _response(
        request,
        status_code=exc.status_code,
        code="http_error",
        message="The request could not be completed.",
    )


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    LOGGER.error("unhandled_exception request_id=%s", _request_id(request))
    return _response(
        request,
        status_code=500,
        code="internal_error",
        message="The service could not complete the request.",
    )


__all__ = [
    "ApiError",
    "ApiErrorDetail",
    "ApiErrorResponse",
    "error_payload",
    "install_error_handlers",
]
