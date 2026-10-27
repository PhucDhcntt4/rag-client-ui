from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.errors import UniqueViolation

from app.schemas import (
    AdminMutationResponse,
    AdminUserCreate,
    AdminUserInfo,
    AdminUserPasswordReset,
    AdminUserUpdate,
    AdminUsersResponse,
    PermissionGroupCreate,
    PermissionGroupInfo,
    PermissionGroupsResponse,
    PermissionGroupUpdate,
    PermissionScope,
    PermissionScopesUpdate,
    UserPermissionGroupUpdate,
)
from app.security.dependencies import AdminUser, DatabaseConnection, require_admin
from app.security.passwords import hash_password


router = APIRouter(
    prefix="/api/admin",
    tags=["Administration"],
    dependencies=[Depends(require_admin)],
)


def normalize_scopes(scopes: list[PermissionScope]) -> list[PermissionScope]:
    """Giữ payload idempotent khi UI gửi lặp hoặc gửi cả quyền all."""
    if any(scope.scope_type == "all" for scope in scopes):
        return [PermissionScope(scope_type="all")]

    unique: dict[tuple[str, int | None, int | None], PermissionScope] = {}
    for scope in scopes:
        key = (scope.scope_type, scope.doc_type_id, scope.doc_group_id)
        unique[key] = scope
    return list(unique.values())


def load_groups(connection) -> PermissionGroupsResponse:
    group_rows = connection.execute(
        """
        SELECT
            groups.id,
            groups.code,
            groups.name,
            groups.description,
            groups.is_active,
            COUNT(users.id)::integer AS user_count
        FROM rag_client.permission_groups AS groups
        LEFT JOIN rag_client.users AS users
            ON users.permission_group_id = groups.id
        GROUP BY groups.id
        ORDER BY groups.name, groups.code
        """
    ).fetchall()
    scope_rows = connection.execute(
        """
        SELECT permission_group_id, scope_type, doc_type_id, doc_group_id
        FROM rag_client.permission_group_scopes
        ORDER BY scope_type, doc_type_id, doc_group_id
        """
    ).fetchall()
    scopes_by_group: dict[UUID, list[PermissionScope]] = {}
    for row in scope_rows:
        scopes_by_group.setdefault(row["permission_group_id"], []).append(
            PermissionScope(
                scope_type=row["scope_type"],
                doc_type_id=row["doc_type_id"],
                doc_group_id=row["doc_group_id"],
            )
        )
    return PermissionGroupsResponse(
        groups=[
            PermissionGroupInfo(
                **row,
                scopes=scopes_by_group.get(row["id"], []),
            )
            for row in group_rows
        ]
    )


@router.get("/permission-groups", response_model=PermissionGroupsResponse)
def list_permission_groups(
    _admin: AdminUser,
    connection: DatabaseConnection,
):
    return load_groups(connection)


@router.post(
    "/permission-groups",
    response_model=PermissionGroupInfo,
    status_code=status.HTTP_201_CREATED,
)
def create_permission_group(
    payload: PermissionGroupCreate,
    _admin: AdminUser,
    connection: DatabaseConnection,
):
    try:
        row = connection.execute(
            """
            INSERT INTO rag_client.permission_groups (
                code, name, description, is_active
            )
            VALUES (%s, %s, %s, TRUE)
            RETURNING id, code, name, description, is_active
            """,
            (payload.code.upper(), payload.name, payload.description),
        ).fetchone()
    except UniqueViolation as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Mã nhóm quyền đã tồn tại.",
        ) from error
    return PermissionGroupInfo(**row, user_count=0, scopes=[])


@router.put(
    "/permission-groups/{group_id}",
    response_model=AdminMutationResponse,
)
def update_permission_group(
    group_id: UUID,
    payload: PermissionGroupUpdate,
    _admin: AdminUser,
    connection: DatabaseConnection,
):
    row = connection.execute(
        """
        UPDATE rag_client.permission_groups
        SET name = %s,
            description = %s,
            is_active = %s,
            updated_at = NOW()
        WHERE id = %s
        RETURNING id
        """,
        (payload.name, payload.description, payload.is_active, group_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhóm quyền.")
    return AdminMutationResponse(message="Đã cập nhật nhóm quyền.")


@router.delete(
    "/permission-groups/{group_id}",
    response_model=AdminMutationResponse,
)
def delete_permission_group(
    group_id: UUID,
    _admin: AdminUser,
    connection: DatabaseConnection,
):
    """Xóa nhóm trống; không tự ý làm người dùng mất quyền."""
    with connection.transaction():
        group = connection.execute(
            """
            SELECT id, code, name
            FROM rag_client.permission_groups
            WHERE id = %s
            FOR UPDATE
            """,
            (group_id,),
        ).fetchone()
        if group is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy nhóm quyền.",
            )

        if group["code"].upper() == "ALL_DOCUMENTS":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Không thể xóa nhóm quyền hệ thống ALL_DOCUMENTS.",
            )

        user_count_row = connection.execute(
            """
            SELECT COUNT(*)::integer AS user_count
            FROM rag_client.users
            WHERE permission_group_id = %s
            """,
            (group_id,),
        ).fetchone()
        user_count = user_count_row["user_count"]
        if user_count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Nhóm đang có {user_count} người dùng. "
                    "Hãy chuyển người dùng sang nhóm khác trước khi xóa."
                ),
            )

        connection.execute(
            "DELETE FROM rag_client.permission_groups WHERE id = %s",
            (group_id,),
        )

    return AdminMutationResponse(
        message=f"Đã xóa nhóm quyền {group['name']}.",
    )


