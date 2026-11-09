from fastapi import APIRouter

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.get("")
def list_payments() -> dict[str, str]:
    return {"status": "placeholder", "message": "Payment listing endpoint will be implemented here."}


@router.get("/{payment_id}")
def get_payment(payment_id: str) -> dict[str, str]:
    return {"payment_id": payment_id, "status": "placeholder"}
