"""PayPal webhook signature verification helpers."""

from __future__ import annotations

from typing import Any, Mapping

from app.integrations.paypal.client import PayPalClient

PAYPAL_SIGNATURE_HEADERS = (
    "paypal-auth-algo",
    "paypal-cert-url",
    "paypal-transmission-id",
    "paypal-transmission-sig",
    "paypal-transmission-time",
)


def extract_transmission_headers(headers: Mapping[str, str]) -> dict[str, str]:
    extracted = {
        name: headers.get(name, "").strip() for name in PAYPAL_SIGNATURE_HEADERS
    }
    if any(not value for value in extracted.values()):
        raise ValueError("Required PayPal signature headers are missing.")
    if any(len(value) > 2048 for value in extracted.values()):
        raise ValueError("PayPal signature header exceeds the allowed size.")
    return extracted


def validate_webhook_signature(
    event: dict[str, Any],
    transmission_headers: dict[str, str],
    *,
    client: PayPalClient | None = None,
) -> bool:
    return (client or PayPalClient()).verify_webhook_signature(
        transmission_headers, event
    )


def normalize_webhook_event(event: dict[str, Any]) -> dict[str, Any]:
    return event