def validate_scope_ids(connection, scopes: list[PermissionScope]) -> None:
    doc_type_ids = {
        scope.doc_type_id
        for scope in scopes
        if scope.doc_type_id is not None
    }
    group_ids = {
        scope.doc_group_id
        for scope in scopes
        if scope.doc_group_id is not None
    }
    if doc_type_ids:
        found = connection.execute(
            "SELECT id FROM rag_metadata.doc_types WHERE id = ANY(%s)",
            (list(doc_type_ids),),
        ).fetchall()
        if {row["id"] for row in found} != doc_type_ids:
            raise HTTPException(status_code=422, detail="Có loại tài liệu không tồn tại.")
    if group_ids:
        found = connection.execute(
            "SELECT id FROM rag_metadata.document_groups WHERE id = ANY(%s)",
            (list(group_ids),),
        ).fetchall()
        if {row["id"] for row in found} != group_ids:
            raise HTTPException(status_code=422, detail="Có nhóm tài liệu không tồn tại.")


@router.put(
    "/permission-groups/{group_id}/scopes",
    response_model=AdminMutationResponse,
)
def replace_permission_scopes(
    group_id: UUID,
    payload: PermissionScopesUpdate,
    _admin: AdminUser,
    connection: DatabaseConnection,
):
    scopes = normalize_scopes(payload.scopes)

    group = connection.execute(
        "SELECT id FROM rag_client.permission_groups WHERE id = %s",
        (group_id,),
    ).fetchone()
    if group is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhóm quyền.")
    validate_scope_ids(connection, scopes)

    with connection.transaction():
        connection.execute(
            "DELETE FROM rag_client.permission_group_scopes WHERE permission_group_id = %s",
            (group_id,),
        )
        for scope in scopes:
            connection.execute(
                """
                INSERT INTO rag_client.permission_group_scopes (
                    permission_group_id,
                    scope_type,
                    doc_type_id,
                    doc_group_id
                )
                VALUES (%s, %s, %s, %s)
                """,
                (
                    group_id,
                    scope.scope_type,
                    scope.doc_type_id,
                    scope.doc_group_id,
                ),
            )
    return AdminMutationResponse(message="Đã lưu phạm vi tài liệu.")


@router.get("/users", response_model=AdminUsersResponse)
def list_users(
    _admin: AdminUser,
    connection: DatabaseConnection,
):
    rows = connection.execute(
        """
        SELECT
            users.id,
            users.username,
            users.full_name,
            users.email,
            users.department,
            users.role,
            users.account_status,
            users.permission_group_id,
            users.last_login_at,
            groups.name AS permission_group_name
        FROM rag_client.users AS users
        LEFT JOIN rag_client.permission_groups AS groups
            ON groups.id = users.permission_group_id
        ORDER BY users.full_name, users.username
        """
    ).fetchall()
    return AdminUsersResponse(users=[AdminUserInfo(**row) for row in rows])


@router.post(
    "/users",
    response_model=AdminUserInfo,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    payload: AdminUserCreate,
    _admin: AdminUser,
    connection: DatabaseConnection,
):
    """Tạo tài khoản nhân viên và gán tối đa một nhóm quyền."""
    permission_group_id = (
        None if payload.role == "admin" else payload.permission_group_id
    )
    permission_group_name = None
    if permission_group_id is not None:
        group = connection.execute(
            """
            SELECT id, name
            FROM rag_client.permission_groups
            WHERE id = %s AND is_active = TRUE
            """,
            (permission_group_id,),
        ).fetchone()
        if group is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Nhóm quyền không tồn tại hoặc đã bị khóa.",
            )
        permission_group_name = group["name"]

    email = payload.email or None
    department = payload.department or None
    try:
        row = connection.execute(
            """
            INSERT INTO rag_client.users (
                username,
                password_hash,
                full_name,
                email,
                department,
                role,
                account_status,
                permission_group_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING
                id,
                username,
                full_name,
                email,
                department,
                role,
                account_status,
                permission_group_id
            """,
            (
                payload.username,
                hash_password(payload.password),
                payload.full_name,
                email,
                department,
                payload.role,
                payload.account_status,
                permission_group_id,
            ),
        ).fetchone()
    except UniqueViolation as error:
        constraint_name = getattr(error.diag, "constraint_name", "") or ""
        if "email" in constraint_name:
            detail = "Email đã được sử dụng."
        elif "username" in constraint_name:
            detail = "Tên đăng nhập đã tồn tại."
        else:
            detail = "Tên đăng nhập hoặc email đã tồn tại."
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        ) from error

    return AdminUserInfo(
        **row,
        permission_group_name=permission_group_name,
    )


