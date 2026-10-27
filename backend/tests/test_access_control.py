from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_database_connection
from app.routers.admin import normalize_scopes, router as admin_router
from app.schemas import PermissionScope
from app.schemas import AuthUser
from app.security.dependencies import get_current_user
from app.security.passwords import verify_password
from app.services.access_control import DocumentAccess, load_document_access


USER_ID = UUID("00000000-0000-0000-0000-000000000100")
GROUP_ID = UUID("00000000-0000-0000-0000-000000000200")
CREATED_USER_ID = UUID("00000000-0000-0000-0000-000000000300")


class Result:
    def __init__(self, rows=None):
        self.rows = rows or []

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class Transaction:
    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False


class DeleteGroupConnection:
    def __init__(self, *, group=None, user_count=0):
        self.group = group
        self.user_count = user_count
        self.deleted_group_id = None

    def transaction(self):
        return Transaction()

    def execute(self, statement, params=()):
        normalized = " ".join(statement.split()).lower()
        if "select id, code, name" in normalized:
            return Result([self.group] if self.group else [])
        if "select count(*)::integer as user_count" in normalized:
            return Result([{"user_count": self.user_count}])
        if "delete from rag_client.permission_groups" in normalized:
            self.deleted_group_id = params[0]
            return Result()
        raise AssertionError(normalized)


class AdminConnection:
    def execute(self, statement, _params=()):
        normalized = " ".join(statement.split()).lower()
        if "from rag_client.permission_group_scopes" in normalized:
            return Result([])
        if "from rag_client.permission_groups" in normalized:
            return Result(
                [
                    {
                        "id": GROUP_ID,
                        "code": "STORE",
                        "name": "Nhân viên cửa hàng",
                        "description": None,
                        "is_active": True,
                        "user_count": 1,
                    }
                ]
            )
        raise AssertionError(normalized)


class CreateUserConnection:
    def __init__(self, *, group_exists=True):
        self.group_exists = group_exists
        self.insert_params = None

    def execute(self, statement, params=()):
        normalized = " ".join(statement.split()).lower()
        if "select id, name" in normalized and "permission_groups" in normalized:
            if not self.group_exists:
                return Result([])
            return Result([{"id": GROUP_ID, "name": "Nhân viên cửa hàng"}])
        if "insert into rag_client.users" in normalized:
            self.insert_params = params
            return Result(
                [
                    {
                        "id": CREATED_USER_ID,
                        "username": params[0],
                        "full_name": params[2],
                        "email": params[3],
                        "department": params[4],
                        "role": params[5],
                        "account_status": params[6],
                        "permission_group_id": params[7],
                    }
                ]
            )
        raise AssertionError(normalized)


class UpdateUserConnection:
    def __init__(self, *, current_user_id=CREATED_USER_ID):
        self.current_user_id = current_user_id
        self.update_params = None
        self.update_statement = ""

    def execute(self, statement, params=()):
        normalized = " ".join(statement.split()).lower()
        if "select id, role, account_status" in normalized:
            return Result(
                [
                    {
                        "id": self.current_user_id,
                        "role": "employee",
                        "account_status": "active",
                    }
                ]
            )
        if "select id, name" in normalized and "permission_groups" in normalized:
            return Result([{"id": GROUP_ID, "name": "Nhân viên cửa hàng"}])
        if "update rag_client.users" in normalized:
            self.update_statement = normalized
            self.update_params = params
            return Result(
                [
                    {
                        "id": self.current_user_id,
                        "username": params[2],
                        "full_name": params[3],
                        "email": params[4],
                        "department": params[5],
                        "role": params[6],
                        "account_status": params[7],
                        "permission_group_id": params[8],
                    }
                ]
            )
        raise AssertionError(normalized)


class ResetPasswordConnection:
    def __init__(self, *, user_exists=True):
        self.user_exists = user_exists
        self.update_params = None
        self.update_statement = ""

    def execute(self, statement, params=()):
        normalized = " ".join(statement.split()).lower()
        if "set password_hash" not in normalized:
            raise AssertionError(normalized)
        self.update_statement = normalized
        self.update_params = params
        return Result([{"id": params[1]}] if self.user_exists else [])


def auth_user(role: str) -> AuthUser:
    return AuthUser(
        id=USER_ID,
        username="tester",
        full_name="Test User",
        email=None,
        department=None,
        role=role,
        permission_group_id=GROUP_ID,
    )


def admin_client(role: str) -> TestClient:
    application = FastAPI()
    application.include_router(admin_router)
    application.dependency_overrides[get_current_user] = lambda: auth_user(role)
    application.dependency_overrides[get_database_connection] = AdminConnection
    return TestClient(application)


def delete_group_client(connection: DeleteGroupConnection) -> TestClient:
    application = FastAPI()
    application.include_router(admin_router)
    application.dependency_overrides[get_current_user] = lambda: auth_user("admin")
    application.dependency_overrides[get_database_connection] = lambda: connection
    return TestClient(application)


