import httpx
import pytest

from app.clients.gemini_vision_client import (
    GeminiVisionError,
    ProductVisionAnalysis,
)
from app.clients.product_visual_verifier import ProductVisualMatch
from app.clients.qdrant_image_client import QdrantImageClient, QdrantImageError
from app.config import get_settings
from app.services.image_processing_service import (
    ProcessedProductImage,
    ProductBoundingBox,
)
from app.services.product_category_mapping import load_product_category_mapping
from app.services.product_image_decision import ProductImageDecisionEngine
from app.services.product_image_downloader import DownloadedProductImage
from app.services.product_image_service import (
    ProductImageSearchError,
    ProductImageService,
)


class FakeEmbedder:
    def embed(self, data: bytes) -> list[float]:
        assert data == b"valid-image"
        return [0.5] * 512


class RecordingEmbedder:
    def __init__(self):
        self.received_data: bytes | None = None

    def embed(self, data: bytes) -> list[float]:
        self.received_data = data
        return [0.5] * 512


class FakeVisionClient:
    async def analyze(self, *, data: bytes, media_type: str):
        assert data == b"valid-image"
        assert media_type == "image/jpeg"
        return ProductVisionAnalysis(
            product_detected=True,
            category="shoe",
            label="Giày",
            bounding_box=ProductBoundingBox(
                x_min=0.1,
                y_min=0.2,
                x_max=0.9,
                y_max=0.8,
            ),
            confidence=0.95,
            description="Giày màu đen",
        )


class FakeImageProcessor:
    def process(self, data: bytes, bounding_box: ProductBoundingBox):
        assert data == b"valid-image"
        assert bounding_box.x_min == pytest.approx(0.1)
        return ProcessedProductImage(
            data=b"cropped-image",
            width=640,
            height=480,
            original_width=1280,
            original_height=960,
            crop_applied=True,
        )


class FakeImageQdrant:
    async def search(
        self,
        vector,
        *,
        limit,
        score_threshold,
        product_types=None,
    ):
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
        async def search(
            self,
            vector,
            *,
            limit,
            score_threshold,
            product_types=None,
        ):
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
async def test_image_search_embeds_the_product_crop_when_vision_is_enabled():
    embedder = RecordingEmbedder()
    settings = image_settings().model_copy(
        update={
            "product_vision_enabled": True,
            "product_image_fast_accept_score": 0.99,
        }
    )
    service = ProductImageService(
        settings,
        embedder,
        FakeImageQdrant(),
        FakeImageRagClient(),
        vision_client=FakeVisionClient(),
        image_processor=FakeImageProcessor(),
    )

    await service.search(
        filename="shoe.jpg",
        media_type="image/jpeg",
        data=b"valid-image",
    )

    assert embedder.received_data == b"cropped-image"


@pytest.mark.asyncio
async def test_image_search_falls_back_to_original_image_when_vision_fails():
    class FailingVisionClient:
        async def analyze(self, *, data: bytes, media_type: str):
            raise GeminiVisionError("Vision unavailable")

    embedder = RecordingEmbedder()
    settings = image_settings().model_copy(
        update={
            "product_vision_enabled": True,
            "product_image_fast_accept_score": 0.99,
        }
    )
    service = ProductImageService(
        settings,
        embedder,
        FakeImageQdrant(),
        FakeImageRagClient(),
        vision_client=FailingVisionClient(),
        image_processor=FakeImageProcessor(),
    )

    await service.search(
        filename="shoe.jpg",
        media_type="image/jpeg",
        data=b"valid-image",
    )

    assert embedder.received_data == b"valid-image"


@pytest.mark.asyncio
async def test_image_search_rejects_image_without_a_detected_product():
    class NoProductVisionClient:
        async def analyze(self, *, data: bytes, media_type: str):
            return ProductVisionAnalysis(
                product_detected=False,
                category="unknown",
                label="",
                bounding_box=None,
                confidence=0.1,
                description="Không phát hiện sản phẩm",
            )

    embedder = RecordingEmbedder()
    settings = image_settings().model_copy(
        update={
            "product_vision_enabled": True,
            "product_image_fast_accept_score": 0.99,
        }
    )
    service = ProductImageService(
        settings,
        embedder,
        FakeImageQdrant(),
        FakeImageRagClient(),
        vision_client=NoProductVisionClient(),
        image_processor=FakeImageProcessor(),
    )

    with pytest.raises(ProductImageSearchError) as caught:
        await service.search(
            filename="room.jpg",
            media_type="image/jpeg",
            data=b"valid-image",
        )

    assert caught.value.status_code == 422
    assert embedder.received_data == b"valid-image"


