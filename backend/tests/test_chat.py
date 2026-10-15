import pytest

from app.config import get_settings
from app.schemas import ChatRequest
from app.services.chat_service import (
    ChatService,
    load_answer_prompt,
    prepare_retrieval,
)


class FakeRagClient:
    async def search(self, *_args, **_kwargs):
        return {
            "success": True,
            "status": "knowledge_found",
            "content": "Đổi trả trong 7 ngày.",
            "sources": [
                {
                    "source_key": "policy/returns",
                    "title": "Chính sách đổi trả",
                    "category": "returns",
                    "heading": "Thời hạn",
                    "section_path": ["Chính sách", "Đổi trả"],
                    "chunk_index": 0,
                    "similarity": 0.9,
                    "assets": [
                        {
                            "id": 8,
                            "asset_type": "image",
                            "page_number": 5,
                            "width": 720,
                            "height": 480,
                            "bbox": [72, 130, 312, 290],
                            "media_type": "image/png",
                            "url": "/api/v1/knowledge/assets/8",
                            "caption": "Sơ đồ đổi trả",
                        }
                    ],
                }
            ],
            "elapsed_ms": 10.0,
        }


class FakeLlmClient:
    async def generate_answer(self, **kwargs):
        assert "Đổi trả trong 7 ngày" in kwargs["context"]
        assert kwargs["provider"] == "openai"
        return "Thời hạn đổi trả là 7 ngày [S1]."


@pytest.mark.asyncio
async def test_chat_returns_grounded_sources():
    service = ChatService(get_settings(), FakeRagClient(), FakeLlmClient())
    result = await service.answer(
        ChatRequest(query="Đổi trả bao lâu?", ai_provider="openai")
    )
    assert result.status == "answered"
    assert result.sources[0].citation == "S1"
    assert result.sources[0].section_path == ["Chính sách", "Đổi trả"]
    assert result.sources[0].assets[0].url == "/api/rag-assets/8"
    assert result.retrieved_content == "Đổi trả trong 7 ngày."
    assert "[S1]" in result.answer
    assert result.llm_provider == "openai"


def test_prepare_retrieval_numbers_and_keeps_expanded_sections():
    retrieval = {
        "sources": [{"source_key": str(index)} for index in range(1, 5)],
        "content": "\n\n".join(
            f"[Nguồn: Tài liệu {index}] Nội dung {index}"
            for index in range(1, 5)
        ),
    }

    sources, content = prepare_retrieval(retrieval)

    assert len(sources) == 4
    assert content.count("[Nguồn:") == 4
    assert content.startswith("[S1] [Nguồn:")
    assert "[S2] [Nguồn:" in content
    assert "[S4] [Nguồn:" in content
    assert "Nội dung 4" in content


def test_answer_prompt_balances_source_coverage_and_query_scope():
    prompt = load_answer_prompt()

    assert "[S8] [S9]" in prompt
    assert "kiểm tra toàn bộ DANH SÁCH NGUỒN" in prompt
    assert "Phải sử dụng tất cả nguồn trực tiếp" in prompt
    assert "Việc hai nguồn cùng mục cha không đủ" in prompt
    assert "MỤC GẦN NHẤT" in prompt
    assert "một bảng Markdown hoàn chỉnh" in prompt
    assert '"giải thích về X"' in prompt
    assert "không phải về toàn bộ chương chứa X" in prompt
    assert "không tự mở rộng sang nghỉ phép" in prompt
    assert 'hỏi về "đóng tiết kiệm hàng tháng"' in prompt
    assert "loại bỏ nội dung lân cận vượt ngoài câu hỏi" in prompt
