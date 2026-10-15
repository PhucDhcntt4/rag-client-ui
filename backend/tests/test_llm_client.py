import json

import httpx
import pytest
from pydantic import SecretStr

from app.clients.llm_client import LlmClient, clean_openai_citations
from app.config import get_settings


def test_openai_citation_cleanup_only_removes_bulk_source_dump():
    answer = (
        "Thời gian làm việc là 48 giờ/tuần [S2].\n\n"
        "Nghỉ hàng tuần theo quy định [S5] [S6] [S7].\n\n"
        "Tóm lại, công ty có quy định đầy đủ"
        " [S1] [S2] [S3] [S4] [S5] [S6] [S7] [S8]."
    )

    cleaned = clean_openai_citations(answer)

    assert "48 giờ/tuần [S2]" in cleaned
    assert "[S5] [S6] [S7]" in cleaned
    assert "Tóm lại, công ty có quy định đầy đủ." in cleaned
    assert "[S1] [S2] [S3] [S4] [S5] [S6]" not in cleaned


@pytest.mark.asyncio
async def test_gemini_keeps_v1beta_base_path():
    def handler(request: httpx.Request):
        assert request.url.path == (
            "/v1beta/models/gemini-3.5-flash-lite:generateContent"
        )
        assert request.headers["x-goog-api-key"]
        payload = json.loads(request.content)
        user_prompt = payload["contents"][-1]["parts"][0]["text"]
        assert "DANH SÁCH NGUỒN VÀ ĐƯỜNG DẪN PHÂN CẤP" in user_prompt
        assert "MỤC GẦN NHẤT: 1.4.1. Hạn mức" in user_prompt
        assert "PHẦN III > 1.4. Mức đóng > 1.4.1. Hạn mức" in user_prompt
        assert "Phân loại nguồn thành trực tiếp, hỗ trợ và lân cận" in user_prompt
        assert "mọi chunk có dữ liệu hoặc dòng bảng riêng biệt" in user_prompt
        assert "phải nêu ít nhất một ý chính từ nguồn đó" in user_prompt
        assert "gộp thành một ý súc tích" in user_prompt
        assert "Cùng chương hoặc cùng mục cha không có nghĩa" in user_prompt
        assert "QUY TẮC HIỂN THỊ NGUỒN RIÊNG CHO OPENAI" not in user_prompt
        assert "Nếu bảng bị chia qua nhiều nguồn" in user_prompt
        assert "loại nội dung vượt ngoài phạm vi câu hỏi" in user_prompt
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
            "ai_provider": "gemini",
            "gemini_base_url": "https://generativelanguage.googleapis.com/v1beta",
            "gemini_api_key": SecretStr("test-gemini-key"),
            "gemini_model": "gemini-3.5-flash-lite",
        }
    )
    async_client = httpx.AsyncClient(
        base_url=settings.gemini_base_url,
        transport=httpx.MockTransport(handler),
    )
    client = LlmClient(settings, client=async_client)
    answer = await client.generate_answer(
        system_prompt="Chỉ trả lời từ dữ liệu.",
        query="Câu hỏi",
        history=[],
        context="Ngữ cảnh",
        sources=[
            {
                "citation": "S1",
                "title": "Tài liệu",
                "heading": "1.4.1. Hạn mức",
                "section_path": ["PHẦN III", "1.4. Mức đóng"],
            }
        ],
    )
    await async_client.aclose()
    assert answer.text == "Câu trả lời [S1]."
    assert answer.provider == "gemini"


@pytest.mark.asyncio
async def test_openai_keeps_v1_base_path():
    def handler(request: httpx.Request):
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        user_prompt = payload["messages"][-1]["content"]
        assert "QUY TẮC HIỂN THỊ NGUỒN RIÊNG CHO OPENAI" in user_prompt
        assert "Không gom toàn bộ nhãn nguồn thành một chuỗi" in user_prompt
        assert "Không hiển thị nhãn của nguồn không thực sự được dùng" in user_prompt
        assert 'cột "Nguồn"' in user_prompt
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Kết quả"}}]},
        )

    settings = get_settings().model_copy(
        update={
            "ai_provider": "openai",
            "openai_base_url": "http://llm.test/v1",
            "openai_api_key": SecretStr("test-openai-key"),
            "openai_model": "local-model",
        }
    )
    async_client = httpx.AsyncClient(
        base_url=settings.openai_base_url,
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
    assert answer.text == "Kết quả"
    assert answer.provider == "openai"
