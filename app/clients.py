from functools import lru_cache

from openai import OpenAI

from app.config import get_settings
from app.security.model_endpoint import parse_pinned_model_endpoint


@lru_cache
def get_ollama_client() -> OpenAI:
    settings = get_settings()
    endpoint = parse_pinned_model_endpoint(settings.llm_base_url)
    return OpenAI(
        base_url=endpoint.openai_base_url,
        api_key=settings.llm_api_key,
    )
