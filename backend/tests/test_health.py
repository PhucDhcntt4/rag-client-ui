from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import AuthUser
from app.database import get_database_connection
from app.security.dependencies import get_current_user


class UnusedAdminConnection:
    def execute(self, *_args, **_kwargs):
        raise AssertionError("Admin không cần truy vấn quyền tài liệu")


@pytest.fixture
def authenticated_client() -> Iterator[TestClient]:
    def authenticated_user() -> AuthUser:
        return AuthUser(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            username="test-user",
            full_name="Test User",
            email=None,
            department=None,
            role="admin",
        )

    app.dependency_overrides[get_current_user] = authenticated_user
    app.dependency_overrides[get_database_connection] = (
        lambda: UnusedAdminConnection()
    )
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_database_connection, None)


def test_health():
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_business_api_requires_login():
    with TestClient(app) as client:
        response = client.get("/api/ai/providers")

    assert response.status_code == 401


def test_ai_provider_catalog_is_safe_for_frontend(authenticated_client):
    response = authenticated_client.get("/api/ai/providers")

    assert response.status_code == 200
    body = response.json()
    assert {item["id"] for item in body["providers"]} == {"gemini", "openai"}
    assert "api_key" not in response.text.lower()


def test_frontend_is_served_by_fastapi():
    with TestClient(app) as client:
        page = client.get("/")
        module = client.get("/js/app.js")
        api_module = client.get("/js/api.js")
        stylesheet = client.get("/assets/styles.css")
        marked = client.get("/assets/marked.js")

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert page.headers["cache-control"] == "no-store, max-age=0"
    assert module.headers["cache-control"] == "no-store, max-age=0"
    assert 'class="auth-pending"' in page.text
    assert 'id="brandLink"' in page.text
    assert 'id="scopeToggle"' in page.text
    assert 'aria-controls="scopeControls"' in page.text
    assert 'id="scrollDownButton"' in page.text
    assert 'id="documentsDrawer"' in page.text
    assert 'class="icon-button hidden"' in page.text
    assert 'id="aiProviderSelect"' in page.text
    assert 'id="accountMenu"' in page.text
    assert 'id="logoutButton"' in page.text
    assert 'id="adminButton"' in page.text
    assert 'id="adminDrawer"' in page.text
    assert 'class="admin-page hidden"' in page.text
    assert 'id="permissionGroupTableBody"' in page.text
    assert 'id="permissionGroupDialog"' in page.text
    assert 'id="permissionDialogScopeTree"' in page.text
    assert 'id="permissionUserList"' in page.text
    assert 'id="permissionDepartmentFilter"' in page.text
    assert 'id="permissionStatusFilter"' in page.text
    assert 'id="permissionUserDialog"' in page.text
    assert 'id="permissionUserGroupList"' in page.text
    assert 'id="permissionUserRole"' in page.text
    assert 'id="permissionUserActive"' in page.text
    assert 'id="permissionPasswordResetPanel"' in page.text
    assert 'id="confirmPermissionPasswordResetButton"' in page.text
    assert 'id="openCreatePermissionUserButton"' in page.text
    assert 'id="createPermissionUserDialog"' in page.text
    assert 'id="createPermissionUserForm"' in page.text
    assert 'id="permissionDialogUserList"' in page.text
    assert 'id="deletePermissionGroupButton"' in page.text
    assert 'class="permission-admin-sidebar"' in page.text
    assert 'id="backToPermissionGroupsButton"' in page.text
    assert 'id="showAdminUsersButton"' in page.text
    assert 'data-admin-panel="groups"' in page.text
    assert 'data-admin-panel="users"' in page.text
    assert 'id="documentsModeButton"' not in page.text
    assert 'id="productsModeButton"' not in page.text
    assert 'id="productImageButton"' in page.text
    assert 'id="productImageInput"' in page.text
    assert 'dataSource: "auto"' in module.text
    assert 'get("debug")' in module.text
    assert "visibleMessageContent" in module.text
    assert "restoreAuthentication" in module.text
    assert "conversationStoreKey" in module.text
    assert "toggleAccountMenu" in module.text
    assert "ensureAdminData" in module.text
    assert "setAdminPanel" in module.text
    assert "renderPermissionGroupTable" in module.text
    assert "renderPermissionDialogUsers" in module.text
    assert "renderPermissionUserGroupChoices" in module.text
    assert "submitPermissionUserDialog" in module.text
    assert "syncPermissionUserStatusControl" in module.text
    assert "submitPermissionPasswordReset" in module.text
    assert "updateAdminUser" in api_module.text
    assert "resetAdminUserPassword" in api_module.text
    assert "submitCreatePermissionUserDialog" in module.text
    assert "createAdminUser" in api_module.text
    assert "permission-row-delete-button" in module.text
    assert "deletePermissionGroupRecord" in module.text
    assert "deleteEditingPermissionGroup" in module.text
    assert "submitPermissionGroupDialog" in module.text
    assert 'app.currentUser?.role === "admin"' in module.text
    assert 'name === "documents" && !DEBUG_MODE' in module.text
    assert module.status_code == 200
    assert api_module.status_code == 200
    assert 'credentials: "include"' in api_module.text
    assert 'apiRequest("/api/auth/login"' in api_module.text
    assert "deletePermissionGroup" in api_module.text
    assert 'method: "DELETE"' in api_module.text
    assert stylesheet.status_code == 200
    assert marked.status_code == 200


def test_rag_asset_proxy_returns_image_without_exposing_key(
    authenticated_client,
):
    class FakeRagClient:
        async def get_asset(self, asset_id: int):
            assert asset_id == 8
            return b"\x89PNG\r\n\x1a\nimage-data", "image/png"

    authenticated_client.app.state.rag_client = FakeRagClient()
    response = authenticated_client.get("/api/rag-assets/8")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content.startswith(b"\x89PNG")
