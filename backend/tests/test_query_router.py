import pytest

from app.schemas import ChatMessage
from app.services.query_router import detect_data_source


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Quy định về thời gian làm việc?", "documents"),
        ("Chính sách bảo hành sản phẩm?", "documents"),
        ("G5876 còn size 39 không?", "products"),
        ("Các sản phẩm mới trong tháng này?", "products"),
        ("Sản phẩm nào đang hết hàng?", "products"),
        ("cac san pham con hang hien tai", "products"),
        ("Văn hóa công ty như thế nào?", "documents"),
        ("Cho tôi biết về ABC", "documents"),
    ],
)
def test_detect_data_source(query, expected):
    assert detect_data_source(query) == expected


def test_document_scope_forces_document_search():
    assert (
        detect_data_source(
            "G5876 còn hàng không?",
            has_document_scope=True,
        )
        == "documents"
    )


def test_product_follow_up_uses_recent_assistant_context():
    history = [
        ChatMessage(
            role="assistant",
            content="Mã sản phẩm G5876, tổng tồn kho 12.",
        )
    ]

    assert detect_data_source("Còn màu khác không?", history) == "products"
