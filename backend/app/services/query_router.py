"""Resolve a unified chat question to the appropriate internal data source."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from app.schemas import ChatMessage


DOCUMENT_KEYWORDS = (
    "quy định",
    "chính sách",
    "quy trình",
    "nội quy",
    "sổ tay",
    "hướng dẫn",
    "thời gian làm việc",
    "ngày nghỉ",
    "nghỉ phép",
    "bảo hành",
    "văn hóa công ty",
    "đổi trả",
)

PRODUCT_KEYWORDS = (
    "sản phẩm",
    "mã sản phẩm",
    "sku",
    "giá sản phẩm",
    "bao nhiêu tiền",
    "còn hàng",
    "hết hàng",
    "tồn kho",
    "còn size",
    "kích thước",
    "sản phẩm mới",
    "mẫu mới",
    "link sản phẩm",
    "giày nào",
    "dép nào",
    "túi nào",
    "giá",
    "size",
    "màu",
)

PRODUCT_HISTORY_MARKERS = (
    "mã sản phẩm",
    "tổng tồn kho",
    "biến thể còn hàng",
    "xem sản phẩm",
)

SKU_PATTERN = re.compile(
    r"\b(?=[A-Z0-9-]{4,20}\b)(?=[A-Z0-9-]*[A-Z])"
    r"(?=[A-Z0-9-]*\d)[A-Z0-9-]+\b",
    re.IGNORECASE,
)


def _fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.casefold())
    return "".join(
        character
        for character in normalized.replace("đ", "d")
        if not unicodedata.combining(character)
    )


def detect_data_source(
    query: str,
    history: Sequence[ChatMessage] | None = None,
    *,
    has_document_scope: bool = False,
) -> str:
    """Return ``documents`` or ``products`` without spending an LLM call."""

    normalized = _fold_text(query).strip()

    if has_document_scope:
        return "documents"

    # Document intent has priority so "chính sách bảo hành sản phẩm"
    # is not mistaken for a catalog search.
    if any(_fold_text(keyword) in normalized for keyword in DOCUMENT_KEYWORDS):
        return "documents"

    if SKU_PATTERN.search(query):
        return "products"

    if any(_fold_text(keyword) in normalized for keyword in PRODUCT_KEYWORDS):
        return "products"

    # Preserve product context for short follow-up questions when possible.
    for message in reversed(history or ()):
        if message.role != "assistant":
            continue
        previous = _fold_text(message.content)
        if any(
            _fold_text(marker) in previous
            for marker in PRODUCT_HISTORY_MARKERS
        ):
            return "products"
        break

    return "documents"