def create_user_client(connection: CreateUserConnection) -> TestClient:
    application = FastAPI()
    application.include_router(admin_router)
    application.dependency_overrides[get_current_user] = lambda: auth_user("admin")
    application.dependency_overrides[get_database_connection] = lambda: connection
    return TestClient(application)


def update_user_client(connection: UpdateUserConnection) -> TestClient:
    application = FastAPI()
    application.include_router(admin_router)
    application.dependency_overrides[get_current_user] = lambda: auth_user("admin")
    application.dependency_overrides[get_database_connection] = lambda: connection
    return TestClient(application)


def reset_password_client(connection: ResetPasswordConnection) -> TestClient:
    application = FastAPI()
    application.include_router(admin_router)
    application.dependency_overrides[get_current_user] = lambda: auth_user("admin")
    application.dependency_overrides[get_database_connection] = lambda: connection
    return TestClient(application)


def test_admin_api_rejects_regular_user():
    with admin_client("employee") as client:
        response = client.get("/api/admin/permission-groups")

    assert response.status_code == 403


def test_admin_can_list_permission_groups():
    with admin_client("admin") as client:
        response = client.get("/api/admin/permission-groups")

    assert response.status_code == 200
    assert response.json()["groups"][0]["code"] == "STORE"


def test_admin_user_list_exposes_last_login_time():
    last_login = datetime(2026, 10, 22, 3, 15, tzinfo=timezone.utc)

    def execute(statement, _params=()):
        normalized = " ".join(statement.split()).lower()
        assert "users.last_login_at" in normalized
        return Result(
            [
                {
                    "id": CREATED_USER_ID,
                    "username": "employee",
                    "full_name": "Nhân viên",
                    "email": None,
                    "department": "Cửa hàng",
                    "role": "employee",
                    "account_status": "active",
                    "permission_group_id": GROUP_ID,
                    "permission_group_name": "Nhân viên cửa hàng",
                    "last_login_at": last_login,
                }
            ]
        )

    application = FastAPI()
    application.include_router(admin_router)
    application.dependency_overrides[get_current_user] = lambda: auth_user("admin")
    application.dependency_overrides[get_database_connection] = lambda: SimpleNamespace(
        execute=execute
    )

    with TestClient(application) as client:
        response = client.get("/api/admin/users")

    assert response.status_code == 200
    assert response.json()["users"][0]["last_login_at"] == "2026-10-22T03:15:00Z"


def test_document_access_loads_only_assigned_group_scopes():
    rows = [
        {
            "is_active": True,
            "scope_type": "doc_type",
            "doc_type_id": 2,
            "doc_group_id": None,
            "group_doc_type_id": None,
        },
        {
            "is_active": True,
            "scope_type": "doc_group",
            "doc_type_id": None,
            "doc_group_id": 9,
            "group_doc_type_id": 3,
        },
    ]
    connection = SimpleNamespace(
        execute=lambda *_args, **_kwargs: Result(rows)
    )

    access = load_document_access(auth_user("employee"), connection)

    assert access == DocumentAccess(
        doc_type_ids=frozenset({2}),
        group_ids=frozenset({9}),
        group_doc_type_pairs=frozenset({(9, 3)}),
    )
    assert access.allows(2, None)
    assert access.allows(3, 9)
    assert not access.allows(3, 10)


def test_permission_scopes_are_idempotently_normalized():
    scopes = normalize_scopes(
        [
            PermissionScope(scope_type="doc_group", doc_group_id=11),
            PermissionScope(scope_type="doc_group", doc_group_id=11),
        ]
    )
    assert scopes == [PermissionScope(scope_type="doc_group", doc_group_id=11)]

    all_scopes = normalize_scopes(
        [
            PermissionScope(scope_type="doc_group", doc_group_id=11),
            PermissionScope(scope_type="all"),
        ]
    )
    assert all_scopes == [PermissionScope(scope_type="all")]


def test_admin_can_delete_empty_permission_group():
    connection = DeleteGroupConnection(
        group={"id": GROUP_ID, "code": "STORE", "name": "Nhân viên cửa hàng"},
    )
    with delete_group_client(connection) as client:
        response = client.delete(f"/api/admin/permission-groups/{GROUP_ID}")

    assert response.status_code == 200
    assert connection.deleted_group_id == GROUP_ID
    assert response.json()["message"] == "Đã xóa nhóm quyền Nhân viên cửa hàng."


def test_delete_permission_group_rejects_group_with_users():
    connection = DeleteGroupConnection(
        group={"id": GROUP_ID, "code": "STORE", "name": "Nhân viên cửa hàng"},
        user_count=2,
    )
    with delete_group_client(connection) as client:
        response = client.delete(f"/api/admin/permission-groups/{GROUP_ID}")

    assert response.status_code == 409
    assert connection.deleted_group_id is None
    assert "2 người dùng" in response.json()["detail"]


def test_delete_permission_group_protects_system_group():
    connection = DeleteGroupConnection(
        group={"id": GROUP_ID, "code": "ALL_DOCUMENTS", "name": "Xem toàn bộ"},
    )
    with delete_group_client(connection) as client:
        response = client.delete(f"/api/admin/permission-groups/{GROUP_ID}")

    assert response.status_code == 409
    assert connection.deleted_group_id is None


