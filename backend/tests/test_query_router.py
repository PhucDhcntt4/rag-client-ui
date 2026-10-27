import pytest

from app.schemas import ChatMessage
from app.services.query_router import detect_data_source, resolve_product_query


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


def test_three_turn_product_follow_up_then_document_topic_switch():
    product_history = [
        ChatMessage(
            role="user",
            content="Cho tôi thông tin mã sản phẩm G5876",
        ),
        ChatMessage(
            role="assistant",
            content="Mã sản phẩm G5876, tổng tồn kho 12.",
        ),
    ]

    assert (
        detect_data_source(product_history[0].content)
        == "products"
    )
    assert detect_data_source("màu đen", product_history) == "products"
    assert (
        resolve_product_query("màu đen", product_history)
        == "G5876 màu đen"
    )

    full_history = [
        *product_history,
        ChatMessage(role="user", content="màu đen"),
        ChatMessage(
            role="assistant",
            content="Sản phẩm G5876 có biến thể màu đen.",
        ),
    ]
    assert detect_data_source("danh sách quản lý", full_history) == "documents"


def test_new_product_request_does_not_inherit_previous_sku():
    history = [
        ChatMessage(role="user", content="Thông tin G5876"),
        ChatMessage(role="assistant", content="Mã sản phẩm G5876."),
    ]

    assert (
        resolve_product_query("Các sản phẩm mới trong tháng", history)
        == "Các sản phẩm mới trong tháng"
    )
