"""Read-only document facade for the browser client."""

import re

from app.clients.rag_client import RagClient
from app.schemas import (
    DocumentDetail,
    DocumentListResponse,
    DocumentSummary,
    TaxonomyDocType,
    TaxonomyGroup,
    TaxonomyResponse,
)


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

    async def list_documents(self) -> DocumentListResponse:
        rows = await self.rag_client.get_all_documents()
        documents = [
            self._summary(row)
            for row in rows
            if bool(row.get("is_active", True))
        ]
        return DocumentListResponse(documents=documents)

    async def get_document(self, document_id: str) -> DocumentDetail:
        return self._detail(await self.rag_client.get_document(document_id))

    async def get_document_by_source_key(self, source_key: str) -> DocumentDetail:
        row = await self.rag_client.get_document_by_source_key(source_key)
        return self._detail(row)

    async def get_taxonomy(self) -> TaxonomyResponse:
        data = await self.rag_client.get_taxonomy()
        doc_types = []
        for item in data["doc_types"]:
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
            ]
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
