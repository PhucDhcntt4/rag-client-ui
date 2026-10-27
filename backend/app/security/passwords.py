from __future__ import annotations

from pwdlib import PasswordHash  # type: ignore


MIN_PASSWORD_LENGTH = 4
_password_hash = PasswordHash.recommended()


def validate_password(password: str) -> None:
    """Từ chối mật khẩu yếu trước khi hash."""

    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự."
        )


def hash_password(password: str) -> str:
    validate_password(password)
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)
