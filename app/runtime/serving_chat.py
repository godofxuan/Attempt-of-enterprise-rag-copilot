"""Fixed serving policy; Ollama receives the context size on every request."""

from app.config import get_settings
from app.ollama_chat import _post_ollama
from app.runtime.model_transport import perform_model_request
from app.security.model_endpoint import parse_pinned_model_endpoint

SERVING_CONTEXT_TOKENS = 8192
SERVING_OUTPUT_TOKENS = 1024


def serving_chat(
    model: str,
    messages: list[dict],
    *,
    response_format: str | dict | None = None,
    think: bool | str | None = None,
    max_output_tokens: int = SERVING_OUTPUT_TOKENS,
    seed: int | None = None,
) -> str:
    # Keep the generation capture hook compatible without allowing policy drift.
    if type(max_output_tokens) is not int or max_output_tokens != SERVING_OUTPUT_TOKENS:
        raise ValueError("serving output limit is fixed at 1024")
    if seed is not None and (type(seed) is not int or not 0 <= seed <= 2_147_483_647):
        raise ValueError("Ollama seed must be an integer between 0 and 2147483647")
    settings = get_settings()
    endpoint = parse_pinned_model_endpoint(settings.llm_base_url)
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0,
            "num_predict": SERVING_OUTPUT_TOKENS,
            "num_ctx": SERVING_CONTEXT_TOKENS,
        },
    }
    if response_format is not None:
        payload["format"] = response_format
    if think is not None:
        payload["think"] = think
    if seed is not None:
        payload["options"]["seed"] = seed
    result = perform_model_request(
        lambda timeout: _post_ollama(f"{endpoint.origin}/api/chat", payload, timeout),
        operation="chat",
        timeout_seconds=settings.model_request_timeout_seconds,
        max_attempts=settings.model_max_attempts,
        backoff_seconds=settings.model_retry_backoff_ms / 1000.0,
    )
    return result.response.json()["message"]["content"]