@pytest.mark.asyncio
async def test_image_search_combines_global_and_category_results_by_best_score():
    class RecordingQdrant:
        def __init__(self):
            self.calls = []

        async def search(
            self,
            vector,
            *,
            limit,
            score_threshold,
            product_types=None,
        ):
            self.calls.append(product_types)
            if product_types:
                return [
                    {
                        "score": 0.95,
                        "payload": {
                            "product_code": "IMG01",
                            "color": "Đen",
                            "image_checksum": "best",
                        },
                    },
                    {
                        "score": 0.88,
                        "payload": {
                            "product_code": "IMG02",
                            "color": "Nâu",
                            "image_checksum": "second",
                        },
                    },
                ]
            return [
                {
                    "score": 0.80,
                    "payload": {
                        "product_code": "IMG01",
                        "color": "Trắng",
                        "image_checksum": "older",
                    },
                }
            ]

    qdrant = RecordingQdrant()
    embedder = RecordingEmbedder()
    settings = image_settings().model_copy(
        update={"product_vision_enabled": True}
    )
    service = ProductImageService(
        settings,
        embedder,
        qdrant,
        FakeImageRagClient(),
        vision_client=FakeVisionClient(),
        image_processor=FakeImageProcessor(),
        category_mapping={"shoe": ["GIAY TEST"]},
    )

    result = await service.search(
        filename="shoe.jpg",
        media_type="image/jpeg",
        data=b"valid-image",
    )

    assert qdrant.calls == [None, None, ("GIAY TEST",)]
    assert [product.product_code for product in result.products] == [
        "IMG01",
        "IMG02",
    ]
    assert result.products[0].image_similarity == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_image_search_skips_category_query_for_unknown_category():
    class UnknownCategoryVisionClient:
        async def analyze(self, *, data: bytes, media_type: str):
            return ProductVisionAnalysis(
                product_detected=True,
                category="unknown",
                label="Sản phẩm",
                bounding_box=None,
                confidence=0.5,
                description="Không xác định được nhóm",
            )

    class RecordingQdrant(FakeImageQdrant):
        def __init__(self):
            self.calls = []

        async def search(self, *args, product_types=None, **kwargs):
            self.calls.append(product_types)
            return await super().search(
                *args,
                product_types=product_types,
                **kwargs,
            )

    qdrant = RecordingQdrant()
    service = ProductImageService(
        image_settings().model_copy(
            update={
                "product_vision_enabled": True,
                "product_image_fast_accept_score": 0.99,
            }
        ),
        RecordingEmbedder(),
        qdrant,
        FakeImageRagClient(),
        vision_client=UnknownCategoryVisionClient(),
        image_processor=FakeImageProcessor(),
        category_mapping={"shoe": ["GIAY TEST"], "unknown": []},
    )

    await service.search(
        filename="product.jpg",
        media_type="image/jpeg",
        data=b"valid-image",
    )

    assert qdrant.calls == [None]


@pytest.mark.asyncio
async def test_image_search_uses_global_results_when_category_query_fails():
    class CategoryFailureQdrant(FakeImageQdrant):
        async def search(
            self,
            vector,
            *,
            limit,
            score_threshold,
            product_types=None,
        ):
            if product_types:
                raise QdrantImageError("Category query failed")
            return await super().search(
                vector,
                limit=limit,
                score_threshold=score_threshold,
            )

    service = ProductImageService(
        image_settings().model_copy(
            update={
                "product_vision_enabled": True,
                "product_image_fast_accept_score": 0.99,
            }
        ),
        RecordingEmbedder(),
        CategoryFailureQdrant(),
        FakeImageRagClient(),
        vision_client=FakeVisionClient(),
        image_processor=FakeImageProcessor(),
        category_mapping={"shoe": ["GIAY TEST"]},
    )

    result = await service.search(
        filename="shoe.jpg",
        media_type="image/jpeg",
        data=b"valid-image",
    )

    assert [product.product_code for product in result.products] == ["IMG01"]


@pytest.mark.asyncio
async def test_image_search_skips_vision_for_a_clear_qdrant_winner():
    class ForbiddenVisionClient:
        async def analyze(self, *, data: bytes, media_type: str):
            raise AssertionError("Gemini Vision must not be called")

    class RecordingQdrant(FakeImageQdrant):
        def __init__(self):
            self.calls = 0

        async def search(self, *args, **kwargs):
            self.calls += 1
            return await super().search(*args, **kwargs)

    qdrant = RecordingQdrant()
    embedder = RecordingEmbedder()
    service = ProductImageService(
        image_settings().model_copy(
            update={
                "product_vision_enabled": True,
                "product_image_fast_accept_score": 0.88,
                "product_image_fast_accept_margin": 0.08,
            }
        ),
        embedder,
        qdrant,
        FakeImageRagClient(),
        vision_client=ForbiddenVisionClient(),
        image_processor=FakeImageProcessor(),
    )

    result = await service.search(
        filename="clear-shoe.jpg",
        media_type="image/jpeg",
        data=b"valid-image",
    )

    assert qdrant.calls == 1
    assert embedder.received_data == b"valid-image"
    assert result.best_similarity == pytest.approx(0.91)


