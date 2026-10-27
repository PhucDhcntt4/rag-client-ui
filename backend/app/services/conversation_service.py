from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb


def ensure_conversation_access(
    connection,
    user_id: UUID,
    conversation_id: UUID,
) -> None:
    owner = connection.execute(
        """
        SELECT user_id
        FROM rag_client.chat_history
        WHERE conversation_id = %s
        LIMIT 1
        """,
        (conversation_id,),
    ).fetchone()

    if owner is not None and owner["user_id"] != user_id:
        # Không để lộ rằng conversation của người khác tồn tại.
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy cuộc trò chuyện.",
        )


def save_message(
    connection,
    *,
    user_id: UUID,
    conversation_id: UUID,
    conversation_title: str,
    message_id: UUID | None = None,
    role: str,
    content: str,
    data_source: str | None = None,
    ai_provider: str | None = None,
    sources: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_conversation_access(
        connection,
        user_id,
        conversation_id,
    )

    stored_message_id = message_id or uuid4()
    row = connection.execute(
        """
        INSERT INTO rag_client.chat_history (
            id,
            user_id,
            conversation_id,
            conversation_title,
            role,
            content,
            data_source,
            ai_provider,
            sources,
            metadata
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE
        SET conversation_title = EXCLUDED.conversation_title,
            content = EXCLUDED.content,
            data_source = EXCLUDED.data_source,
            ai_provider = EXCLUDED.ai_provider,
            sources = EXCLUDED.sources,
            metadata = EXCLUDED.metadata
        WHERE rag_client.chat_history.user_id = EXCLUDED.user_id
          AND rag_client.chat_history.conversation_id = EXCLUDED.conversation_id
          AND rag_client.chat_history.role = EXCLUDED.role
        RETURNING
            id,
            role,
            content,
            data_source,
            ai_provider,
            sources,
            metadata,
            created_at
        """,
        (
            stored_message_id,
            user_id,
            conversation_id,
            conversation_title,
            role,
            content,
            data_source,
            ai_provider,
            Jsonb(sources or []),
            Jsonb(metadata or {}),
        ),
    ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=409,
            detail="Mã tin nhắn đã được sử dụng ở cuộc trò chuyện khác.",
        )
    return row


def truncate_conversation_after_message(
    connection,
    *,
    user_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
) -> None:
    """Xóa câu trả lời cũ và các lượt sau khi người dùng bấm trả lời lại."""
    anchor = connection.execute(
        """
        SELECT created_at
        FROM rag_client.chat_history
        WHERE id = %s
          AND user_id = %s
          AND conversation_id = %s
          AND role = 'user'
        """,
        (message_id, user_id, conversation_id),
    ).fetchone()
    if anchor is None:
        return

    connection.execute(
        """
        DELETE FROM rag_client.chat_history
        WHERE user_id = %s
          AND conversation_id = %s
          AND (
                created_at > %s
                OR (created_at = %s AND id <> %s)
          )
        """,
        (
            user_id,
            conversation_id,
            anchor["created_at"],
            anchor["created_at"],
            message_id,
        ),
    )


def list_user_conversations(
    connection,
    *,
    user_id: UUID,
    limit: int = 20,
) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT
            conversation_id AS id,
            COALESCE(
                MAX(conversation_title),
                'Cuộc trò chuyện'
            ) AS title,
            COUNT(*)::integer AS message_count,
            MIN(created_at) AS created_at,
            MAX(created_at) AS updated_at
        FROM rag_client.chat_history
        WHERE user_id = %s
        GROUP BY conversation_id
        ORDER BY MAX(created_at) DESC
        LIMIT %s
        """,
        (user_id, limit),
    ).fetchall()


def get_user_conversation(
    connection,
    *,
    user_id: UUID,
    conversation_id: UUID,
) -> dict[str, Any]:
    messages = connection.execute(
        """
        SELECT
            id,
            role,
            content,
            data_source,
            ai_provider,
            sources,
            metadata,
            created_at
        FROM rag_client.chat_history
        WHERE user_id = %s
          AND conversation_id = %s
        ORDER BY created_at, id
        """,
        (user_id, conversation_id),
    ).fetchall()

    if not messages:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy cuộc trò chuyện.",
        )

    summary = connection.execute(
        """
        SELECT
            conversation_id AS id,
            COALESCE(
                MAX(conversation_title),
                'Cuộc trò chuyện'
            ) AS title,
            COUNT(*)::integer AS message_count,
            MIN(created_at) AS created_at,
            MAX(created_at) AS updated_at
        FROM rag_client.chat_history
        WHERE user_id = %s
          AND conversation_id = %s
        GROUP BY conversation_id
        """,
        (user_id, conversation_id),
    ).fetchone()

    return {
        **summary,
        "messages": messages,
    }


def delete_user_conversation(
    connection,
    *,
    user_id: UUID,
    conversation_id: UUID,
) -> None:
    deleted = connection.execute(
        """
        DELETE FROM rag_client.chat_history
        WHERE user_id = %s
          AND conversation_id = %s
        RETURNING id
        """,
        (user_id, conversation_id),
    ).fetchone()

    if deleted is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy cuộc trò chuyện.",
        )


def delete_all_user_conversations(
    connection,
    *,
    user_id: UUID,
) -> int:
    deleted = connection.execute(
        """
        DELETE FROM rag_client.chat_history
        WHERE user_id = %s
        RETURNING id
        """,
        (user_id,),
    ).fetchall()
    return len(deleted)
