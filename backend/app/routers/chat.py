"""Grounded chat endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.schemas import ChatRequest, ChatResponse
from app.services.chat_service import ChatService


router = APIRouter(prefix="/api", tags=["Chat"])


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service


ChatServiceDependency = Annotated[ChatService, Depends(get_chat_service)]


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, service: ChatServiceDependency):
    return await service.answer(payload)
