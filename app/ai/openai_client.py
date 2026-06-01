from functools import lru_cache

from openai import DefaultHttpxClient, OpenAI

from app.core.config import get_settings


@lru_cache
def get_ai_client() -> OpenAI:
    settings = get_settings()
    http_client = DefaultHttpxClient(
        timeout=25.0,
        trust_env=settings.http_trust_env,
    )
    if settings.ai_provider != "openrouter":
        return OpenAI(api_key=settings.openai_api_key or None, http_client=http_client)
    return OpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        http_client=http_client,
    )
