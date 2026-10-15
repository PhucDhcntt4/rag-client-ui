import httpx
import pytest

from app.clients.qdrant_image_client import QdrantImageClient
from app.config import get_settings
from app.services.product_image_service import (
    ProductImageSearchError,
    ProductImageService,
)


class FakeEmbedder:
    def embed(self, data: bytes) -> list[float]:
        assert data == b"valid-image"
        return [0.5] * 512


class FakeImageQdrant:
    async def search(self, vector, *, limit, score_threshold):
        assert len(vector) == 512
        assert limit == 50
        assert score_threshold is None
        return [
            {
                "score": 0.91,
                "payload": {
                    "product_code": "IMG01",
                    "color": "Đen",
                    "image_checksum": "best",
                },
            },
            {
                "score": 0.83,
                "payload": {
                    "product_code": "IMG01",
                    "color": "Trắng",
                    "image_checksum": "duplicate",
                },
            },
            {
                "score": 0.72,
                "payload": {
                    "product_code": "INACTIVE01",
                    "color": "Nâu",
                    "image_checksum": "inactive",
                },
            },
        ]


class FakeImageRagClient:
    async def get_product(self, product_code: str):
        status = "INACTIVE" if product_code == "INACTIVE01" else "ACTIVE"
        return {
            "product": {
                "product_code": product_code,
                "title": f"Sản phẩm {product_code}",
                "status": status,
                "public_info": {
                    "image_urls": [f"https://example.test/{product_code}.jpg"],
                },
                "images": [
                    {
                        "image_checksum": "best",
                        "color": "Đen",
                        "source_url": "https://example.test/matched.jpg",
                    }
                ],
                "variants": [],
            }
        }


def image_settings():
    return get_settings().model_copy(
        update={
            "product_image_search_enabled": True,
            "product_image_candidate_limit": 50,
            "product_image_result_limit": 8,
            "product_image_min_score": 0.25,
        }
    )


@pytest.mark.asyncio
async def test_image_search_deduplicates_and_loads_active_product_details():
    service = ProductImageService(
        image_settings(),
        FakeEmbedder(),
        FakeImageQdrant(),
        FakeImageRagClient(),
    )

    result = await service.search(
        filename="folder\\shoe.jpg",
        media_type="image/jpeg",
        data=b"valid-image",
    )

    assert result.query_image.filename == "shoe.jpg"
    assert result.result.total == 1
    assert [product.product_code for product in result.products] == ["IMG01"]
    assert result.products[0].image_similarity == pytest.approx(0.91)
    assert result.products[0].matched_color == "Đen"
    assert result.products[0].image_urls[0].endswith("matched.jpg")
    assert result.low_confidence is False
    assert result.best_similarity == pytest.approx(0.91)


@pytest.mark.asyncio
async def test_image_search_returns_nearest_products_when_all_scores_are_low():
    class LowScoreQdrant:
        async def search(self, vector, *, limit, score_threshold):
            assert score_threshold is None
            return [
                {
                    "score": 0.20,
                    "payload": {
                        "product_code": "IMG01",
                        "color": "Đen",
                        "image_checksum": "best",
                    },
                }
            ]

    service = ProductImageService(
        image_settings(),
        FakeEmbedder(),
        LowScoreQdrant(),
        FakeImageRagClient(),
    )

    result = await service.search(
        filename="shoe.jpg",
        media_type="image/jpeg",
        data=b"valid-image",
    )

    assert [product.product_code for product in result.products] == ["IMG01"]
    assert result.low_confidence is True
    assert result.best_similarity == pytest.approx(0.20)


@pytest.mark.asyncio
async def test_image_search_rejects_unsupported_media_type():
    service = ProductImageService(
        image_settings(),
        FakeEmbedder(),
        FakeImageQdrant(),
        FakeImageRagClient(),
    )

    with pytest.raises(ProductImageSearchError) as caught:
        await service.search(
            filename="shoe.gif",
            media_type="image/gif",
            data=b"valid-image",
        )

    assert caught.value.status_code == 415


@pytest.mark.asyncio
async def test_qdrant_image_client_uses_image_collection_query_endpoint():
    def handler(request: httpx.Request):
        assert request.url.path == "/collections/images-v2/points/query"
        assert request.headers["api-key"] == "secret"
        payload = __import__("json").loads(request.content)
        assert len(payload["query"]) == 512
        assert payload["limit"] == 12
        assert payload["score_threshold"] == 0.3
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "result": {
                    "points": [
                        {
                            "id": 1,
                            "score": 0.8,
                            "payload": {"product_code": "IMG01"},
                        }
                    ]
                },
            },
        )

    async_client = httpx.AsyncClient(
        base_url="http://qdrant.test",
        transport=httpx.MockTransport(handler),
    )
    client = QdrantImageClient(
        base_url="http://qdrant.test",
        collection="images-v2",
        api_key="secret",
        client=async_client,
    )

    result = await client.search(
        [0.1] * 512,
        limit=12,
        score_threshold=0.3,
    )

    await async_client.aclose()
    assert result[0]["payload"]["product_code"] == "IMG01"
