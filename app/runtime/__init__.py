from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "RequestContext": ("app.runtime.request_context", "RequestContext"),
    "RequestDeadlineExceeded": (
        "app.runtime.request_context",
        "RequestDeadlineExceeded",
    ),
    "bind_request_context": ("app.runtime.request_context", "bind_request_context"),
    "current_request_context": (
        "app.runtime.request_context",
        "current_request_context",
    ),
    "current_request_id": ("app.runtime.request_context", "current_request_id"),
    "effective_timeout_seconds": (
        "app.runtime.request_context",
        "effective_timeout_seconds",
    ),
    "remaining_seconds": ("app.runtime.request_context", "remaining_seconds"),
    "reset_request_context": ("app.runtime.request_context", "reset_request_context"),
    "ModelRequestError": ("app.runtime.model_transport", "ModelRequestError"),
    "ModelRequestResult": ("app.runtime.model_transport", "ModelRequestResult"),
    "perform_model_request": ("app.runtime.model_transport", "perform_model_request"),
    "ReadinessSnapshot": ("app.runtime.resources", "ReadinessSnapshot"),
    "ReadyIndexInfo": ("app.runtime.resources", "ReadyIndexInfo"),
    "RuntimeResources": ("app.runtime.resources", "RuntimeResources"),
    "ServiceContainer": ("app.runtime.resources", "ServiceContainer"),
    "build_service_container": ("app.runtime.resources", "build_service_container"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