@pytest.mark.asyncio
async def test_image_search_calls_vision_when_top_scores_are_too_close():
    class CloseScoreQdrant:
        async def search(
            self,
            vector,
            *,
            limit,
            score_threshold,
            product_types=None,
        ):
            return [
                {
                    "score": 0.90,
                    "payload": {
                        "product_code": "IMG01",
                        "color": "Đen",
                        "image_checksum": "best",
                    },
                },
                {
                    "score": 0.87,
                    "payload": {
                        "product_code": "IMG02",
                        "color": "Nâu",
                        "image_checksum": "second",
                    },
                },
            ]

    class CountingVisionClient:
        def __init__(self):
            self.calls = 0

        async def analyze(self, *, data: bytes, media_type: str):
            self.calls += 1
            return ProductVisionAnalysis(
                product_detected=True,
                category="unknown",
                label="Sản phẩm",
                bounding_box=None,
                confidence=0.7,
                description="Hai kết quả gần nhau",
            )

    vision_client = CountingVisionClient()
    service = ProductImageService(
        image_settings().model_copy(
            update={
                "product_vision_enabled": True,
                "product_image_fast_accept_score": 0.88,
                "product_image_fast_accept_margin": 0.08,
            }
        ),
        RecordingEmbedder(),
        CloseScoreQdrant(),
        FakeImageRagClient(),
        vision_client=vision_client,
        image_processor=FakeImageProcessor(),
    )

    await service.search(
        filename="ambiguous-shoe.jpg",
        media_type="image/jpeg",
        data=b"valid-image",
    )

    assert vision_client.calls == 1


@pytest.mark.asyncio
async def test_visual_verification_can_promote_a_better_matching_sku():
    class AmbiguousQdrant:
        async def search(
            self,
            vector,
            *,
            limit,
            score_threshold,
            product_types=None,
        ):
            return [
                {
                    "score": 0.80,
                    "payload": {
                        "product_code": "IMG01",
                        "color": "Đen",
                        "image_checksum": "first",
                    },
                },
                {
                    "score": 0.79,
                    "payload": {
                        "product_code": "IMG02",
                        "color": "Nâu",
                        "image_checksum": "second",
                    },
                },
            ]

    class FakeDownloader:
        def __init__(self):
            self.calls = 0

        async def download(self, url: str):
            self.calls += 1
            return DownloadedProductImage(
                data=f"reference-{self.calls}".encode(),
                media_type="image/jpeg",
            )

    class FakeVisualVerifier:
        def __init__(self):
            self.calls = 0

        async def verify(self, *, query_data, query_media_type, candidates):
            self.calls += 1
            assert query_data == b"cropped-image"
            assert query_media_type == "image/jpeg"
            assert {item.product_code for item in candidates} == {
                "IMG01",
                "IMG02",
            }
            return [
                ProductVisualMatch("IMG01", 0.20, "Khác kiểu dáng"),
                ProductVisualMatch("IMG02", 0.99, "Khớp kiểu dáng"),
            ]

    downloader = FakeDownloader()
    verifier = FakeVisualVerifier()
    service = ProductImageService(
        image_settings().model_copy(
            update={
                "product_vision_enabled": True,
                "product_visual_verification_enabled": True,
                "product_image_fast_accept_score": 0.99,
                "product_vision_verify_top_k": 2,
            }
        ),
        RecordingEmbedder(),
        AmbiguousQdrant(),
        FakeImageRagClient(),
        vision_client=FakeVisionClient(),
        image_processor=FakeImageProcessor(),
        category_mapping={"shoe": []},
        visual_verifier=verifier,
        image_downloader=downloader,
        decision_engine=ProductImageDecisionEngine(
            vector_weight=0.55,
            visual_weight=0.45,
            verify_min_score=0.65,
            high_confidence=0.82,
            medium_confidence=0.65,
        ),
    )

    result = await service.search(
        filename="ambiguous.jpg",
        media_type="image/jpeg",
        data=b"valid-image",
    )

    assert verifier.calls == 1
    assert downloader.calls == 2
    assert result.products[0].product_code == "IMG02"
    assert result.best_similarity == pytest.approx(0.88, abs=0.001)
    assert result.low_confidence is False


