"""Resolve ambiguous follow-up questions before data retrieval."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.clients.llm_client import LlmClient, LlmServiceError
from app.config import AiProvider
from app.schemas import ChatMessage
from app.services.query_router import detect_data_source, resolve_product_query


LOGGER = logging.getLogger(__name__)
PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "prompts"
    / "conversation_query_analysis.txt"
)
CONTEXT_MARKERS = (
    "nó",
    "cái đó",
    "phần đó",
    "mục đó",
    "sản phẩm đó",
    "mẫu đó",
    "quy định trên",
    "thông tin trên",
    "như trên",
    "vậy",
    "thế",
    "còn",
    "tiếp theo",
)


@dataclass(frozen=True)
class ConversationResolution:
    related: bool
    data_source: str
    standalone_query: str
    used_llm: bool = False


def load_conversation_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def should_resolve_context(
    query: str,
    history: list[ChatMessage],
) -> bool:
    if not history:
        return False
    normalized = query.casefold().strip()
    word_count = len(re.findall(r"\w+", normalized, flags=re.UNICODE))
    return word_count <= 12 or any(marker in normalized for marker in CONTEXT_MARKERS)


def _parse_resolution(value: str) -> ConversationResolution:
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("LLM không trả JSON phân tích ngữ cảnh")
    payload = json.loads(text[start:end + 1])
    data_source = str(payload.get("data_source") or "").strip().lower()
    standalone_query = str(payload.get("standalone_query") or "").strip()
    related = payload.get("related")
    if data_source not in {"documents", "products"}:
        raise ValueError("Nguồn dữ liệu phân tích không hợp lệ")
    if not isinstance(related, bool):
        raise ValueError("Trạng thái liên quan không hợp lệ")
    if not standalone_query or len(standalone_query) > 4_000:
        raise ValueError("Câu truy vấn độc lập không hợp lệ")
    return ConversationResolution(
        related=related,
        data_source=data_source,
        standalone_query=standalone_query,
        used_llm=True,
    )


def fallback_resolution(
    query: str,
    history: list[ChatMessage],
    *,
    has_document_scope: bool = False,
) -> ConversationResolution:
    data_source = detect_data_source(
        query,
        history,
        has_document_scope=has_document_scope,
    )
    standalone_query = (
        resolve_product_query(query, history)
        if data_source == "products"
        else query
    )
    return ConversationResolution(
        related=standalone_query != query,
        data_source=data_source,
        standalone_query=standalone_query,
    )


async def resolve_conversation_query(
    *,
    query: str,
    history: list[ChatMessage],
    llm_client: LlmClient,
    provider: AiProvider | None,
    has_document_scope: bool = False,
) -> ConversationResolution:
    fallback = fallback_resolution(
        query,
        history,
        has_document_scope=has_document_scope,
    )
    if has_document_scope or not should_resolve_context(query, history):
        return fallback

    try:
        result = await llm_client.generate_text(
            system_prompt=load_conversation_prompt(),
            user_prompt=f"CÂU HỎI MỚI:\n{query}",
            history=[item.model_dump() for item in history[-12:]],
            provider=provider,
            temperature=0.0,
        )
        resolution = _parse_resolution(result.text)
        LOGGER.debug(
            "Phân tích ngữ cảnh: related=%s, source=%s, rewritten=%s.",
            resolution.related,
            resolution.data_source,
            resolution.standalone_query != query,
        )
        return resolution
    except (LlmServiceError, ValueError, json.JSONDecodeError) as exc:
        LOGGER.warning(
            "Không thể phân tích ngữ cảnh bằng LLM; dùng rule dự phòng: %s",
            exc,
        )
        return fallback
