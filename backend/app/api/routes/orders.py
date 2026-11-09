from fastapi import APIRouter

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.get("")
def list_orders() -> dict[str, str]:
    return {"status": "placeholder", "message": "Orders endpoint will be implemented here."}


@router.get("/{order_id}")
def get_order(order_id: str) -> dict[str, str]:
    return {"order_id": order_id, "status": "placeholder"}
