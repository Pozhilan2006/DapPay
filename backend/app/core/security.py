from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

from app.core.config import Settings, get_settings


class Role(StrEnum):
    ADMIN = "admin"
    MERCHANT = "merchant"
    READ_ONLY = "read_only"


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)

    subject: str
    role: Role
    merchant_id: str | None


_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Valid bearer authentication is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise _unauthorized()
    if len(settings.auth_jwt_secret.encode("utf-8")) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is not configured.",
        )
    try:
        claims = jwt.decode(
            credentials.credentials,
            settings.auth_jwt_secret,
            algorithms=["HS256"],
            issuer=settings.auth_jwt_issuer,
            audience=settings.auth_jwt_audience,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "role"]},
        )
        role = Role(claims["role"])
        subject = claims["sub"]
        merchant_id = claims.get("merchant_id")
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError
        if role != Role.ADMIN and (
            not isinstance(merchant_id, str)
            or not merchant_id.strip()
            or len(merchant_id) > 128
        ):
            raise ValueError
        if (
            role == Role.ADMIN
            and merchant_id is not None
            and (not isinstance(merchant_id, str) or len(merchant_id) > 128)
        ):
            raise ValueError
        return Principal(
            subject=subject,
            role=role,
            merchant_id=merchant_id,
        )
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise _unauthorized() from None


def require_roles(*roles: Role) -> Callable:
    allowed = frozenset(roles)

    def authorize(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )
        return principal

    return authorize
