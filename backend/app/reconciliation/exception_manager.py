"""Exception orchestration for reconciliation failures."""


def create_exception(event_id: str) -> dict[str, str]:
    return {"event_id": event_id, "status": "logged"}
