import time
from urllib.parse import urlparse

import requests

from app.config import get_settings


def _ollama_api_base_url(llm_base_url: str) -> str:
    parsed = urlparse(llm_base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


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
) -> str:
    settings = get_settings()
    url = f"{_ollama_api_base_url(settings.llm_base_url)}/api/chat"
    max_attempts = 3
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

    for attempt in range(1, max_attempts + 1):
        try:
            response = _post_ollama(url, payload, timeout=180)
            response.raise_for_status()
            data = response.json()
            return data["message"]["content"]
        except Exception as exc:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)

            if status_code == 503 and attempt < max_attempts:
                time.sleep(attempt * 2)
                continue

            detail = ""
            if response is not None:
                detail = f" Ollama response: {response.text[:500]}"

            raise RuntimeError(
                f"Chat request failed at {url} for model {model!r}: {exc}.{detail}"
            ) from exc
