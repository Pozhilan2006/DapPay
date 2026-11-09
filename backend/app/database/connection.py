from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.core.config import get_settings


def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True)
