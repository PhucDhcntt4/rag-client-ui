import httpx
import pytest
from pydantic import SecretStr

from app.clients.llm_client import LlmClient
from app.config import get_settings


@pytest.mark.asyncio
async def test_uses_fallback_provider_when_primary_provider_fails():
    calls: list[str] = []

    def handler(request: httpx.Request):
        calls.append(request.url.host or "")
        if request.url.host == "gemini.test":
            return httpx.Response(503, json={"error": {"message": "Unavailable"}})
        assert request.url.host == "openai.test"
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Fallback OK"}}]},
        )

    settings = get_settings().model_copy(
        update={
            "ai_provider": "gemini",
            "ai_fallback_provider": "openai",
            "gemini_base_url": "https://gemini.test/v1beta",
            "gemini_api_key": SecretStr("gemini-key"),
            "gemini_model": "gemini-model",
            "openai_base_url": "https://openai.test/v1",
            "openai_api_key": SecretStr("openai-key"),
            "openai_model": "openai-model",
        }
    )
    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = LlmClient(settings, client=async_client)
    answer = await client.generate_answer(
        system_prompt="System",
        query="Question",
        history=[],
        context="Context",
        sources=[],
    )
    await async_client.aclose()

    assert calls == ["gemini.test", "openai.test"]
    assert answer.text == "Fallback OK"
    assert answer.provider == "openai"
    assert answer.model == "openai-model"
