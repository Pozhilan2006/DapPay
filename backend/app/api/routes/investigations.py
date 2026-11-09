from fastapi import APIRouter

router = APIRouter(prefix="/investigations", tags=["Investigations"])


@router.get("")
def list_investigations() -> dict[str, str]:
    return {"status": "placeholder", "message": "Investigation workflows will be implemented here."}


@router.post("/new")
def create_investigation() -> dict[str, str]:
    return {"status": "placeholder", "message": "Create new investigation workflow."}
