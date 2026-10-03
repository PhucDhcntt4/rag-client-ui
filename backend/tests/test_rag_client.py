import httpx
import pytest

from app.clients.rag_client import RagClient, RagServiceError
from app.config import get_settings


@pytest.mark.asyncio
async def test_search_uses_search_endpoint():
    def handler(request: httpx.Request):
        assert request.url.path == "/api/v1/knowledge/search"
        assert request.headers["Authorization"].startswith("Bearer ")
        return httpx.Response(
            200,
            json={
                "success": True,
                "status": "knowledge_found",
                "content": "Nội dung",
                "sources": [],
                "elapsed_ms": 12.5,
            },
        )

    async_client = httpx.AsyncClient(
        base_url="http://rag.test",
        transport=httpx.MockTransport(handler),
    )
    client = RagClient(get_settings(), client=async_client)
    result = await client.search("Câu hỏi")
    await async_client.aclose()
    assert result["status"] == "knowledge_found"


@pytest.mark.asyncio
async def test_upstream_error_is_wrapped():
    async_client = httpx.AsyncClient(
        base_url="http://rag.test",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(503, json={"detail": "Tạm lỗi"})
        ),
    )
    client = RagClient(get_settings(), client=async_client)
    with pytest.raises(RagServiceError, match="Tạm lỗi"):
        await client.search("Câu hỏi")
    await async_client.aclose()


@pytest.mark.asyncio
async def test_get_asset_uses_search_key_and_returns_image():
    def handler(request: httpx.Request):
        assert request.url.path == "/api/v1/knowledge/assets/8"
        assert request.headers["Authorization"].startswith("Bearer ")
        return httpx.Response(
            200,
            content=b"\x89PNG\r\n\x1a\nimage-data",
            headers={"Content-Type": "image/png"},
        )

    async_client = httpx.AsyncClient(
        base_url="http://rag.test",
        transport=httpx.MockTransport(handler),
    )
    client = RagClient(get_settings(), client=async_client)

    content, media_type = await client.get_asset(8)

    await async_client.aclose()
    assert content.startswith(b"\x89PNG")
    assert media_type == "image/png"
