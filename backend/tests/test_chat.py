import pytest

from app.config import get_settings
from app.schemas import ChatRequest
from app.services.chat_service import ChatService, limit_retrieval


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
        return "Thời hạn đổi trả là 7 ngày [S1]."


@pytest.mark.asyncio
async def test_chat_returns_grounded_sources():
    service = ChatService(get_settings(), FakeRagClient(), FakeLlmClient())
    result = await service.answer(ChatRequest(query="Đổi trả bao lâu?"))
    assert result.status == "answered"
    assert result.sources[0].citation == "S1"
    assert result.sources[0].section_path == ["Chính sách", "Đổi trả"]
    assert result.sources[0].assets[0].url == "/api/rag-assets/8"
    assert result.retrieved_content == "Đổi trả trong 7 ngày."
    assert "[S1]" in result.answer


def test_limit_retrieval_numbers_and_limits_expanded_sections():
    retrieval = {
        "sources": [{"source_key": str(index)} for index in range(1, 5)],
        "content": "\n\n".join(
            f"[Nguồn: Tài liệu {index}] Nội dung {index}"
            for index in range(1, 5)
        ),
    }

    sources, content = limit_retrieval(retrieval, 2)

    assert len(sources) == 2
    assert content.count("[Nguồn:") == 2
    assert content.startswith("[S1] [Nguồn:")
    assert "[S2] [Nguồn:" in content
    assert "Nội dung 3" not in content
