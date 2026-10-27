from __future__ import annotations

import sys

import psycopg  # type: ignore
from psycopg import sql  # type: ignore

from app.config import get_settings


SUPPORTED_ID_TYPES = {
    "smallint": sql.SQL("SMALLINT"),
    "integer": sql.SQL("INTEGER"),
    "bigint": sql.SQL("BIGINT"),
    "uuid": sql.SQL("UUID"),
}


def get_metadata_id_types(
    connection: psycopg.Connection,
    metadata_schema: str,
) -> tuple[sql.SQL, sql.SQL]:
    """Đọc kiểu ID thật từ hai bảng của RAG Metadata."""

    query = """
        SELECT table_name, data_type
        FROM information_schema.columns
        WHERE table_schema = %s
          AND column_name = 'id'
          AND table_name IN ('doc_types', 'document_groups')
    """

    with connection.cursor() as cursor:
        cursor.execute(query, (metadata_schema,))
        rows = cursor.fetchall()

    found_types = {
        table_name: data_type
        for table_name, data_type in rows
    }

    missing_tables = [
        table_name
        for table_name in ("doc_types", "document_groups")
        if table_name not in found_types
    ]

    if missing_tables:
        missing = ", ".join(missing_tables)
        raise RuntimeError(
            f"Không tìm thấy cột id của bảng: {missing}. "
            f"Hãy kiểm tra schema RAG_METADATA_SCHEMA={metadata_schema!r}."
        )

    doc_type_name = found_types["doc_types"]
    doc_group_name = found_types["document_groups"]

    if doc_type_name not in SUPPORTED_ID_TYPES:
        raise RuntimeError(
            "Kiểu dữ liệu rag_metadata.doc_types.id chưa được hỗ trợ: "
            f"{doc_type_name}"
        )

    if doc_group_name not in SUPPORTED_ID_TYPES:
        raise RuntimeError(
            "Kiểu dữ liệu rag_metadata.document_groups.id "
            f"chưa được hỗ trợ: {doc_group_name}"
        )

    return (
        SUPPORTED_ID_TYPES[doc_type_name],
        SUPPORTED_ID_TYPES[doc_group_name],
    )


