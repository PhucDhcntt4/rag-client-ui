import httpx
import pytest

from app.clients.llm_client import LlmClient
from app.config import get_settings


@pytest.mark.asyncio
async def test_gemini_keeps_v1beta_base_path():
    def handler(request: httpx.Request):
        assert request.url.path == (
            "/v1beta/models/gemini-3.5-flash-lite:generateContent"
        )
        assert request.headers["x-goog-api-key"]
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "Câu trả lời [S1]."}]}}
                ]
            },
        )

    settings = get_settings().model_copy(
        update={
            "llm_provider": "gemini",
            "llm_base_url": "https://generativelanguage.googleapis.com/v1beta",
            "llm_model": "gemini-3.5-flash-lite",
        }
    )
    async_client = httpx.AsyncClient(
        base_url=settings.llm_base_url,
        transport=httpx.MockTransport(handler),
    )
    client = LlmClient(settings, client=async_client)
    answer = await client.generate_answer(
        system_prompt="Chỉ trả lời từ dữ liệu.",
        query="Câu hỏi",
        history=[],
        context="Ngữ cảnh",
        sources=[
            {"citation": "S1", "title": "Tài liệu", "heading": "Mục 1"}
        ],
    )
    await async_client.aclose()
    assert answer == "Câu trả lời [S1]."


@pytest.mark.asyncio
async def test_openai_compatible_keeps_v1_base_path():
    def handler(request: httpx.Request):
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Kết quả"}}]},
        )

    settings = get_settings().model_copy(
        update={
            "llm_provider": "openai_compatible",
            "llm_base_url": "http://llm.test/v1",
            "llm_model": "local-model",
        }
    )
    async_client = httpx.AsyncClient(
        base_url=settings.llm_base_url,
        transport=httpx.MockTransport(handler),
    )
    client = LlmClient(settings, client=async_client)
    answer = await client.generate_answer(
        system_prompt="Chỉ trả lời từ dữ liệu.",
        query="Câu hỏi",
        history=[],
        context="Ngữ cảnh",
        sources=[],
    )
    await async_client.aclose()
    assert answer == "Kết quả"