def test_delete_permission_group_returns_not_found():
    connection = DeleteGroupConnection(group=None)
    with delete_group_client(connection) as client:
        response = client.delete(f"/api/admin/permission-groups/{GROUP_ID}")

    assert response.status_code == 404
    assert connection.deleted_group_id is None


def test_admin_can_create_user_with_hashed_password_and_group():
    connection = CreateUserConnection()
    payload = {
        "username": "nguyenvana",
        "password": "secure-password",
        "full_name": "Nguyễn Văn A",
        "email": "nguyenvana@example.com",
        "department": "Kinh doanh",
        "role": "employee",
        "account_status": "active",
        "permission_group_id": str(GROUP_ID),
    }

    with create_user_client(connection) as client:
        response = client.post("/api/admin/users", json=payload)

    assert response.status_code == 201
    assert response.json()["id"] == str(CREATED_USER_ID)
    assert response.json()["permission_group_name"] == "Nhân viên cửa hàng"
    assert "password" not in response.json()
    assert connection.insert_params[1] != payload["password"]
    assert verify_password(payload["password"], connection.insert_params[1])


def test_create_user_rejects_inactive_or_missing_group():
    connection = CreateUserConnection(group_exists=False)
    with create_user_client(connection) as client:
        response = client.post(
            "/api/admin/users",
            json={
                "username": "new-user",
                "password": "1234",
                "full_name": "New User",
                "permission_group_id": str(GROUP_ID),
            },
        )

    assert response.status_code == 422
    assert connection.insert_params is None


def test_create_user_validates_password_and_username():
    connection = CreateUserConnection()
    with create_user_client(connection) as client:
        response = client.post(
            "/api/admin/users",
            json={
                "username": "invalid username",
                "password": "123",
                "full_name": "New User",
            },
        )

    assert response.status_code == 422
    assert connection.insert_params is None


def test_admin_can_create_another_admin_account():
    connection = CreateUserConnection()
    with create_user_client(connection) as client:
        response = client.post(
            "/api/admin/users",
            json={
                "username": "second-admin",
                "password": "secure-password",
                "full_name": "Quản trị viên 2",
                "role": "admin",
                "account_status": "active",
            },
        )

    assert response.status_code == 201
    assert response.json()["role"] == "admin"
    assert response.json()["permission_group_id"] is None
    assert connection.insert_params[5] == "admin"


def test_admin_can_edit_user_and_disable_account():
    connection = UpdateUserConnection()
    payload = {
        "username": "updated-user",
        "full_name": "Người dùng đã sửa",
        "email": "updated@example.com",
        "department": "Kinh doanh",
        "role": "manager",
        "account_status": "disabled",
        "permission_group_id": str(GROUP_ID),
    }

    with update_user_client(connection) as client:
        response = client.put(
            f"/api/admin/users/{CREATED_USER_ID}",
            json=payload,
        )

    assert response.status_code == 200
    assert response.json()["full_name"] == payload["full_name"]
    assert response.json()["account_status"] == "disabled"
    assert response.json()["permission_group_name"] == "Nhân viên cửa hàng"
    assert connection.update_params[6] == "manager"
    assert connection.update_params[7] == "disabled"
    assert "session_version = session_version + case" in connection.update_statement
    assert "failed_login_attempts = 0" in connection.update_statement
    assert "locked_until = null" in connection.update_statement


def test_admin_cannot_disable_own_account():
    connection = UpdateUserConnection(current_user_id=USER_ID)
    with update_user_client(connection) as client:
        response = client.put(
            f"/api/admin/users/{USER_ID}",
            json={
                "username": "tester",
                "full_name": "Test User",
                "role": "admin",
                "account_status": "disabled",
            },
        )

    assert response.status_code == 409
    assert connection.update_params is None


def test_admin_can_reset_password_and_revoke_old_sessions():
    connection = ResetPasswordConnection()
    new_password = "new-secure-password"
    with reset_password_client(connection) as client:
        response = client.put(
            f"/api/admin/users/{CREATED_USER_ID}/password",
            json={"new_password": new_password},
        )

    assert response.status_code == 200
    assert verify_password(new_password, connection.update_params[0])
    assert connection.update_params[1] == CREATED_USER_ID
    assert "session_version = session_version + 1" in connection.update_statement
    assert "failed_login_attempts = 0" in connection.update_statement
    assert "locked_until = null" in connection.update_statement


def test_reset_password_validates_length_and_missing_user():
    connection = ResetPasswordConnection()
    with reset_password_client(connection) as client:
        invalid = client.put(
            f"/api/admin/users/{CREATED_USER_ID}/password",
            json={"new_password": "123"},
        )
    assert invalid.status_code == 422
    assert connection.update_params is None

    missing_connection = ResetPasswordConnection(user_exists=False)
    with reset_password_client(missing_connection) as client:
        missing = client.put(
            f"/api/admin/users/{CREATED_USER_ID}/password",
            json={"new_password": "1234"},
        )
    assert missing.status_code == 404
