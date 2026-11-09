from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.payments import router as payments_router
from app.api.routes.orders import router as orders_router
from app.api.routes.webhooks import router as webhooks_router
from app.api.routes.reconciliation import router as reconciliation_router
from app.api.routes.lineage import router as lineage_router
from app.api.routes.investigations import router as investigations_router

api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(payments_router)
api_router.include_router(orders_router)
api_router.include_router(webhooks_router)
api_router.include_router(reconciliation_router)
api_router.include_router(lineage_router)
api_router.include_router(investigations_router)
