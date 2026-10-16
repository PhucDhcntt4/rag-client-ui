import pytest
from datetime import UTC, datetime

from app.clients.llm_client import LlmAnswer
from app.config import get_settings
from app.schemas import ChatRequest
from app.services.chat_service import ChatService
from app.services.product_service import ProductService, build_product_context


def make_product_service(rag_client) -> ProductService:
    settings = get_settings()
    return ProductService(
        rag_client,
        product_timezone=settings.product_timezone,
        chat_page_size=settings.product_chat_page_size,
        candidate_page_size=settings.product_candidate_page_size,
    )


class FakeProductRagClient:
    async def get_product(self, product_code: str):
        assert product_code == "S5921"
        return {
            "product": {
                "product_code": "S5921",
                "title": "Giày nam S5921",
                "product_type": "Giày nam",
                "status": "ACTIVE",
                "inventory_synced_at": "2026-10-15T09:00:00+00:00",
                "public_info": {
                    "image_urls": ["https://example.test/S5921.png"],
                },
                "detail": {
                    "product": {
                        "online_store_url": "https://example.test/S5921",
                    }
                },
                "variants": [
                    {
                        "sku": "S5921-DEN-40",
                        "variant_title": "Đen / 40",
                        "color": "Đen",
                        "size": "40",
                        "price": 1200000,
                        "inventory_quantity": 3,
                        "available": True,
                    }
                ],
            }
        }


class FakeProductLlmClient:
    async def generate_answer(self, **kwargs):
        assert "S5921-DEN-40" in kwargs["context"]
        assert "Số lượng tồn" in kwargs["context"]
        assert "[S1]" not in kwargs["context"]
        assert kwargs["sources"] == []
        return LlmAnswer(
            text="S5921 màu đen size 40 còn 3 sản phẩm.",
            provider="openai",
            model="test-model",
        )


@pytest.mark.asyncio
async def test_product_chat_uses_catalog_inventory_and_llm():
    service = ChatService(
        get_settings(),
        FakeProductRagClient(),
        FakeProductLlmClient(),
    )
    result = await service.answer(
        ChatRequest(
            query="S5921 màu đen size 40 còn hàng không?",
            data_source="auto",
            ai_provider="openai",
        )
    )

    assert result.status == "answered"
    assert result.data_source == "products"
    assert result.sources == []
    assert result.product_sources[0].product_code == "S5921"
    assert result.product_sources[0].variants[0].inventory_quantity == 3
    assert result.product_result is not None
    assert result.product_result.shown == 1
    assert "[S1]" not in result.answer


def product_detail(
    code: str,
    *,
    quantity: int,
    new_at: str,
    product_type: str = "Giày nam",
):
    return {
        "product": {
            "product_code": code,
            "title": f"Sản phẩm {code}",
            "product_type": product_type,
            "vendor": "Đông Hải",
            "status": "ACTIVE",
                "description": f"Mô tả {code}",
                "material": "Da",
                "sole": "Cao su",
                "height": "3 cm",
                "aliases": [
                    {"alias_type": "legacy", "alias": f"OLD-{code}"},
                ],
                "attributes": [
                    {"attribute_key": "Phong cách", "attribute_value": "Công sở"},
                ],
            "new_at": new_at,
            "inventory_synced_at": "2026-10-15T09:00:00+00:00",
            "variants": [
                {
                    "sku": f"{code}-40",
                    "barcode": f"BAR-{code}-40",
                    "color": "Đen",
                    "size": "40",
                    "price": 1200000,
                    "compare_at_price": 1400000,
                    "inventory_quantity": quantity,
                    "available": quantity > 0,
                }
            ],
        }
    }


class FakeCatalogRagClient:
    def __init__(self):
        self.details = {
            "NEW02": product_detail(
                "NEW02", quantity=4, new_at="2026-10-15T08:00:00Z"
            ),
            "NEW01": product_detail(
                "NEW01", quantity=0, new_at="2026-10-14T08:00:00Z"
            ),
            "OLD01": product_detail(
                "OLD01", quantity=2, new_at="2026-09-01T08:00:00Z"
            ),
        }
        self.latest_calls = 0

    async def list_latest_products(
        self,
        *,
        product_type=None,
        page=1,
        limit=10,
        date_from=None,
        date_to=None,
    ):
        self.latest_calls += 1
        rows = [
            {"product_code": "NEW02"},
            {"product_code": "NEW01"},
            {"product_code": "OLD01"},
        ]
        if date_from and date_to:
            start = datetime.fromisoformat(date_from)
            end = datetime.fromisoformat(date_to)
            rows = [
                row for row in rows
                if start <= datetime.fromisoformat(
                    self.details[row["product_code"]]["product"]["new_at"]
                    .replace("Z", "+00:00")
                ) < end
            ]
        start_index = (page - 1) * limit
        page_rows = rows[start_index:start_index + limit]
        total_pages = (len(rows) + limit - 1) // limit if rows else 0
        return {
            "products": page_rows,
            "total": len(rows),
            "total_pages": total_pages,
        }

    async def list_products(
        self, *, query=None, product_type=None, status="ACTIVE", page=1, limit=20
    ):
        return {
            "products": [
                {"product_code": "NEW02"},
                {"product_code": "NEW01"},
                {"product_code": "OLD01"},
            ],
            "page": 1,
            "total_pages": 1,
        }

    async def get_product(self, product_code: str):
        return self.details[product_code]


