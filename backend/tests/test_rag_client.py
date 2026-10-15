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


@pytest.mark.asyncio
async def test_product_requests_use_admin_api():
    def handler(request: httpx.Request):
        assert request.headers["Authorization"] == "Bearer test-admin-key"
        if request.url.path == "/api/v1/products":
            assert request.url.params["q"] == "S5921"
            return httpx.Response(
                200,
                json={"products": [{"product_code": "S5921"}], "total": 1},
            )
        assert request.url.path == "/api/v1/products/S5921"
        return httpx.Response(
            200,
            json={"product": {"product_code": "S5921"}},
        )

    async_client = httpx.AsyncClient(
        base_url="http://rag.test",
        transport=httpx.MockTransport(handler),
    )
    client = RagClient(get_settings(), client=async_client)

    listing = await client.list_products(query="S5921")
    detail = await client.get_product("S5921")

    await async_client.aclose()
    assert listing["products"][0]["product_code"] == "S5921"
    assert detail["product"]["product_code"] == "S5921"


@pytest.mark.asyncio
async def test_latest_products_uses_search_api():
    def handler(request: httpx.Request):
        assert request.url.path == "/api/v1/products/latest"
        assert request.headers["Authorization"] == "Bearer test-search-key"
        assert request.url.params["page"] == "2"
        assert request.url.params["limit"] == "5"
        assert request.url.params["date_from"] == "2026-10-01T00:00:00+07:00"
        assert request.url.params["date_to"] == "2026-11-01T00:00:00+07:00"
        return httpx.Response(
            200,
            json={
                "products": [
                    {"product_code": "GRXG7", "new_at": "2026-10-14T09:22:04Z"}
                ],
                "total": 1,
                "sort_by": "new_at",
            },
        )

    async_client = httpx.AsyncClient(
        base_url="http://rag.test",
        transport=httpx.MockTransport(handler),
    )
    client = RagClient(get_settings(), client=async_client)

    result = await client.list_latest_products(
        page=2,
        limit=5,
        date_from="2026-10-01T00:00:00+07:00",
        date_to="2026-11-01T00:00:00+07:00",
    )

    await async_client.aclose()
    assert result["products"][0]["product_code"] == "GRXG7"
