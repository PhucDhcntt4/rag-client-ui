"""Taxonomy endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.schemas import TaxonomyResponse
from app.services.document_service import DocumentService


router = APIRouter(prefix="/api", tags=["Taxonomy"])


def get_document_service(request: Request) -> DocumentService:
    return request.app.state.document_service


DocumentServiceDependency = Annotated[
    DocumentService,
    Depends(get_document_service),
]


@router.get("/taxonomy", response_model=TaxonomyResponse)
async def taxonomy(service: DocumentServiceDependency):
    return await service.get_taxonomy()
