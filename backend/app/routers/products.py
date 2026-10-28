from typing import Annotated

from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile

from app.clients.rag_client import RagClient, RagServiceError
from app.schemas import ProductImageSearchResponse, ProductPageResponse
from app.services.product_service import ProductService


router = APIRouter(
    prefix="/api/products",
    tags=["Products"],
)


def get_rag_client(request: Request) -> RagClient:
    return request.app.state.rag_client


RagClientDependency = Annotated[
    RagClient,
    Depends(get_rag_client),
]


def get_product_service(request: Request) -> ProductService:
    return request.app.state.product_service


ProductServiceDependency = Annotated[
    ProductService,
    Depends(get_product_service),
]


@router.get("")
async def list_products(
    rag_client: RagClientDependency,
    q: str | None = Query(default=None, max_length=200),
    product_type: str | None = Query(default=None, max_length=200),
    status: str | None = Query(default="ACTIVE", max_length=30),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    return await rag_client.list_products(
        query=q,
        product_type=product_type,
        status=status,
        page=page,
        limit=limit,
    )


@router.get("/latest")
async def latest_products(
    rag_client: RagClientDependency,
    product_type: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=50),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
):
    return await rag_client.list_latest_products(
        product_type=product_type,
        page=page,
        limit=limit,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
    )


@router.get("/latest/details", response_model=ProductPageResponse)
async def latest_product_details(
    product_service: ProductServiceDependency,
    page: int = Query(default=1, ge=1),
    limit: int | None = Query(default=None, ge=1, le=50),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
):
    return await product_service.list_latest_page(
        page=page,
        limit=limit,
        date_from=date_from,
        date_to=date_to,
    )


@router.post("/image-search", response_model=ProductImageSearchResponse)
async def search_products_by_image(
    rag_client: RagClientDependency,
    file: Annotated[UploadFile, File()],
):
    try:
        max_bytes = rag_client.settings.product_image_max_bytes
        data = await file.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Ảnh vượt giới hạn {max_bytes} byte.",
            )
        return await rag_client.search_products_by_image(
            filename=file.filename or "image",
            media_type=file.content_type or "",
            data=data,
        )
    except RagServiceError as exc:
        upstream_status = exc.status_code or 503
        status_code = (
            upstream_status
            if upstream_status in {400, 404, 413, 415, 422, 429}
            else 503
        )
        headers = {"Retry-After": exc.retry_after} if exc.retry_after else None
        raise HTTPException(
            status_code=status_code,
            detail=str(exc),
            headers=headers,
        ) from exc
    finally:
        await file.close()


@router.get("/{product_code}")
async def product_detail(
    product_code: str,
    rag_client: RagClientDependency,
):
    return await rag_client.get_product(product_code)
