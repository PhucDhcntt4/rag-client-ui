"""Read-only document facade for the browser client."""

import re

from fastapi import HTTPException

from app.clients.rag_client import RagClient
from app.schemas import (
    DocumentDetail,
    DocumentListResponse,
    DocumentSummary,
    TaxonomyDocType,
    TaxonomyGroup,
    TaxonomyResponse,
)
from app.services.access_control import DocumentAccess


class DocumentService:
    def __init__(self, rag_client: RagClient):
        self.rag_client = rag_client

    @staticmethod
    def _description(text: str, limit: int = 220) -> str:
        normalized = re.sub(r"\s+", " ", text or "").strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 1].rstrip() + "…"

    def _summary(self, row: dict) -> DocumentSummary:
        return DocumentSummary(
            id=str(row.get("id", "")),
            source_key=str(row.get("source_key", "")),
            title=str(row.get("title") or "Tài liệu chưa có tiêu đề"),
            category=str(row.get("category") or "other"),
            doc_type_id=row.get("doc_type_id"),
            group_id=row.get("group_id"),
            description=self._description(str(row.get("source_text") or "")),
            updated_at=row.get("updated_at") or row.get("created_at"),
            file_name=row.get("file_name"),
            file_size=row.get("file_size"),
            chunk_count=int(row.get("chunk_count") or 0),
            is_active=bool(row.get("is_active", True)),
        )

    def _detail(self, row: dict) -> DocumentDetail:
        summary = self._summary(row)
        return DocumentDetail(
            **summary.model_dump(),
            content=str(row.get("source_text") or ""),
            has_local_file=bool(row.get("has_local_file")),
        )

    async def list_documents(
        self,
        access: DocumentAccess | None = None,
    ) -> DocumentListResponse:
        rows = await self.rag_client.get_all_documents()
        effective_access = access or DocumentAccess(unrestricted=True)
        documents = [
            self._summary(row)
            for row in rows
            if bool(row.get("is_active", True))
            and effective_access.allows(
                row.get("doc_type_id"),
                row.get("group_id"),
            )
        ]
        return DocumentListResponse(documents=documents)

    @staticmethod
    def _ensure_allowed(row: dict, access: DocumentAccess | None) -> None:
        effective_access = access or DocumentAccess(unrestricted=True)
        if not effective_access.allows(
            row.get("doc_type_id"),
            row.get("group_id"),
        ):
            raise HTTPException(
                status_code=403,
                detail="Bạn không có quyền xem tài liệu này.",
            )

    async def get_document(
        self,
        document_id: str,
        access: DocumentAccess | None = None,
    ) -> DocumentDetail:
        row = await self.rag_client.get_document(document_id)
        self._ensure_allowed(row, access)
        return self._detail(row)

    async def get_document_by_source_key(
        self,
        source_key: str,
        access: DocumentAccess | None = None,
    ) -> DocumentDetail:
        row = await self.rag_client.get_document_by_source_key(source_key)
        self._ensure_allowed(row, access)
        return self._detail(row)

    async def get_taxonomy(
        self,
        access: DocumentAccess | None = None,
    ) -> TaxonomyResponse:
        data = await self.rag_client.get_taxonomy()
        effective_access = access or DocumentAccess(unrestricted=True)
        doc_types = []
        for item in data["doc_types"]:
            doc_type_id = int(item["id"])
            allow_entire_type = (
                effective_access.unrestricted
                or doc_type_id in effective_access.doc_type_ids
            )
            groups = [
                TaxonomyGroup(
                    id=group["id"],
                    code=group["code"],
                    name=group["name"],
                    description=group.get("description") or "",
                    doc_type_id=group["doc_type_id"],
                    is_active=bool(group.get("is_active", True)),
                    sort_order=int(group.get("sort_order") or 0),
                    document_count=int(group.get("document_count") or 0),
                )
                for group in item.get("groups", [])
                if allow_entire_type
                or int(group["id"]) in effective_access.group_ids
            ]
            if not allow_entire_type and not groups:
                continue
            doc_types.append(
                TaxonomyDocType(
                    id=item["id"],
                    code=item["code"],
                    name=item["name"],
                    description=item.get("description") or "",
                    is_active=bool(item.get("is_active", True)),
                    sort_order=int(item.get("sort_order") or 0),
                    groups=groups,
                )
            )
        return TaxonomyResponse(doc_types=doc_types)
