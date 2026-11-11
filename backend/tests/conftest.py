from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.session import get_db
from app.core.config import Settings, get_settings
from app.main import app
from app.models import (
    InvestigationReportRecord,
    MerchantOrder,
    PaymentCapture,
    ReconciliationExceptionRecord,
    WebhookEvent,
)

_registered_models = (
    InvestigationReportRecord,
    MerchantOrder,
    PaymentCapture,
    ReconciliationExceptionRecord,
    WebhookEvent,
)
_TEST_JWT_SECRET = "unit-tests-only-secret-with-32-bytes-minimum"
assert {model.__tablename__ for model in _registered_models}.issubset(
    Base.metadata.tables
)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        del _connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with test_session() as session:
        yield session
        session.rollback()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def api_client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        AUTH_JWT_SECRET=_TEST_JWT_SECRET,
        AUTH_JWT_ISSUER="payrecon-tests",
        AUTH_JWT_AUDIENCE="payrecon-test-api",
    )
    token = create_test_token("admin")
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_settings, None)


def create_test_token(
    role: str,
    merchant_id: str | None = None,
    *,
    expires_in: timedelta = timedelta(minutes=5),
    secret: str = _TEST_JWT_SECRET,
) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "iss": "payrecon-tests",
        "aud": "payrecon-test-api",
        "sub": "unit-test-user",
        "role": role,
        "iat": now,
        "exp": now + expires_in,
    }
    if merchant_id is not None:
        claims["merchant_id"] = merchant_id
    return jwt.encode(claims, secret, algorithm="HS256")
