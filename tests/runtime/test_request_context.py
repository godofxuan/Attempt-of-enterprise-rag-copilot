from __future__ import annotations

import pytest

from app.runtime.request_context import (
    RequestDeadlineExceeded,
    bind_request_context,
    current_request_context,
    current_request_id,
    effective_timeout_seconds,
    remaining_seconds,
    reset_request_context,
)


def test_bind_exposes_request_id_and_deadline_then_reset_isolates_next_request() -> None:
    token = bind_request_context(
        "req-one",
        deadline_ms=1_000,
        clock_ms=lambda: 100.0,
    )
    try:
        assert current_request_id() == "req-one"
        assert remaining_seconds(clock_ms=lambda: 350.0) == pytest.approx(0.75)
    finally:
        reset_request_context(token)

    assert current_request_context() is None
    assert current_request_id() is None


def test_nested_request_context_restores_outer_value() -> None:
    outer = bind_request_context("outer", deadline_ms=1_000, clock_ms=lambda: 0.0)
    try:
        inner = bind_request_context("inner", deadline_ms=500, clock_ms=lambda: 0.0)
        try:
            assert current_request_id() == "inner"
        finally:
            reset_request_context(inner)
        assert current_request_id() == "outer"
    finally:
        reset_request_context(outer)


def test_effective_timeout_uses_smaller_request_remainder() -> None:
    token = bind_request_context("req", deadline_ms=500, clock_ms=lambda: 0.0)
    try:
        assert effective_timeout_seconds(
            12.0,
            clock_ms=lambda: 300.0,
        ) == pytest.approx(0.2)
    finally:
        reset_request_context(token)


def test_effective_timeout_uses_configured_value_without_request_context() -> None:
    assert effective_timeout_seconds(12.0) == 12.0
    assert remaining_seconds() is None


def test_effective_timeout_fails_before_io_when_deadline_is_exhausted() -> None:
    token = bind_request_context("req", deadline_ms=100, clock_ms=lambda: 0.0)
    try:
        with pytest.raises(RequestDeadlineExceeded) as exc_info:
            effective_timeout_seconds(12.0, clock_ms=lambda: 100.0)
    finally:
        reset_request_context(token)

    assert str(exc_info.value) == "request deadline exhausted"


def test_invalid_context_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="request ID"):
        bind_request_context("", deadline_ms=1_000)
    with pytest.raises(ValueError, match="deadline"):
        bind_request_context("req", deadline_ms=0)
