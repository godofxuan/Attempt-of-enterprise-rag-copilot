from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import requests

from app.runtime.request_context import (
    RequestDeadlineExceeded,
    current_request_context,
    effective_timeout_seconds,
    remaining_seconds,
)


ModelOperation = Literal["chat", "embed"]
RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})


class ModelRequestError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        status_code: int | None,
        retryable: bool,
        attempts: int,
    ) -> None:
        super().__init__(f"model request failed ({code})")
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        self.attempts = attempts


@dataclass(frozen=True)
class ModelRequestResult:
    response: Any
    attempts: int
    retries: int


def perform_model_request(
    send: Callable[[float], Any],
    *,
    operation: str,
    timeout_seconds: float,
    max_attempts: int,
    backoff_seconds: float,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> ModelRequestResult:
    if operation not in {"chat", "embed"}:
        raise ValueError("operation must be 'chat' or 'embed'")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if backoff_seconds < 0:
        raise ValueError("backoff_seconds must not be negative")

    attempts = 0
    retries = 0
    while attempts < max_attempts:
        try:
            timeout = effective_timeout_seconds(
                timeout_seconds,
                clock_ms=lambda: clock() * 1000.0,
            )
        except RequestDeadlineExceeded:
            _record_final_error()
            raise _deadline_error(attempts) from None

        attempts += 1
        started = clock()
        try:
            response = send(timeout)
            response.raise_for_status()
        except Exception as exc:
            _record_attempt(
                operation,
                status="error",
                duration_ms=max(0.0, (clock() - started) * 1000.0),
            )
            error = _safe_error(exc, attempts)
            if not error.retryable or attempts >= max_attempts:
                _record_final_error()
                raise error from exc
            if not _backoff_fits_deadline(
                backoff_seconds,
                clock=clock,
            ):
                _record_final_error()
                raise _deadline_error(attempts) from None
            _record_retry()
            retries += 1
            if backoff_seconds:
                sleeper(backoff_seconds)
            continue

        _record_attempt(
            operation,
            status="ok",
            duration_ms=max(0.0, (clock() - started) * 1000.0),
        )
        return ModelRequestResult(
            response=response,
            attempts=attempts,
            retries=retries,
        )

    raise AssertionError("bounded model request loop exhausted unexpectedly")


def _safe_error(exc: Exception, attempts: int) -> ModelRequestError:
    if isinstance(exc, requests.Timeout):
        return ModelRequestError(
            code="transport_timeout",
            status_code=None,
            retryable=True,
            attempts=attempts,
        )
    if isinstance(exc, requests.ConnectionError):
        return ModelRequestError(
            code="transport_connection",
            status_code=None,
            retryable=True,
            attempts=attempts,
        )
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return ModelRequestError(
            code=f"http_{status_code}",
            status_code=status_code,
            retryable=status_code in RETRYABLE_STATUS_CODES,
            attempts=attempts,
        )
    return ModelRequestError(
        code="transport_error",
        status_code=None,
        retryable=False,
        attempts=attempts,
    )


def _deadline_error(attempts: int) -> ModelRequestError:
    return ModelRequestError(
        code="deadline_exhausted",
        status_code=None,
        retryable=False,
        attempts=attempts,
    )


def _backoff_fits_deadline(
    backoff_seconds: float,
    *,
    clock: Callable[[], float],
) -> bool:
    remaining = remaining_seconds(clock_ms=lambda: clock() * 1000.0)
    return remaining is None or remaining > backoff_seconds


def _record_attempt(operation: str, *, status: str, duration_ms: float) -> None:
    context = current_request_context()
    if context is None:
        return
    context.model_calls += 1
    context.spans.append(
        {
            "name": f"model.{operation}",
            "status": status,
            "duration_ms": duration_ms,
        }
    )


def _record_retry() -> None:
    context = current_request_context()
    if context is not None:
        context.model_retries += 1


def _record_final_error() -> None:
    context = current_request_context()
    if context is not None:
        context.model_errors += 1


__all__ = [
    "ModelRequestError",
    "ModelRequestResult",
    "RETRYABLE_STATUS_CODES",
    "perform_model_request",
]