def build_schema_sql(
    metadata_schema: str,
    doc_type_id_type: sql.SQL,
    doc_group_id_type: sql.SQL,
) -> sql.Composed:
    metadata_schema_identifier = sql.Identifier(metadata_schema)

    return sql.SQL(
        """
        CREATE SCHEMA IF NOT EXISTS rag_client;

        CREATE TABLE IF NOT EXISTS rag_client.users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            username VARCHAR(100) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            full_name VARCHAR(150) NOT NULL,
            email VARCHAR(255),
            department VARCHAR(150),

            role VARCHAR(30) NOT NULL DEFAULT 'employee',
            account_status VARCHAR(20) NOT NULL DEFAULT 'active',

            session_version INTEGER NOT NULL DEFAULT 1,
            failed_login_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until TIMESTAMPTZ,

            last_login_at TIMESTAMPTZ,
            last_logout_at TIMESTAMPTZ,

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_users_username_nonempty
                CHECK (length(btrim(username)) > 0),

            CONSTRAINT chk_users_role
                CHECK (role IN ('admin', 'manager', 'employee')),

            CONSTRAINT chk_users_account_status
                CHECK (
                    account_status IN (
                        'active',
                        'locked',
                        'disabled'
                    )
                ),

            CONSTRAINT chk_users_session_version
                CHECK (session_version >= 1),

            CONSTRAINT chk_users_failed_attempts
                CHECK (failed_login_attempts >= 0)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_users_username_ci
            ON rag_client.users (lower(username));

        CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_users_email_ci
            ON rag_client.users (lower(email))
            WHERE email IS NOT NULL;


        CREATE TABLE IF NOT EXISTS rag_client.permission_groups (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code VARCHAR(60) NOT NULL UNIQUE,
            name VARCHAR(150) NOT NULL,
            description TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_permission_groups_code_nonempty
                CHECK (length(btrim(code)) > 0),

            CONSTRAINT chk_permission_groups_name_nonempty
                CHECK (length(btrim(name)) > 0)
        );

        -- Mỗi người dùng chỉ thuộc một nhóm quyền. Bảng document_permissions
        -- cũ được giữ lại để tương thích và phục vụ migration dữ liệu.
        ALTER TABLE rag_client.users
            ADD COLUMN IF NOT EXISTS permission_group_id UUID;

        DO $migration$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_users_permission_group'
                  AND conrelid = 'rag_client.users'::regclass
            ) THEN
                ALTER TABLE rag_client.users
                    ADD CONSTRAINT fk_users_permission_group
                    FOREIGN KEY (permission_group_id)
                    REFERENCES rag_client.permission_groups(id)
                    ON DELETE SET NULL;
            END IF;
        END
        $migration$;

        CREATE INDEX IF NOT EXISTS idx_rag_users_permission_group
            ON rag_client.users (permission_group_id);


        CREATE TABLE IF NOT EXISTS rag_client.permission_group_scopes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

            permission_group_id UUID NOT NULL
                REFERENCES rag_client.permission_groups(id)
                ON DELETE CASCADE,

            scope_type VARCHAR(20) NOT NULL,

            doc_type_id {}
                REFERENCES {}.doc_types(id)
                ON DELETE CASCADE,

            doc_group_id {}
                REFERENCES {}.document_groups(id)
                ON DELETE CASCADE,

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_permission_scope_type
                CHECK (
                    scope_type IN (
                        'all',
                        'doc_type',
                        'doc_group'
                    )
                ),

            CONSTRAINT chk_permission_scope_exactly_one_target
                CHECK (
                    (
                        scope_type = 'all'
                        AND doc_type_id IS NULL
                        AND doc_group_id IS NULL
                    )
                    OR
                    (
                        scope_type = 'doc_type'
                        AND doc_type_id IS NOT NULL
                        AND doc_group_id IS NULL
                    )
                    OR
                    (
                        scope_type = 'doc_group'
                        AND doc_type_id IS NULL
                        AND doc_group_id IS NOT NULL
                    )
                )
        );

        -- Nâng cấp an toàn từ schema cũ có phạm vi "document".
        -- Không tự xóa dữ liệu quyền: nếu đã có dòng document,
        -- transaction sẽ dừng và rollback để người quản trị xử lý.
        DO $migration$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM rag_client.permission_group_scopes
                WHERE scope_type = 'document'
            ) THEN
                RAISE EXCEPTION
                    'Không thể bỏ phạm vi document: permission_group_scopes vẫn có dữ liệu scope_type=document';
            END IF;
        END
        $migration$;

        DROP INDEX IF EXISTS rag_client.uq_rag_scopes_document;

        ALTER TABLE rag_client.permission_group_scopes
            DROP CONSTRAINT IF EXISTS chk_permission_scope_document_nonempty,
            DROP CONSTRAINT IF EXISTS chk_permission_scope_exactly_one_target,
            DROP CONSTRAINT IF EXISTS chk_permission_scope_type,
            DROP COLUMN IF EXISTS document_id;

        ALTER TABLE rag_client.permission_group_scopes
            ADD CONSTRAINT chk_permission_scope_type
                CHECK (
                    scope_type IN (
                        'all',
                        'doc_type',
                        'doc_group'
                    )
                ),
            ADD CONSTRAINT chk_permission_scope_exactly_one_target
                CHECK (
                    (
                        scope_type = 'all'
                        AND doc_type_id IS NULL
                        AND doc_group_id IS NULL
                    )
                    OR
                    (
                        scope_type = 'doc_type'
                        AND doc_type_id IS NOT NULL
                        AND doc_group_id IS NULL
                    )
                    OR
                    (
                        scope_type = 'doc_group'
                        AND doc_type_id IS NULL
                        AND doc_group_id IS NOT NULL
                    )
                );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_scopes_all
            ON rag_client.permission_group_scopes (
                permission_group_id
            )
            WHERE scope_type = 'all';

        CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_scopes_doc_type
            ON rag_client.permission_group_scopes (
                permission_group_id,
                doc_type_id
            )
            WHERE scope_type = 'doc_type';

        CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_scopes_doc_group
            ON rag_client.permission_group_scopes (
                permission_group_id,
                doc_group_id
            )
            WHERE scope_type = 'doc_group';

        CREATE TABLE IF NOT EXISTS rag_client.document_permissions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

            user_id UUID NOT NULL
                REFERENCES rag_client.users(id)
                ON DELETE CASCADE,

            permission_group_id UUID NOT NULL
                REFERENCES rag_client.permission_groups(id)
                ON DELETE CASCADE,

            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            expires_at TIMESTAMPTZ,

            assigned_by UUID
                REFERENCES rag_client.users(id)
                ON DELETE SET NULL,

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT uq_rag_document_permission_membership
                UNIQUE (user_id, permission_group_id)
        );

        CREATE INDEX IF NOT EXISTS idx_rag_document_permissions_group
            ON rag_client.document_permissions (
                permission_group_id,
                user_id
            );

        -- Chuyển lần gán nhóm còn hiệu lực gần nhất từ mô hình cũ sang users.
        UPDATE rag_client.users AS users
        SET permission_group_id = membership.permission_group_id,
            updated_at = NOW()
        FROM (
            SELECT DISTINCT ON (user_id)
                user_id,
                permission_group_id
            FROM rag_client.document_permissions
            WHERE is_active = TRUE
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY user_id, created_at DESC, id DESC
        ) AS membership
        WHERE users.id = membership.user_id
          AND users.permission_group_id IS NULL;


        CREATE TABLE IF NOT EXISTS rag_client.chat_history (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

            user_id UUID NOT NULL
                REFERENCES rag_client.users(id)
                ON DELETE CASCADE,

            conversation_id UUID NOT NULL,
            conversation_title VARCHAR(255),

            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL DEFAULT '',

            data_source VARCHAR(40),
            ai_provider VARCHAR(80),

            sources JSONB NOT NULL DEFAULT '[]'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_rag_chat_role
                CHECK (role IN ('user', 'assistant')),

            CONSTRAINT chk_rag_chat_sources_array
                CHECK (jsonb_typeof(sources) = 'array'),

            CONSTRAINT chk_rag_chat_metadata_object
                CHECK (jsonb_typeof(metadata) = 'object')
        );

        CREATE INDEX IF NOT EXISTS idx_rag_chat_user_conversation
            ON rag_client.chat_history (
                user_id,
                conversation_id,
                created_at,
                id
            );

        CREATE INDEX IF NOT EXISTS idx_rag_chat_user_recent
            ON rag_client.chat_history (
                user_id,
                created_at DESC
            );
        """
    ).format(
        doc_type_id_type,
        metadata_schema_identifier,
        doc_group_id_type,
        metadata_schema_identifier,
    )


def main() -> None:
    settings = get_settings()
    database_url = settings.database_url.get_secret_value()
    metadata_schema = settings.rag_metadata_schema

    print("Đang kết nối PostgreSQL...")
    print(f"Schema metadata: {metadata_schema}")
    print("Schema client: rag_client")

    try:
        with psycopg.connect(database_url) as connection:
            doc_type_id_type, doc_group_id_type = get_metadata_id_types(
                connection,
                metadata_schema,
            )

            schema_sql = build_schema_sql(
                metadata_schema,
                doc_type_id_type,
                doc_group_id_type,
            )

            with connection.cursor() as cursor:
                cursor.execute(schema_sql)

        print("Đã tạo hoặc kiểm tra thành công 5 bảng:")
        print("- rag_client.users")
        print("- rag_client.permission_groups")
        print("- rag_client.permission_group_scopes")
        print("- rag_client.document_permissions")
        print("- rag_client.chat_history")

    except Exception as error:
        print(f"Khởi tạo database thất bại: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
