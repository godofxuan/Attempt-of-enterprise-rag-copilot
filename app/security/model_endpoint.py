from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


_ALLOWED_PATHS = {"", "/", "/v1", "/v1/"}
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_ERROR = "model endpoint must be a pinned local Ollama origin"


@dataclass(frozen=True)
class PinnedModelEndpoint:
    origin: str
    openai_base_url: str


def parse_pinned_model_endpoint(value: str) -> PinnedModelEndpoint:
    if value != value.strip() or not value.isascii():
        raise ValueError(_ERROR)
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(_ERROR) from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in _LOOPBACK_HOSTS
        or port is None
        or not 1 <= port <= 65_535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in _ALLOWED_PATHS
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(_ERROR)

    if parsed.hostname == "localhost":
        host = "127.0.0.1"
    elif parsed.hostname == "::1":
        host = "[::1]"
    else:
        host = parsed.hostname
    origin = f"http://{host}:{port}"
    return PinnedModelEndpoint(
        origin=origin,
        openai_base_url=f"{origin}/v1",
    )


__all__ = ["PinnedModelEndpoint", "parse_pinned_model_endpoint"]
