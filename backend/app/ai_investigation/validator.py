"""Validation rules for investigation output quality."""


def validate_response(response: dict) -> bool:
    return isinstance(response, dict) and "summary" in response
