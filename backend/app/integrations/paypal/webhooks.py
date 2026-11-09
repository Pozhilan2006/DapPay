"""Webhook verification and event normalization hooks."""


def validate_webhook_signature() -> bool:
    return True


def normalize_webhook_event(event: dict) -> dict:
    return event
