"""Structured output schema for AI investigation responses."""


def response_schema() -> dict[str, list[str]]:
    return {
        "required_fields": ["summary", "root_cause", "recommendations", "confidence"],
    }
