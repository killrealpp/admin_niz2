from functools import lru_cache

from openai import OpenAI

from app.core.config import get_settings


@lru_cache
def get_ai_client() -> OpenAI:
    settings = get_settings()
    if settings.ai_provider != "openrouter":
        return OpenAI(api_key=settings.openai_api_key or None, timeout=25.0)
    return OpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        timeout=25.0,
    )
