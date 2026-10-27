from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg  # type: ignore
from fastapi import APIRouter, Depends, HTTPException, Response, status  # type: ignore

from app.config import Settings, get_settings
from app.database import get_database_connection
from app.schemas import (
    AuthResponse,
    AuthUser,
    LoginRequest,
    LogoutResponse,
)
from app.security.dependencies import CurrentUser
from app.security.passwords import hash_password, verify_password
from app.security.tokens import create_access_token


router = APIRouter(prefix="/api/auth", tags=["Authentication"])

MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15

# Dùng để tránh khác biệt thời gian phản hồi khi username không tồn tại.
DUMMY_PASSWORD_HASH = hash_password("dummy-password")


def to_auth_user(user: dict[str, Any]) -> AuthUser:
    return AuthUser(
        id=user["id"],
        username=user["username"],
        full_name=user["full_name"],
        email=user["email"],
        department=user["department"],
        role=user["role"],
        permission_group_id=user.get("permission_group_id"),
    )


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    response: Response,
    connection=Depends(get_database_connection),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    user = connection.execute(
        """
        SELECT
            id,
            username,
            password_hash,
            full_name,
            email,
            department,
            role,
            permission_group_id,
            account_status,
            session_version,
            failed_login_attempts,
            locked_until
        FROM rag_client.users
        WHERE lower(username) = lower(%s)
           OR lower(email) = lower(%s)
        """,
        (payload.username, payload.username),
    ).fetchone()

    if user is None:
        verify_password(payload.password, DUMMY_PASSWORD_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tên đăng nhập hoặc mật khẩu không đúng.",
        )

    now = datetime.now(UTC)

    if user["account_status"] == "disabled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản đã bị vô hiệu hóa.",
        )

    if user["account_status"] == "locked":
        locked_until = user["locked_until"]

        if locked_until is not None and locked_until > now:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Tài khoản đang tạm khóa. Vui lòng thử lại sau.",
            )

        connection.execute(
            """
            UPDATE rag_client.users
            SET account_status = 'active',
                failed_login_attempts = 0,
                locked_until = NULL,
                updated_at = NOW()
            WHERE id = %s
            """,
            (user["id"],),
        )

        user["account_status"] = "active"
        user["failed_login_attempts"] = 0
        user["locked_until"] = None

    if not verify_password(payload.password, user["password_hash"]):
        failed_attempts = user["failed_login_attempts"] + 1
        should_lock = failed_attempts >= MAX_FAILED_ATTEMPTS
        locked_until = (
            now + timedelta(minutes=LOCK_MINUTES)
            if should_lock
            else None
        )

        connection.execute(
            """
            UPDATE rag_client.users
            SET failed_login_attempts = %s,
                account_status = %s,
                locked_until = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                failed_attempts,
                "locked" if should_lock else "active",
                locked_until,
                user["id"],
            ),
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tên đăng nhập hoặc mật khẩu không đúng.",
        )

    connection.execute(
        """
        UPDATE rag_client.users
        SET failed_login_attempts = 0,
            locked_until = NULL,
            account_status = 'active',
            last_login_at = NOW(),
            updated_at = NOW()
        WHERE id = %s
        """,
        (user["id"],),
    )

    token = create_access_token(
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
        session_version=user["session_version"],
        settings=settings,
    )

    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.auth_token_expire_minutes * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="strict",
        path="/",
    )

    return AuthResponse(user=to_auth_user(user))


@router.get("/me", response_model=AuthResponse)
def me(current_user: CurrentUser) -> AuthResponse:
    return AuthResponse(user=current_user)


@router.post("/logout", response_model=LogoutResponse)
def logout(
    response: Response,
    current_user: CurrentUser,
    connection=Depends(get_database_connection),
    settings: Settings = Depends(get_settings),
) -> LogoutResponse:
    connection.execute(
        """
        UPDATE rag_client.users
        SET session_version = session_version + 1,
            last_logout_at = NOW(),
            updated_at = NOW()
        WHERE id = %s
        """,
        (current_user.id,),
    )

    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="strict",
    )

    return LogoutResponse(message="Đăng xuất thành công.")
