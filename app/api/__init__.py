"""Explicit lazy legacy exports; importing product routes never builds legacy resources."""

from importlib import import_module

_EXPORTS = {
    "ApiError": ("app.api.errors", "ApiError"),
    "ApiErrorResponse": ("app.api.errors", "ApiErrorResponse"),
    "install_error_handlers": ("app.api.errors", "install_error_handlers"),
    "RequestContextMiddleware": ("app.api.middleware", "RequestContextMiddleware"),
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    value = getattr(import_module(target[0]), target[1])
    globals()[name] = value
    return value
