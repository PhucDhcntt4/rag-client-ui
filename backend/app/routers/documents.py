"""Read-only document endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.schemas import DocumentDetail, DocumentListResponse
from app.services.document_service import DocumentService


router = APIRouter(prefix="/api/documents", tags=["Documents"])


def get_document_service(request: Request) -> DocumentService:
    return request.app.state.document_service


DocumentServiceDependency = Annotated[
    DocumentService,
    Depends(get_document_service),
]


@router.get("", response_model=DocumentListResponse)
async def list_documents(service: DocumentServiceDependency):
    return await service.list_documents()


@router.get("/by-source-key", response_model=DocumentDetail)
async def document_by_source_key(
    service: DocumentServiceDependency,
    source_key: str = Query(min_length=1, max_length=500),
):
    return await service.get_document_by_source_key(source_key)


@router.get("/{document_id}", response_model=DocumentDetail)
async def document(document_id: str, service: DocumentServiceDependency):
    return await service.get_document(document_id)