class FakeSkuRagClient(FakeCatalogRagClient):
    async def get_product(self, product_code: str):
        return self.details.get(product_code)


@pytest.mark.asyncio
async def test_latest_product_question_uses_latest_endpoint_and_keeps_order():
    rag = FakeCatalogRagClient()
    result = await make_product_service(rag).search_for_question(
        "Các sản phẩm mới hiện tại là gì?"
    )
    products = result.products

    assert rag.latest_calls == 1
    assert [item.product_code for item in products] == [
        "NEW02",
        "NEW01",
        "OLD01",
    ]
    assert products[0].new_at == "2026-10-15T08:00:00Z"


@pytest.mark.asyncio
async def test_latest_products_this_month_use_date_filter_not_name_keywords(
    monkeypatch,
):
    monkeypatch.setattr(
        ProductService,
        "_new_date_period",
        staticmethod(
            lambda query: (
                datetime(2026, 10, 1, tzinfo=UTC),
                datetime(2026, 11, 1, tzinfo=UTC),
            )
        ),
    )

    result = await make_product_service(
        FakeCatalogRagClient()
    ).search_for_question(
        "Sản phẩm mới trong tháng này"
    )
    products = result.products

    assert [item.product_code for item in products] == ["NEW02", "NEW01"]
    assert result.result.total == 2


@pytest.mark.asyncio
async def test_latest_page_returns_dynamic_pagination_metadata():
    result = await make_product_service(
        FakeCatalogRagClient()
    ).list_latest_page(page=2, limit=1)

    assert [item.product_code for item in result.products] == ["NEW01"]
    assert result.products[0].citation == "S2"
    assert result.result.total == 3
    assert result.result.total_pages == 3
    assert result.result.has_more is True


@pytest.mark.asyncio
async def test_sku_resolves_parent_product_and_builds_full_context():
    service = make_product_service(FakeSkuRagClient())
    result = await service.search_for_question(
        "Cho tôi thông tin đầy đủ SKU NEW02-40"
    )

    assert [item.product_code for item in result.products] == ["NEW02"]
    context = build_product_context(
        result.products,
        "Cho tôi thông tin đầy đủ SKU NEW02-40",
        result.result,
    )
    assert "tra cứu đầy đủ một sản phẩm theo mã hoặc SKU" in context
    assert "Mô tả NEW02" in context
    assert "Chất liệu: Da" in context
    assert "OLD-NEW02" in context
    assert "Phong cách: Công sở" in context
    assert "BAR-NEW02-40" in context
    assert "1.400.000 đ" in context
    assert "Tồn kho cập nhật lúc" in context
    assert "[S1]" not in context
    assert "http" not in context
    assert "Không có dữ liệu" not in context


def test_full_product_context_omits_empty_fields():
    source = ProductService._to_source(
        {
            "product": {
                "product_code": "EMPTY01",
                "title": "Sản phẩm EMPTY01",
                "status": "ACTIVE",
                "variants": [],
            }
        },
        "S1",
    )

    context = build_product_context(
        [source],
        "Thông tin SKU EMPTY01",
    )

    assert "Chiều cao:" not in context
    assert "Chất liệu:" not in context
    assert "Trang sản phẩm:" not in context
    assert "Hình ảnh:" not in context
    assert "Không có dữ liệu" not in context


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "expected_code", "expected_status"),
    [
        ("Các sản phẩm còn hàng", "NEW02", "in_stock"),
        ("Các sản phẩm hết hàng", "NEW01", "out_of_stock"),
    ],
)
async def test_generic_inventory_questions_are_filtered(
    question,
    expected_code,
    expected_status,
):
    result = await make_product_service(
        FakeCatalogRagClient()
    ).search_for_question(
        question
    )
    products = result.products

    assert products
    assert all(item.inventory_status == expected_status for item in products)
    assert expected_code in {item.product_code for item in products}


def test_product_context_contains_detected_intent_dates_and_inventory():
    source = ProductService._to_source(
        product_detail(
            "NEW02", quantity=4, new_at="2026-10-15T08:00:00Z"
        ),
        "S1",
    )

    context = build_product_context(
        [source],
        "Sản phẩm mới còn hàng",
    )

    assert "sản phẩm mới nhất" in context
    assert "chỉ sản phẩm còn hàng" in context
    assert "2026-10-15T08:00:00Z" in context
    assert "Tổng tồn kho: 4" in context


def test_latest_only_context_does_not_include_inventory_timestamp():
    source = ProductService._to_source(
        product_detail(
            "NEW02", quantity=4, new_at="2026-10-15T08:00:00Z"
        ),
        "S1",
    )

    context = build_product_context(
        [source],
        "Các sản phẩm mới hiện tại là gì?",
    )

    assert "Ngày sản phẩm mới: 2026-10-15T08:00:00Z" in context
    assert "Tồn kho cập nhật lúc" not in context
    assert "Trạng thái tồn kho" not in context
    assert "Số lượng tồn" not in context
