from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import get_settings
from app.database import get_database_connection
from app.routers.auth import router as auth_router
from app.security.passwords import hash_password


USER_ID = UUID("00000000-0000-0000-0000-000000000123")


class FakeResult:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self):
        self.user = {
            "id": USER_ID,
            "username": "admin",
            "password_hash": hash_password("test-password"),
            "full_name": "Quản trị viên",
            "email": "admin@example.com",
            "department": "IT",
            "role": "admin",
            "account_status": "active",
            "session_version": 0,
            "failed_login_attempts": 0,
            "locked_until": None,
        }

    def execute(self, statement, params=()):
        normalized = " ".join(statement.split()).lower()
        if normalized.startswith("select"):
            lookup = str(params[0]).lower()
            matches = lookup in {
                str(self.user["id"]).lower(),
                self.user["username"].lower(),
                self.user["email"].lower(),
            }
            return FakeResult(self.user if matches else None)

        if "session_version = session_version + 1" in normalized:
            self.user["session_version"] += 1
        elif "failed_login_attempts = %s" in normalized:
            self.user["failed_login_attempts"] = params[0]
            self.user["account_status"] = params[1]
            self.user["locked_until"] = params[2]
        elif "failed_login_attempts = 0" in normalized:
            self.user["failed_login_attempts"] = 0
            self.user["locked_until"] = None
            self.user["account_status"] = "active"
        return FakeResult()


def create_auth_client(connection: FakeConnection) -> TestClient:
    application = FastAPI()
    application.include_router(auth_router)
    settings = SimpleNamespace(
        auth_secret_key=SecretStr("test-secret-key-with-enough-entropy"),
        auth_cookie_name="mshai_session",
        auth_token_expire_minutes=60,
        auth_cookie_secure=False,
    )
    application.dependency_overrides[get_database_connection] = (
        lambda: connection
    )
    application.dependency_overrides[get_settings] = lambda: settings
    return TestClient(application)


def test_login_restore_session_and_logout():
    connection = FakeConnection()
    with create_auth_client(connection) as client:
        login_response = client.post(
            "/api/auth/login",
            json={
                "username": "admin@example.com",
                "password": "test-password",
            },
        )
        me_response = client.get("/api/auth/me")
        logout_response = client.post("/api/auth/logout")
        expired_response = client.get("/api/auth/me")

    assert login_response.status_code == 200
    assert login_response.json()["user"]["username"] == "admin"
    assert "httponly" in login_response.headers["set-cookie"].lower()
    assert "samesite=strict" in login_response.headers["set-cookie"].lower()
    assert me_response.status_code == 200
    assert me_response.json()["user"]["id"] == str(USER_ID)
    assert logout_response.status_code == 200
    assert connection.user["session_version"] == 1
    assert expired_response.status_code == 401


def test_wrong_password_is_rejected_and_counted():
    connection = FakeConnection()
    with create_auth_client(connection) as client:
        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )

    assert response.status_code == 401
    assert connection.user["failed_login_attempts"] == 1
