from __future__ import annotations

from getpass import getpass
import sys
from typing import Literal
from uuid import UUID

import psycopg  # type: ignore

from app.config import get_settings
from app.security.passwords import hash_password, validate_password


UserRole = Literal["admin", "manager", "employee"]
ROLE_OPTIONS: tuple[tuple[str, UserRole, str], ...] = (
    ("1", "admin", "Quản trị viên - toàn quyền hệ thống"),
    ("2", "manager", "Quản lý - quyền tài liệu theo nhóm được gán"),
    ("3", "employee", "Nhân viên - quyền tài liệu theo nhóm được gán"),
)


def configure_console() -> None:
    """Tránh lỗi Unicode khi chạy script trên Windows."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def prompt_required(label: str) -> str:
    while True:
        value = input(f"{label}: ").strip()
        if value:
            return value
        print(f"{label} không được để trống.")


def prompt_optional(label: str) -> str | None:
    value = input(f"{label} (có thể bỏ trống): ").strip()
    return value or None


def prompt_new_password() -> str:
    while True:
        password = getpass("Mật khẩu: ")
        confirmation = getpass("Nhập lại mật khẩu: ")

        if password != confirmation:
            print("Hai mật khẩu không khớp. Vui lòng nhập lại.")
            continue

        try:
            validate_password(password)
        except ValueError as error:
            print(error)
            continue

        return password


def prompt_role() -> UserRole:
    print("Vai trò tài khoản:")
    for number, _role, description in ROLE_OPTIONS:
        print(f"  {number}. {description}")

    role_by_choice = {number: role for number, role, _ in ROLE_OPTIONS}
    role_names = {role for _, role, _ in ROLE_OPTIONS}
    while True:
        value = input("Chọn vai trò [1/2/3, mặc định 3]: ").strip().lower()
        if not value:
            return "employee"
        if value in role_by_choice:
            return role_by_choice[value]
        if value in role_names:
            return value  # type: ignore[return-value]
        print("Vai trò không hợp lệ. Hãy chọn 1, 2, 3 hoặc nhập tên role.")


def ensure_schema_exists(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('rag_client.users')")
        users_table = cursor.fetchone()

    if not users_table or users_table[0] is None:
        raise RuntimeError(
            "Chưa có bảng rag_client.users. Hãy chạy python init_db.py trước."
        )


def load_permission_groups(
    connection: psycopg.Connection,
) -> list[tuple[UUID, str, str]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, code, name
            FROM rag_client.permission_groups
            WHERE is_active = TRUE
            ORDER BY name, code
            """
        )
        return list(cursor.fetchall())


def prompt_permission_group(
    groups: list[tuple[UUID, str, str]],
    role: UserRole,
) -> UUID | None:
    if role == "admin":
        print("Admin có toàn quyền tài liệu nên không cần gán nhóm quyền.")
        return None

    if not groups:
        print("Chưa có nhóm quyền hoạt động. Tài khoản sẽ chưa được xem tài liệu.")
        return None

    print("Nhóm quyền tài liệu:")
    print("  0. Chưa gán nhóm (không được xem tài liệu)")
    for index, (_group_id, code, name) in enumerate(groups, start=1):
        print(f"  {index}. {name} [{code}]")

    while True:
        value = input("Chọn nhóm quyền [0]: ").strip() or "0"
        if value == "0":
            return None
        try:
            index = int(value)
        except ValueError:
            print("Lựa chọn không hợp lệ. Hãy nhập số trong danh sách.")
            continue
        if 1 <= index <= len(groups):
            return groups[index - 1][0]
        print("Lựa chọn không hợp lệ. Hãy nhập số trong danh sách.")


def create_user(
    connection: psycopg.Connection,
    *,
    username: str,
    password: str,
    full_name: str,
    email: str | None,
    department: str | None,
    role: UserRole,
    permission_group_id: UUID | None,
) -> UUID:
    password_digest = hash_password(password)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM rag_client.users
            WHERE lower(username) = lower(%s)
            """,
            (username,),
        )
        if cursor.fetchone() is not None:
            raise ValueError(f"Tên đăng nhập {username!r} đã tồn tại.")

        if email:
            cursor.execute(
                """
                SELECT id
                FROM rag_client.users
                WHERE lower(email) = lower(%s)
                """,
                (email,),
            )
            if cursor.fetchone() is not None:
                raise ValueError(f"Email {email!r} đã được sử dụng.")

        if permission_group_id is not None:
            cursor.execute(
                """
                SELECT id
                FROM rag_client.permission_groups
                WHERE id = %s AND is_active = TRUE
                """,
                (permission_group_id,),
            )
            if cursor.fetchone() is None:
                raise ValueError("Nhóm quyền không tồn tại hoặc đã bị khóa.")

        cursor.execute(
            """
            INSERT INTO rag_client.users (
                username,
                password_hash,
                full_name,
                email,
                department,
                role,
                permission_group_id,
                account_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'active')
            RETURNING id
            """,
            (
                username,
                password_digest,
                full_name,
                email,
                department,
                role,
                permission_group_id,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Không nhận được ID của tài khoản vừa tạo.")
        return row[0]


def create_admin(
    connection: psycopg.Connection,
    *,
    username: str,
    password: str,
    full_name: str,
    email: str | None,
    department: str | None,
) -> UUID:
    """Giữ tương thích cho code cũ cần tạo riêng tài khoản admin."""
    return create_user(
        connection,
        username=username,
        password=password,
        full_name=full_name,
        email=email,
        department=department,
        role="admin",
        permission_group_id=None,
    )


def main() -> None:
    configure_console()
    print("Tạo tài khoản người dùng Ms.Hài")
    print("Mật khẩu được hash bằng Argon2 và không hiển thị.")
    print()

    try:
        username = prompt_required("Tên đăng nhập")
        full_name = prompt_required("Họ và tên")
        email = prompt_optional("Email")
        department = prompt_optional("Phòng ban")
        role = prompt_role()
        password = prompt_new_password()

        settings = get_settings()
        database_url = settings.database_url.get_secret_value()

        with psycopg.connect(database_url) as connection:
            ensure_schema_exists(connection)
            groups = load_permission_groups(connection)
            permission_group_id = prompt_permission_group(groups, role)
            user_id = create_user(
                connection,
                username=username,
                password=password,
                full_name=full_name,
                email=email,
                department=department,
                role=role,
                permission_group_id=permission_group_id,
            )

        selected_group = next(
            (
                f"{name} [{code}]"
                for group_id, code, name in groups
                if group_id == permission_group_id
            ),
            "Không gán nhóm",
        )
        if role == "admin":
            selected_group = "Toàn bộ tài liệu theo vai trò admin"

        print()
        print("Tạo tài khoản thành công.")
        print(f"ID: {user_id}")
        print(f"Tên đăng nhập: {username}")
        print(f"Vai trò: {role}")
        print(f"Nhóm quyền: {selected_group}")

    except (KeyboardInterrupt, EOFError):
        print("\nĐã hủy tạo tài khoản.", file=sys.stderr)
        raise SystemExit(1)
    except (ValueError, RuntimeError) as error:
        print(f"Tạo tài khoản thất bại: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except psycopg.errors.UniqueViolation as error:
        print(
            "Tạo tài khoản thất bại: username hoặc email đã tồn tại.",
            file=sys.stderr,
        )
        raise SystemExit(1) from error
    except psycopg.Error as error:
        print(f"Lỗi PostgreSQL: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
