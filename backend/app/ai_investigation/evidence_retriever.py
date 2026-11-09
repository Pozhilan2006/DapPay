"""Evidence retrieval layer for contextual analysis."""


def retrieve_evidence(*, event_id: str) -> list[dict]:
    return [{"event_id": event_id, "evidence": []}]
