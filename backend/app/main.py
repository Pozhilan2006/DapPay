from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    allowed_origins = app_settings.cors_allowed_origins
    if not allowed_origins and app_settings.app_env == "development":
        allowed_origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]

    application = FastAPI(
        title="PayRecon AI",
        description="Financial intelligence and reconciliation platform for PayPal and merchant records.",
        version="0.1.0",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "Authorization", "Content-Type"],
    )
    application.include_router(api_router)
    application.get("/")(read_root)
    return application


def read_root() -> dict[str, str]:
    return {"message": "PayRecon AI API is running."}


app = create_app()
