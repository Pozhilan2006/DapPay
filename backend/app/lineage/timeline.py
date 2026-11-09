"""Time-based event chronology utilities."""


def build_timeline(events: list[dict]) -> list[dict]:
    return sorted(events, key=lambda item: item.get("created_at", ""))
