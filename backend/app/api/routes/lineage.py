from fastapi import APIRouter

router = APIRouter(prefix="/lineage", tags=["Lineage"])


@router.get("")
def get_lineage_graph() -> dict[str, str]:
    return {"status": "placeholder", "message": "Lineage graph endpoint will be implemented here."}