@router.put("/users/{user_id}", response_model=AdminUserInfo)
def update_user(
    user_id: UUID,
    payload: AdminUserUpdate,
    admin: AdminUser,
    connection: DatabaseConnection,
):
    current = connection.execute(
        """
        SELECT id, role, account_status
        FROM rag_client.users
        WHERE id = %s
        """,
        (user_id,),
    ).fetchone()
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy người dùng.",
        )

    if user_id == admin.id and (
        payload.role != "admin" or payload.account_status != "active"
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Admin đang đăng nhập không thể tự hạ quyền hoặc tự vô hiệu hóa.",
        )

    permission_group_id = (
        None if payload.role == "admin" else payload.permission_group_id
    )
    permission_group_name = None
    if permission_group_id is not None:
        group = connection.execute(
            """
            SELECT id, name
            FROM rag_client.permission_groups
            WHERE id = %s AND is_active = TRUE
            """,
            (permission_group_id,),
        ).fetchone()
        if group is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Nhóm quyền không tồn tại hoặc đã bị khóa.",
            )
        permission_group_name = group["name"]

    try:
        row = connection.execute(
            """
            UPDATE rag_client.users
            SET session_version = session_version + CASE
                    WHEN role <> %s OR account_status <> %s THEN 1
                    ELSE 0
                END,
                failed_login_attempts = 0,
                locked_until = NULL,
                username = %s,
                full_name = %s,
                email = %s,
                department = %s,
                role = %s,
                account_status = %s,
                permission_group_id = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING
                id,
                username,
                full_name,
                email,
                department,
                role,
                account_status,
                permission_group_id
            """,
            (
                payload.role,
                payload.account_status,
                payload.username,
                payload.full_name,
                payload.email or None,
                payload.department or None,
                payload.role,
                payload.account_status,
                permission_group_id,
                user_id,
            ),
        ).fetchone()
    except UniqueViolation as error:
        constraint_name = getattr(error.diag, "constraint_name", "") or ""
        if "email" in constraint_name:
            detail = "Email đã được sử dụng."
        elif "username" in constraint_name:
            detail = "Tên đăng nhập đã tồn tại."
        else:
            detail = "Tên đăng nhập hoặc email đã tồn tại."
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        ) from error

    return AdminUserInfo(
        **row,
        permission_group_name=permission_group_name,
    )


@router.put(
    "/users/{user_id}/password",
    response_model=AdminMutationResponse,
)
def reset_user_password(
    user_id: UUID,
    payload: AdminUserPasswordReset,
    _admin: AdminUser,
    connection: DatabaseConnection,
):
    row = connection.execute(
        """
        UPDATE rag_client.users
        SET password_hash = %s,
            session_version = session_version + 1,
            failed_login_attempts = 0,
            locked_until = NULL,
            updated_at = NOW()
        WHERE id = %s
        RETURNING id
        """,
        (hash_password(payload.new_password), user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy người dùng.",
        )
    return AdminMutationResponse(
        message="Đã đặt lại mật khẩu và thu hồi các phiên đăng nhập cũ.",
    )


@router.put(
    "/users/{user_id}/permission-group",
    response_model=AdminMutationResponse,
)
def assign_user_permission_group(
    user_id: UUID,
    payload: UserPermissionGroupUpdate,
    _admin: AdminUser,
    connection: DatabaseConnection,
):
    if payload.permission_group_id is not None:
        group = connection.execute(
            """
            SELECT id
            FROM rag_client.permission_groups
            WHERE id = %s AND is_active = TRUE
            """,
            (payload.permission_group_id,),
        ).fetchone()
        if group is None:
            raise HTTPException(
                status_code=422,
                detail="Nhóm quyền không tồn tại hoặc đã bị khóa.",
            )

    row = connection.execute(
        """
        UPDATE rag_client.users
        SET permission_group_id = %s,
            updated_at = NOW()
        WHERE id = %s
        RETURNING id
        """,
        (payload.permission_group_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng.")
    return AdminMutationResponse(message="Đã cập nhật nhóm quyền của người dùng.")

