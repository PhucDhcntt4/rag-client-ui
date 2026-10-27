from typing import Annotated, Any
from uuid import UUID

import psycopg  # type: ignore
from fastapi import Depends, HTTPException, Request, status  # type: ignore

from app.config import Settings, get_settings
from app.database import get_database_connection
from app.schemas import AuthUser
from app.security.tokens import decode_access_token


DatabaseConnection = Annotated[
    psycopg.Connection[dict[str, Any]],
    Depends(get_database_connection),
]


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Bạn cần đăng nhập để sử dụng hệ thống.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_session_payload(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    token = request.cookies.get(settings.auth_cookie_name)

    if not token:
        raise unauthorized()

    try:
        return decode_access_token(token, settings)
    except (ValueError, TypeError, KeyError):
        raise unauthorized()


SessionPayload = Annotated[dict[str, Any], Depends(get_session_payload)]


def get_current_user(
    payload: SessionPayload,
    connection: DatabaseConnection,
) -> AuthUser:
    try:
        user_id = UUID(payload["sub"])
        token_session_version = int(payload["ver"])
    except (ValueError, TypeError, KeyError):
        raise unauthorized()

    user = connection.execute(
        """
        SELECT
            id,
            username,
            full_name,
            email,
            department,
            role,
            permission_group_id,
            account_status,
            session_version
        FROM rag_client.users
        WHERE id = %s
        """,
        (user_id,),
    ).fetchone()

    if user is None:
        raise unauthorized()

    if user["account_status"] != "active":
        raise unauthorized()

    if user["session_version"] != token_session_version:
        raise unauthorized()

    return AuthUser(
        id=user["id"],
        username=user["username"],
        full_name=user["full_name"],
        email=user["email"],
        department=user["department"],
        role=user["role"],
        permission_group_id=user.get("permission_group_id"),
    )


CurrentUser = Annotated[AuthUser, Depends(get_current_user)]


def require_admin(current_user: CurrentUser) -> AuthUser:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ quản trị viên được sử dụng chức năng này.",
        )
    return current_user


AdminUser = Annotated[AuthUser, Depends(require_admin)]
