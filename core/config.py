from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    app_timezone: str = "Europe/Moscow"
    hold_ttl_minutes: int = 15

    telegram_bot_token: str = ""
    telegram_proxy_url: str = ""
    admin_telegram_chat_id: str = ""

    ai_provider: str = "deepseek"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    openai_model: str = "deepseek-chat"
    openai_temperature: float = 0.1
    openai_max_tokens: int = 700

    yclients_base_url: str = "https://api.yclients.com/api/v1"
    yclients_partner_token: str = ""
    yclients_user_token: str = ""
    yclients_company_id: str = ""

    db_host: str = ""
    db_port: int = 5432
    db_name: str = ""
    db_user: str = ""
    db_password: str = ""
    db_sslmode: str = "prefer"
    db_sslrootcert: str = "~/.postgresql/root.crt"
    db_target_session_attrs: str = "read-write"
    db_connect_timeout: int = 15

    payment_provider: str = "yookassa"
    payment_shop_id: str = ""
    payment_secret_key: str = ""
    payment_success_url: str = ""
    prepayment_amount_rub: int = 1

    sqlite_path: str = Field(default="bot.sqlite3")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def sqlite_path() -> Path:
    path = Path(get_settings().sqlite_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path
