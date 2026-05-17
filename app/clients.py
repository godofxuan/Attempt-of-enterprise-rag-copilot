from functools import lru_cache

from openai import OpenAI

from app.config import get_settings


@lru_cache
def get_ollama_client() -> OpenAI:
    settings = get_settings()
    return OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
    )