from uuid import UUID

from fastapi import APIRouter, Query

from app.schemas import (
    AdminMutationResponse,
    ConversationDetail,
    ConversationListResponse,
    ConversationMessageCreate,
    ConversationMessageInfo,
    ConversationSummary,
)
from app.security.dependencies import CurrentUser, DatabaseConnection
from app.services.conversation_service import (
    delete_all_user_conversations,
    delete_user_conversation,
    get_user_conversation,
    list_user_conversations,
    save_message,
)


router = APIRouter(
    prefix="/api/conversations",
    tags=["Conversations"],
)


@router.post(
    "/{conversation_id}/messages",
    response_model=ConversationMessageInfo,
)
def create_conversation_message(
    conversation_id: UUID,
    payload: ConversationMessageCreate,
    current_user: CurrentUser,
    connection: DatabaseConnection,
):
    row = save_message(
        connection,
        user_id=current_user.id,
        conversation_id=conversation_id,
        conversation_title=payload.conversation_title,
        message_id=payload.id,
        role=payload.role,
        content=payload.content,
        data_source=payload.data_source,
        ai_provider=payload.ai_provider,
        sources=payload.sources,
        metadata=payload.metadata,
    )
    return ConversationMessageInfo(**row)


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    current_user: CurrentUser,
    connection: DatabaseConnection,
    limit: int = Query(default=20, ge=1, le=100),
):
    rows = list_user_conversations(
        connection,
        user_id=current_user.id,
        limit=limit,
    )

    return ConversationListResponse(
        conversations=[
            ConversationSummary(**row)
            for row in rows
        ]
    )


@router.delete("", response_model=AdminMutationResponse)
def delete_all_conversations(
    current_user: CurrentUser,
    connection: DatabaseConnection,
):
    deleted_count = delete_all_user_conversations(
        connection,
        user_id=current_user.id,
    )
    return AdminMutationResponse(
        message=f"Đã xóa {deleted_count} tin nhắn trong lịch sử.",
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetail,
)
def get_conversation(
    conversation_id: UUID,
    current_user: CurrentUser,
    connection: DatabaseConnection,
):
    result = get_user_conversation(
        connection,
        user_id=current_user.id,
        conversation_id=conversation_id,
    )

    return ConversationDetail(**result)


@router.delete(
    "/{conversation_id}",
    response_model=AdminMutationResponse,
)
def delete_conversation(
    conversation_id: UUID,
    current_user: CurrentUser,
    connection: DatabaseConnection,
):
    delete_user_conversation(
        connection,
        user_id=current_user.id,
        conversation_id=conversation_id,
    )

    return AdminMutationResponse(
        message="Đã xóa cuộc trò chuyện.",
    )
