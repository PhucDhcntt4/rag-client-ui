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
    "danh sách quản lý",
    "ban quản lý",
    "quản lý",
    "danh sách nhân viên",
    "cơ cấu tổ chức",
    "sơ đồ tổ chức",
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

PRODUCT_FOLLOW_UP_KEYWORDS = (
    "màu",
    "size",
    "kích thước",
    "giá",
    "bao nhiêu tiền",
    "còn hàng",
    "hết hàng",
    "tồn kho",
    "còn bao nhiêu",
    "hình ảnh",
    "ảnh",
    "link",
    "biến thể",
    "sản phẩm đó",
    "mẫu đó",
    "cái đó",
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


def _latest_product_identifier(
    history: Sequence[ChatMessage] | None,
) -> str | None:
    """Prefer a SKU explicitly written by the user, then assistant output."""

    recent = list(reversed(history or ()))
    for role in ("user", "assistant"):
        for message in recent:
            if message.role != role:
                continue
            match = SKU_PATTERN.search(message.content)
            if match:
                return match.group(0).upper()
    return None


def resolve_product_query(
    query: str,
    history: Sequence[ChatMessage] | None = None,
) -> str:
    """Attach the recent SKU only when ``query`` is a product follow-up."""

    if SKU_PATTERN.search(query):
        return query

    normalized = _fold_text(query).strip()
    is_follow_up = any(
        _fold_text(keyword) in normalized
        for keyword in PRODUCT_FOLLOW_UP_KEYWORDS
    )
    if not is_follow_up:
        return query

    identifier = _latest_product_identifier(history)
    return f"{identifier} {query}" if identifier else query


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
