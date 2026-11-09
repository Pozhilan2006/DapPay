from __future__ import annotations

from app.core.config import get_settings


class PayPalClient:
    """Placeholder client for PayPal API operations."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def get_base_url(self) -> str:
        return self.settings.paypal_base_url

    def is_configured(self) -> bool:
        return bool(self.settings.paypal_client_id and self.settings.paypal_client_secret)
