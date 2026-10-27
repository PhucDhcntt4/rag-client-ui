"""Same-origin proxy for protected RAG document images."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response

from app.clients.rag_client import RagClient
from app.security.dependencies import DatabaseConnection
from app.services.access_control import DocumentAccessDependency


router = APIRouter(prefix="/api/rag-assets", tags=["Assets"])


def get_rag_client(request: Request) -> RagClient:
    return request.app.state.rag_client


RagClientDependency = Annotated[RagClient, Depends(get_rag_client)]


@router.get("/{asset_id}")
async def get_asset(
    rag_client: RagClientDependency,
    access: DocumentAccessDependency,
    connection: DatabaseConnection,
    asset_id: Annotated[int, Path(ge=1)],
):
    if not access.unrestricted:
        asset = connection.execute(
            """
            SELECT document_id
            FROM rag_metadata.document_assets
            WHERE id = %s
            """,
            (asset_id,),
        ).fetchone()
        if asset is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy ảnh tài liệu.")
        document = await rag_client.get_document(str(asset["document_id"]))
        if not access.allows(
            document.get("doc_type_id"),
            document.get("group_id"),
        ):
            raise HTTPException(
                status_code=403,
                detail="Bạn không có quyền xem ảnh của tài liệu này.",
            )
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
