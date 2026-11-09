from fastapi import APIRouter

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.get("")
def list_webhooks() -> dict[str, str]:
    return {"status": "placeholder", "message": "Webhook ingestion endpoint will be implemented here."}


@router.post("")
def receive_webhook() -> dict[str, str]:
    return {"status": "placeholder", "message": "Webhook verification and ingestion will be implemented here."}
