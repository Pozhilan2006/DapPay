from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: Literal["development", "staging", "production"] = Field(default="development", alias="APP_ENV")
    debug: bool = Field(default=False, alias="DEBUG")
    secret_key: str = Field(default="change-me", alias="SECRET_KEY")
    database_url: str = Field(default="postgresql+psycopg://payrecon:payrecon@localhost:5432/payrecon", alias="DATABASE_URL")
    paypal_mode: Literal["sandbox", "live"] = Field(default="sandbox", alias="PAYPAL_MODE")
    paypal_client_id: str = Field(default="", alias="PAYPAL_CLIENT_ID")
    paypal_client_secret: str = Field(default="", alias="PAYPAL_CLIENT_SECRET")
    paypal_base_url: str = Field(default="https://api-m.sandbox.paypal.com", alias="PAYPAL_BASE_URL")
    paypal_webhook_id: str = Field(default="", alias="PAYPAL_WEBHOOK_ID")
    investigation_llm_provider: Literal["ollama"] = Field(
        default="ollama", alias="INVESTIGATION_LLM_PROVIDER"
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434", alias="OLLAMA_BASE_URL"
    )
    ollama_model: str = Field(default="", alias="OLLAMA_MODEL")
    investigation_llm_timeout_seconds: float = Field(
        default=30.0, gt=0, le=180, alias="INVESTIGATION_LLM_TIMEOUT_SECONDS"
    )
    investigation_missing_payment_minutes: int = Field(
        default=15, ge=0, le=10080, alias="INVESTIGATION_MISSING_PAYMENT_MINUTES"
    )
    investigation_webhook_delay_minutes: int = Field(
        default=15, ge=0, le=10080, alias="INVESTIGATION_WEBHOOK_DELAY_MINUTES"
    )
    investigation_merchant_update_minutes: int = Field(
        default=5, ge=0, le=10080, alias="INVESTIGATION_MERCHANT_UPDATE_MINUTES"
    )
    investigation_capture_confirmation_minutes: int = Field(
        default=15, ge=0, le=10080, alias="INVESTIGATION_CAPTURE_CONFIRMATION_MINUTES"
    )
    investigation_accounting_delay_minutes: int = Field(
        default=60, ge=0, le=10080, alias="INVESTIGATION_ACCOUNTING_DELAY_MINUTES"
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
