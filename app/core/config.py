from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field("local", alias="APP_ENV")
    app_debug: bool = Field(True, alias="APP_DEBUG")
    app_timezone: str = Field("Europe/Moscow", alias="APP_TIMEZONE")
    session_ttl_hours: int = Field(72, alias="SESSION_TTL_HOURS")
    hold_ttl_minutes: int = Field(10, alias="HOLD_TTL_MINUTES")
    handoff_ttl_minutes: int = Field(60, alias="HANDOFF_TTL_MINUTES")
    message_summary_enabled: bool = Field(True, alias="MESSAGE_SUMMARY_ENABLED")
    message_summary_after_hours: int = Field(72, alias="MESSAGE_SUMMARY_AFTER_HOURS")
    message_summary_interval_seconds: int = Field(
        3600, alias="MESSAGE_SUMMARY_INTERVAL_SECONDS"
    )
    message_summary_batch_conversations: int = Field(
        20, alias="MESSAGE_SUMMARY_BATCH_CONVERSATIONS"
    )

    db_host: str = Field(..., alias="DB_HOST")
    db_port: int = Field(5432, alias="DB_PORT")
    db_name: str = Field(..., alias="DB_NAME")
    db_user: str = Field(..., alias="DB_USER")
    db_password: str = Field(..., alias="DB_PASSWORD")
    db_charset: str = Field("utf8", alias="DB_CHARSET")
    db_sslmode: str = Field("verify-full", alias="DB_SSLMODE")
    db_sslrootcert: str = Field("~/.postgresql/root.crt", alias="DB_SSLROOTCERT")
    db_target_session_attrs: str = Field(
        "read-write", alias="DB_TARGET_SESSION_ATTRS"
    )
    db_connect_timeout: int = Field(15, alias="DB_CONNECT_TIMEOUT")

    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    telegram_webhook_url: str = Field("", alias="TELEGRAM_WEBHOOK_URL")

    ai_provider: str = Field("openrouter", alias="AI_PROVIDER")
    openai_api_key: str = Field("", alias="OPENAI_API_KEY")
    openrouter_api_key: str = Field("", alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        "https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    openai_model: str = Field("anthropic/claude-sonnet-4", alias="OPENAI_MODEL")
    openai_temperature: float = Field(0.2, alias="OPENAI_TEMPERATURE")
    openai_max_tokens: int = Field(700, alias="OPENAI_MAX_TOKENS")
    voice_transcription_enabled: bool = Field(False, alias="VOICE_TRANSCRIPTION_ENABLED")
    voice_transcription_provider: str = Field(
        "openrouter", alias="VOICE_TRANSCRIPTION_PROVIDER"
    )
    voice_transcription_model: str = Field(
        "openai/whisper-large-v3", alias="VOICE_TRANSCRIPTION_MODEL"
    )
    voice_transcription_language: str = Field("ru", alias="VOICE_TRANSCRIPTION_LANGUAGE")
    voice_transcription_max_seconds: int = Field(
        120, alias="VOICE_TRANSCRIPTION_MAX_SECONDS"
    )

    yclients_base_url: str = Field(
        "https://api.yclients.com/api/v1", alias="YCLIENTS_BASE_URL"
    )
    yclients_partner_token: str = Field("", alias="YCLIENTS_PARTNER_TOKEN")
    yclients_user_token: str = Field("", alias="YCLIENTS_USER_TOKEN")
    yclients_company_id: str = Field("", alias="YCLIENTS_COMPANY_ID")
    yclients_sync_enabled: bool = Field(True, alias="YCLIENTS_SYNC_ENABLED")
    yclients_sync_interval_seconds: int = Field(60, alias="YCLIENTS_SYNC_INTERVAL_SECONDS")
    yclients_sync_days_back: int = Field(1, alias="YCLIENTS_SYNC_DAYS_BACK")
    yclients_sync_days_forward: int = Field(60, alias="YCLIENTS_SYNC_DAYS_FORWARD")

    payment_provider: str = Field("", alias="PAYMENT_PROVIDER")
    payment_shop_id: str = Field("", alias="PAYMENT_SHOP_ID")
    payment_secret_key: str = Field("", alias="PAYMENT_SECRET_KEY")
    payment_success_url: str = Field("", alias="PAYMENT_SUCCESS_URL")
    payment_fail_url: str = Field("", alias="PAYMENT_FAIL_URL")
    prepayment_amount_rub: int = Field(2000, alias="PREPAYMENT_AMOUNT_RUB")
    payment_status_sync_enabled: bool = Field(
        True, alias="PAYMENT_STATUS_SYNC_ENABLED"
    )
    payment_status_sync_interval_seconds: int = Field(
        60, alias="PAYMENT_STATUS_SYNC_INTERVAL_SECONDS"
    )
    yookassa_webhook_enabled: bool = Field(False, alias="YOOKASSA_WEBHOOK_ENABLED")
    yookassa_webhook_host: str = Field("0.0.0.0", alias="YOOKASSA_WEBHOOK_HOST")
    yookassa_webhook_port: int = Field(8088, alias="YOOKASSA_WEBHOOK_PORT")
    yookassa_webhook_path: str = Field("/webhooks/yookassa", alias="YOOKASSA_WEBHOOK_PATH")
    yookassa_webhook_secret: str = Field("", alias="YOOKASSA_WEBHOOK_SECRET")
    yookassa_webhook_url: str = Field("", alias="YOOKASSA_WEBHOOK_URL")

    admin_telegram_chat_id: str = Field("", alias="ADMIN_TELEGRAM_CHAT_ID")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    @computed_field
    @property
    def db_dsn(self) -> str:
        return (
            f"host={self.db_host} port={self.db_port} dbname={self.db_name} "
            f"user={self.db_user} password={self.db_password}"
        )

    def safe_summary(self) -> dict:
        return {
            "app_env": self.app_env,
            "app_timezone": self.app_timezone,
            "db_host": self.db_host,
            "db_port": self.db_port,
            "db_name": self.db_name,
            "db_sslmode": self.db_sslmode,
            "ai_provider": self.ai_provider,
            "openai_model": self.openai_model,
            "voice_transcription_enabled": self.voice_transcription_enabled,
            "telegram_configured": bool(self.telegram_bot_token),
            "openrouter_configured": bool(self.openrouter_api_key),
            "yclients_configured": bool(self.yclients_partner_token),
            "payment_provider": self.payment_provider,
            "payment_configured": bool(self.payment_shop_id and self.payment_secret_key),
            "yookassa_webhook_enabled": self.yookassa_webhook_enabled,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
