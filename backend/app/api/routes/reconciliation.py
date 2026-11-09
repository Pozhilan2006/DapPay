from fastapi import APIRouter

router = APIRouter(prefix="/reconciliation", tags=["Reconciliation"])


@router.get("")
def get_reconciliation_status() -> dict[str, str]:
    return {"status": "placeholder", "message": "Reconciliation engine is scaffolded."}


@router.post("/run")
def run_reconciliation() -> dict[str, str]:
    return {"status": "placeholder", "message": "Run reconciliation job here."}
