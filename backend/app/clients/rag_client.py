"""HTTP client for the upstream RAG Service."""
from typing import Any
from urllib.parse import quote

import httpx # type: ignore

from app.config import Settings


class RagServiceError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class RagClient:
    ALLOWED_ASSET_MEDIA_TYPES = {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "image/avif",
    }

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ):
        self.settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.rag_base_url,
            timeout=httpx.Timeout(settings.rag_timeout_seconds, connect=5.0),
            follow_redirects=False,
            headers={"Accept": "application/json"},
        )

    def _authorization_headers(
        self,
        *,
        admin: bool,
    ) -> dict[str, str]:
        key = (
            self.settings.rag_admin_api_key
            if admin
            else self.settings.rag_search_api_key
        )

        return {
            "Authorization": (
                f"Bearer {key.get_secret_value()}"
            ),
        }

    @staticmethod
    def _error_message(
        response: httpx.Response,
        body: Any,
    ) -> str:
        if isinstance(body, dict):
            detail = body.get("detail")

            if isinstance(detail, str):
                return detail

            if isinstance(detail, list):
                messages = []

                for item in detail:
                    if isinstance(item, dict):
                        message = item.get("msg")

                        if isinstance(message, str):
                            messages.append(message)

                if messages:
                    return "; ".join(messages)

        return (
            "RAG Service trả lỗi "
            f"HTTP {response.status_code}"
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        admin: bool,
        **kwargs,
    ) -> Any:
        headers = {
            **kwargs.pop("headers", {}),
            **self._authorization_headers(admin=admin),
        }

        try:
            response = await self._client.request(
                method,
                path,
                headers=headers,
                **kwargs,
            )
        except httpx.TimeoutException as exc:
            raise RagServiceError(
                "RAG Service phản hồi quá thời gian"
            ) from exc
        except httpx.RequestError as exc:
            raise RagServiceError(
                "Không thể kết nối RAG Service"
            ) from exc

        try:
            body = response.json()
        except ValueError:
            body = None

        if not response.is_success:
            raise RagServiceError(
                self._error_message(response, body),
                status_code=response.status_code,
                retry_after=response.headers.get("Retry-After"),
            )

        if body is None:
            raise RagServiceError(
                "RAG Service trả dữ liệu JSON không hợp lệ",
                status_code=response.status_code,
            )

        return body

    async def health(self) -> dict:
        try:
            response = await self._client.get("/health/live")
        except httpx.TimeoutException as exc:
            raise RagServiceError(
                "RAG Service phản hồi quá thời gian"
            ) from exc
        except httpx.RequestError as exc:
            raise RagServiceError(
                "Không thể kết nối RAG Service"
            ) from exc

        if not response.is_success:
            raise RagServiceError(
                f"RAG Service trả lỗi HTTP {response.status_code}",
                status_code=response.status_code,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise RagServiceError(
                "RAG Service trả dữ liệu JSON không hợp lệ"
            ) from exc

    async def get_asset(self, asset_id: int) -> tuple[bytes, str]:
        try:
            response = await self._client.get(
                f"/api/v1/knowledge/assets/{asset_id}",
                headers=self._authorization_headers(admin=False),
            )
        except httpx.TimeoutException as exc:
            raise RagServiceError("Ảnh tài liệu phản hồi quá thời gian") from exc
        except httpx.RequestError as exc:
            raise RagServiceError("Không thể tải ảnh từ RAG Service") from exc

        if not response.is_success:
            try:
                body = response.json()
            except ValueError:
                body = None
            raise RagServiceError(
                self._error_message(response, body),
                status_code=response.status_code,
                retry_after=response.headers.get("Retry-After"),
            )

        media_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if media_type not in self.ALLOWED_ASSET_MEDIA_TYPES:
            raise RagServiceError("RAG Service trả về định dạng ảnh không được hỗ trợ")
        return response.content, media_type

    async def search(
        self,
        query: str,
        *,
        doc_type_id: int | None = None,
        group_ids: list[int] | None = None,
        top_k: int | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "query": query,
            "top_k": top_k or self.settings.rag_top_k,
        }

        if doc_type_id is not None:
            payload["doc_type_id"] = doc_type_id

        if group_ids:
            payload["group_ids"] = group_ids

        result = await self._request(
            "POST",
            "/api/v1/knowledge/search",
            admin=False,
            json=payload,
        )

        required_fields = {
            "success",
            "status",
            "content",
            "sources",
            "elapsed_ms",
        }

        if (
            not isinstance(result, dict)
            or not required_fields.issubset(result)
            or not isinstance(result["sources"], list)
        ):
            raise RagServiceError(
                "Response tìm kiếm của RAG Service "
                "không đúng hợp đồng API"
            )

        return result

    async def list_documents(
        self,
        *,
        limit: int = 200,
        offset: int = 0,
        doc_type_id: int | None = None,
        group_id: int | None = None,
    ) -> dict:
        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
        }

        if doc_type_id is not None:
            params["doc_type_id"] = doc_type_id

        if group_id is not None:
            params["group_id"] = group_id

        result = await self._request(
            "GET",
            "/api/v1/documents",
            admin=True,
            params=params,
        )

        if (
            not isinstance(result, dict)
            or not isinstance(result.get("documents"), list)
        ):
            raise RagServiceError(
                "Response danh sách tài liệu không hợp lệ"
            )

        return result

    async def get_all_documents(
        self,
        *,
        doc_type_id: int | None = None,
        group_id: int | None = None,
    ) -> list[dict]:
        documents: list[dict] = []
        limit = 200
        offset = 0

        while True:
            result = await self.list_documents(
                limit=limit,
                offset=offset,
                doc_type_id=doc_type_id,
                group_id=group_id,
            )

            batch = result["documents"]
            documents.extend(batch)

            if len(batch) < limit:
                break

            offset += limit

        return documents

    async def get_document(
        self,
        document_id: str,
    ) -> dict:
        safe_id = quote(str(document_id), safe="")

        result = await self._request(
            "GET",
            f"/api/v1/documents/{safe_id}",
            admin=True,
        )

        if not isinstance(result, dict):
            raise RagServiceError(
                "Response chi tiết tài liệu không hợp lệ"
            )

        return result

    async def get_document_by_source_key(
        self,
        source_key: str,
    ) -> dict:
        result = await self._request(
            "GET",
            "/api/v1/documents/by-source-key",
            admin=True,
            params={"source_key": source_key},
        )

        if not isinstance(result, dict):
            raise RagServiceError(
                "Response chi tiết tài liệu không hợp lệ"
            )

        return result

    async def get_taxonomy(self) -> dict:
        result = await self._request(
            "GET",
            "/api/v1/taxonomy",
            admin=True,
        )

        if (
            not isinstance(result, dict)
            or not isinstance(result.get("doc_types"), list)
        ):
            raise RagServiceError(
                "Response taxonomy không hợp lệ"
            )

        return result

    async def close(self):
        if self._owns_client:
            await self._client.aclose()
