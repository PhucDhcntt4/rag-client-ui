
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from uuid import uuid4
from app.security.dependencies import (
    CurrentUser,
    DatabaseConnection
)
from app.services.conversation_service import (
    save_message,
    truncate_conversation_after_message,
)
from app.schemas import ChatRequest, ChatResponse
from app.services.chat_service import ChatService
from app.services.access_control import DocumentAccessDependency


router = APIRouter(prefix="/api", tags=["Chat"])


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service


ChatServiceDependency = Annotated[ChatService, Depends(get_chat_service)]


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    service: ChatServiceDependency,
    access: DocumentAccessDependency,
    current_user: CurrentUser,
    connection: DatabaseConnection,
):
    conversation_id = payload.conversation_id or uuid4()
    user_message_id = payload.message_id or uuid4()

    conversation_title = (
        payload.conversation_title
        or payload.query[:80]
        or "Cuộc trò chuyện"
    )

    # Lưu câu hỏi trước để không mất nội dung nếu LLM gặp lỗi.
    save_message(
        connection,
        user_id=current_user.id,
        conversation_id=conversation_id,
        conversation_title=conversation_title,
        message_id=user_message_id,
        role="user",
        content=payload.query,
        data_source=payload.data_source,
        ai_provider=payload.ai_provider,
        metadata={
            "doc_type_id": payload.doc_type_id,
            "group_ids": payload.group_ids or [],
        },
    )

    truncate_conversation_after_message(
        connection,
        user_id=current_user.id,
        conversation_id=conversation_id,
        message_id=user_message_id,
    )

    result = await service.answer(payload, access)

    document_sources = [
        source.model_dump(mode="json")
        for source in result.sources
    ]

    product_sources = [
        product.model_dump(mode="json")
        for product in result.product_sources
    ]

    product_result = (
        result.product_result.model_dump(mode="json")
        if result.product_result
        else None
    )

    assistant_message = save_message(
        connection,
        user_id=current_user.id,
        conversation_id=conversation_id,
        conversation_title=conversation_title,
        role="assistant",
        content=result.answer,
        data_source=result.data_source,
        ai_provider=result.llm_provider,
        sources=document_sources,
        metadata={
            "product_sources": product_sources,
            "product_result": product_result,
            "query": payload.query,
            "model": result.model,
            "reply_to_message_id": str(user_message_id),
            # Có thể bỏ retrieved_content nếu không muốn DB tăng nhanh.
            "retrieved_content": result.retrieved_content,
        },
    )

    return result.model_copy(
        update={
            "conversation_id": conversation_id,
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_message["id"],
        }
    )