@pytest.mark.asyncio
async def test_visual_verification_keeps_a_matching_candidate_from_original_image():
    """A correct SKU from the original image must survive crop re-ranking."""

    class OriginalThenRefinedQdrant:
        def __init__(self):
            self.calls = 0

        async def search(
            self,
            vector,
            *,
            limit,
            score_threshold,
            product_types=None,
        ):
            self.calls += 1
            if self.calls == 1:
                return [
                    {
                        "score": 0.515,
                        "payload": {
                            "product_code": "PQT",
                            "product_type": "QUA TANG (GIFT)",
                        },
                    },
                    {
                        "score": 0.485,
                        "payload": {
                            "product_code": "G5876",
                            "product_type": "GIAY TAY (MGT)",
                        },
                    },
                    {
                        "score": 0.475,
                        "payload": {
                            "product_code": "DHLN2",
                            "product_type": "DEP CAO GOT (WDC)",
                        },
                    },
                ]

            return [
                {
                    "score": score,
                    "payload": {
                        "product_code": code,
                        "product_type": "GIAY CASUAL (WCA)",
                    },
                }
                for code, score in (
                    ("G5832", 0.713),
                    ("G81T3", 0.709),
                    ("G81R7", 0.701),
                    ("G81T6", 0.696),
                    ("GTP04", 0.682),
                )
            ]

    class FakeDownloader:
        async def download(self, url: str):
            return DownloadedProductImage(
                data=url.encode(),
                media_type="image/jpeg",
            )

    class CorrectSkuVerifier:
        async def verify(self, *, query_data, query_media_type, candidates):
            candidate_codes = [item.product_code for item in candidates]
            assert "G5876" in candidate_codes
            assert "PQT" not in candidate_codes
            return [
                ProductVisualMatch(
                    item.product_code,
                    0.99 if item.product_code == "G5876" else 0.20,
                    "Khớp" if item.product_code == "G5876" else "Khác",
                )
                for item in candidates
            ]

    service = ProductImageService(
        image_settings().model_copy(
            update={
                "product_vision_enabled": True,
                "product_visual_verification_enabled": True,
                "product_image_fast_accept_score": 0.99,
                "product_vision_verify_top_k": 5,
                "product_vision_original_candidate_slots": 2,
            }
        ),
        RecordingEmbedder(),
        OriginalThenRefinedQdrant(),
        FakeImageRagClient(),
        vision_client=FakeVisionClient(),
        image_processor=FakeImageProcessor(),
        category_mapping={
            "shoe": ["GIAY TAY (MGT)", "GIAY CASUAL (WCA)"],
        },
        visual_verifier=CorrectSkuVerifier(),
        image_downloader=FakeDownloader(),
        decision_engine=ProductImageDecisionEngine(
            vector_weight=0.55,
            visual_weight=0.45,
            verify_min_score=0.65,
            high_confidence=0.82,
            medium_confidence=0.65,
        ),
    )

    result = await service.search(
        filename="G5876_2.jpg",
        media_type="image/jpeg",
        data=b"valid-image",
    )

    assert result.products[0].product_code == "G5876"
    assert result.low_confidence is False


def test_product_category_mapping_covers_all_supported_vision_categories():
    mapping = load_product_category_mapping()

    assert set(mapping) == {
        "shoe",
        "sandal",
        "slipper",
        "bag",
        "wallet",
        "belt",
        "accessory",
        "unknown",
    }
    assert mapping["shoe"]
    assert mapping["unknown"] == ()


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


@pytest.mark.asyncio
async def test_qdrant_image_client_filters_by_product_types():
    def handler(request: httpx.Request):
        payload = __import__("json").loads(request.content)
        assert payload["filter"] == {
            "must": [
                {
                    "key": "product_type",
                    "match": {
                        "any": ["GIAY TAY (MGT)", "GIAY THE THAO (MTT)"]
                    },
                }
            ]
        }
        return httpx.Response(200, json={"status": "ok", "result": {"points": []}})

    async_client = httpx.AsyncClient(
        base_url="http://qdrant.test",
        transport=httpx.MockTransport(handler),
    )
    client = QdrantImageClient(
        base_url="http://qdrant.test",
        collection="images-v2",
        api_key=None,
        client=async_client,
    )

    result = await client.search(
        [0.1] * 512,
        limit=10,
        product_types=[
            "GIAY TAY (MGT)",
            "GIAY THE THAO (MTT)",
            "GIAY TAY (MGT)",
        ],
    )

    await async_client.aclose()
    assert result == []
