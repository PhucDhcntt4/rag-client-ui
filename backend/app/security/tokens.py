from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt  # type: ignore
from jwt.exceptions import InvalidTokenError  # type: ignore

from app.config import Settings


JWT_ALGORITHM = "HS256"


def create_access_token(
    *,
    user_id: UUID,
    username: str,
    role: str,
    session_version: int,
    settings: Settings,
) -> str:
    now = datetime.now(UTC)
    expires_at = now + timedelta(
        minutes=settings.auth_token_expire_minutes
    )

    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "ver": session_version,
        "iat": now,
        "exp": expires_at,
    }

    return jwt.encode(
        payload,
        settings.auth_secret_key.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(
    token: str,
    settings: Settings,
) -> dict:
    try:
        return jwt.decode(
            token,
            settings.auth_secret_key.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            options={
                "require": ["sub", "ver", "iat", "exp"],
            },
        )
    except InvalidTokenError as error:
        raise ValueError("Token đăng nhập không hợp lệ.") from error