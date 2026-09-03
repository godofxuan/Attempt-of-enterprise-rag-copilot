import requests

from app.config import get_settings
from app.runtime.model_transport import perform_model_request
from app.security.model_endpoint import parse_pinned_model_endpoint


def _post_ollama(url: str, payload: dict, timeout: int) -> requests.Response:
    session = requests.Session()
    session.trust_env = False
    return session.post(url, json=payload, timeout=timeout)


def chat_with_ollama(
    model: str,
    messages: list[dict],
    *,
    response_format: str | dict | None = None,
    think: bool | str | None = None,
    timeout_seconds: float | None = None,
    max_output_tokens: int | None = None,
    seed: int | None = None,
) -> str:
    if max_output_tokens is not None and not 1 <= max_output_tokens <= 4096:
        raise ValueError("Ollama max output tokens must be between 1 and 4096")
    if seed is not None and (type(seed) is not int or not 0 <= seed <= 2_147_483_647):
        raise ValueError("Ollama seed must be an integer between 0 and 2147483647")
    settings = get_settings()
    endpoint = parse_pinned_model_endpoint(settings.llm_base_url)
    url = f"{endpoint.origin}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0},
    }
    if response_format is not None:
        payload["format"] = response_format
    if think is not None:
        payload["think"] = think
    if max_output_tokens is not None:
        payload["options"]["num_predict"] = max_output_tokens
    if seed is not None:
        payload["options"]["seed"] = seed

    result = perform_model_request(
        lambda timeout: _post_ollama(url, payload, timeout),
        operation="chat",
        timeout_seconds=(
            timeout_seconds
            if timeout_seconds is not None
            else settings.model_request_timeout_seconds
        ),
        max_attempts=settings.model_max_attempts,
        backoff_seconds=settings.model_retry_backoff_ms / 1000.0,
    )
    data = result.response.json()
    return data["message"]["content"]
