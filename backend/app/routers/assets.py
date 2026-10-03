"""Same-origin proxy for protected RAG document images."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response

from app.clients.rag_client import RagClient


router = APIRouter(prefix="/api/rag-assets", tags=["Assets"])


def get_rag_client(request: Request) -> RagClient:
    return request.app.state.rag_client


RagClientDependency = Annotated[RagClient, Depends(get_rag_client)]


@router.get("/{asset_id}")
async def get_asset(
    rag_client: RagClientDependency,
    asset_id: Annotated[int, Path(ge=1)],
):
    content, media_type = await rag_client.get_asset(asset_id)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": f'inline; filename="rag-asset-{asset_id}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
