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
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
