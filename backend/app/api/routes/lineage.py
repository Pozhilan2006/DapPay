from fastapi import APIRouter, Depends

from app.core.security import Role, require_roles

router = APIRouter(prefix="/lineage", tags=["Lineage"])


@router.get(
    "",
    dependencies=[Depends(require_roles(Role.ADMIN, Role.MERCHANT, Role.READ_ONLY))],
)
def get_lineage_graph() -> dict[str, str]:
    return {
        "status": "placeholder",
        "message": "Lineage graph endpoint will be implemented here.",
    }
