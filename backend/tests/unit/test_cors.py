import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app


def _settings(
    *,
    app_env: str = "development",
    origins: list[str] | None = None,
) -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV=app_env,
        CORS_ALLOWED_ORIGINS=origins or [],
    )


def test_development_defaults_to_local_frontend_origins_only():
    client = TestClient(create_app(_settings()))

    response = client.options(
        "/api/payments",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    rejected = client.options(
        "/api/payments",
        headers={
            "Origin": "https://unapproved.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers


def test_configured_production_origin_allows_auth_header_preflight():
    client = TestClient(
        create_app(
            _settings(
                app_env="production",
                origins=["https://payments.example.com"],
            )
        )
    )

    response = client.options(
        "/api/payments",
        headers={
            "Origin": "https://payments.example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert (
        response.headers["access-control-allow-origin"]
        == "https://payments.example.com"
    )
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "GET" in response.headers["access-control-allow-methods"]


@pytest.mark.parametrize(
    "app_env,origins",
    [
        ("production", []),
        ("production", ["*"]),
        ("production", ["http://payments.example.com"]),
        ("staging", []),
    ],
)
def test_non_development_requires_explicit_secure_origins(app_env, origins):
    with pytest.raises(ValidationError):
        _settings(app_env=app_env, origins=origins)


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*.example.com",
        "https://payments.example.com/path",
        "https://user:password@payments.example.com",
        "file://payments.example.com",
    ],
)
def test_cors_rejects_wildcards_and_non_origin_urls(origin):
    with pytest.raises(ValidationError):
        _settings(origins=[origin])
