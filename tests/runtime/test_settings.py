from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_e5_runtime_setting_defaults_are_bounded() -> None:
    settings = Settings(_env_file=None)

    assert settings.api_request_deadline_ms == 15_000
    assert settings.model_request_timeout_seconds == 12.0
    assert settings.model_max_attempts == 2
    assert settings.model_retry_backoff_ms == 100
    assert settings.structured_generation_max_attempts == 2
    assert settings.readiness_probe_timeout_seconds == 2.0
    assert settings.readiness_ttl_seconds == 5.0
    assert settings.trace_buffer_size == 200
    assert settings.metrics_latency_buffer_size == 1_000
    assert settings.sqlite_timeout_seconds == 5.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("api_request_deadline_ms", 99),
        ("model_request_timeout_seconds", 0),
        ("model_max_attempts", 4),
        ("model_retry_backoff_ms", -1),
        ("structured_generation_max_attempts", 3),
        ("readiness_probe_timeout_seconds", 0),
        ("readiness_ttl_seconds", 0),
        ("trace_buffer_size", 9),
        ("metrics_latency_buffer_size", 9),
        ("sqlite_timeout_seconds", 0),
    ],
)
def test_invalid_e5_runtime_settings_fail_closed(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})
