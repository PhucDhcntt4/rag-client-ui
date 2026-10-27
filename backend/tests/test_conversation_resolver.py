import pytest

from app.clients.llm_client import LlmAnswer
from app.schemas import ChatMessage
from app.services.conversation_resolver import (
    load_conversation_prompt,
    resolve_conversation_query,
)


class FakeContextLlm:
    def __init__(self, response: str):
        self.response = response
        self.calls = []

    async def generate_text(self, **kwargs):
        self.calls.append(kwargs)
        return LlmAnswer(
            text=self.response,
            provider="gemini",
            model="test-model",
        )


def product_history():
    return [
        ChatMessage(
            role="user",
            content="Cho tôi thông tin mã sản phẩm G5876",
        ),
        ChatMessage(
            role="assistant",
            content="Mã sản phẩm G5876, tổng tồn kho 12.",
        ),
    ]


@pytest.mark.asyncio
async def test_llm_rewrites_related_product_follow_up():
    llm = FakeContextLlm(
        '{"related":true,"data_source":"products",'
        '"standalone_query":"Thông tin màu đen của G5876"}'
    )

    result = await resolve_conversation_query(
        query="màu đen",
        history=product_history(),
        llm_client=llm,
        provider="gemini",
    )

    assert result.related is True
    assert result.data_source == "products"
    assert result.standalone_query == "Thông tin màu đen của G5876"
    assert result.used_llm is True
    assert llm.calls[0]["temperature"] == 0.0


@pytest.mark.asyncio
async def test_llm_detects_new_document_topic():
    llm = FakeContextLlm(
        '{"related":false,"data_source":"documents",'
        '"standalone_query":"Danh sách quản lý"}'
    )

    result = await resolve_conversation_query(
        query="danh sách quản lý",
        history=product_history(),
        llm_client=llm,
        provider="gemini",
    )

    assert result.related is False
    assert result.data_source == "documents"
    assert result.standalone_query == "Danh sách quản lý"


@pytest.mark.asyncio
async def test_invalid_llm_analysis_uses_deterministic_fallback():
    llm = FakeContextLlm("không phải JSON")

    result = await resolve_conversation_query(
        query="màu đen",
        history=product_history(),
        llm_client=llm,
        provider="gemini",
    )

    assert result.data_source == "products"
    assert result.standalone_query == "G5876 màu đen"
    assert result.used_llm is False


def test_context_prompt_requires_strict_json_and_topic_switching():
    prompt = load_conversation_prompt()

    assert '"standalone_query"' in prompt
    assert '"data_source":"documents"' in prompt
    assert "Không trả lời câu hỏi" in prompt
