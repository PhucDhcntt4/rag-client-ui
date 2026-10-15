"""Client for OpenAI or Gemini with automatic provider fallback."""

from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import quote

import httpx

from app.config import AiProvider, AiProviderConfig, Settings


class LlmServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class LlmAnswer:
    text: str
    provider: AiProvider
    model: str


OPENAI_CITATION_INSTRUCTIONS = """
QUY TẮC HIỂN THỊ NGUỒN RIÊNG CHO OPENAI:
- Đặt nhãn [Sx] ngay sau câu, ý hoặc dòng bảng mà nguồn đó chứng minh.
- Không gom toàn bộ nhãn nguồn thành một chuỗi ở cuối câu trả lời.
- Không hiển thị nhãn của nguồn không thực sự được dùng trong nội dung.
- Nếu nhiều nguồn cùng chứng minh một ý, đặt các nhãn riêng ngay sau ý đó,
  ví dụ: [S2] [S4]. Không viết [S2, S4].
- Với bảng, đặt nguồn trong cột "Nguồn" hoặc đặt các nhãn áp dụng ngay sau bảng.
""".strip()

OPENAI_BULK_CITATIONS = re.compile(
    r"(?:[ \t]*\[S\d+\]){6,}(?=[ \t]*[.!?]?(?:\n|$))",
    flags=re.IGNORECASE,
)


def clean_openai_citations(answer: str) -> str:
    """Remove citation dumps without changing the generated answer content."""
    return OPENAI_BULK_CITATIONS.sub("", answer).strip()


class LlmClient:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ):
        self.settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=10.0),
            follow_redirects=False,
            headers={"Accept": "application/json"},
        )

    @staticmethod
    def _detail(body: Any, status_code: int) -> str:
        if isinstance(body, dict):
            detail = body.get("detail") or body.get("error")
            if isinstance(detail, str):
                return detail
            if isinstance(detail, dict) and isinstance(detail.get("message"), str):
                return detail["message"]
        return f"LLM trả lỗi HTTP {status_code}"

    async def _post(self, path: str, **kwargs) -> dict:
        try:
            response = await self._client.post(path, **kwargs)
        except httpx.TimeoutException as exc:
            raise LlmServiceError("LLM phản hồi quá thời gian") from exc
        except httpx.RequestError as exc:
            raise LlmServiceError("Không thể kết nối LLM") from exc

        try:
            body = response.json()
        except ValueError:
            body = None

        if not response.is_success:
            raise LlmServiceError(self._detail(body, response.status_code))
        if not isinstance(body, dict):
            raise LlmServiceError("LLM trả dữ liệu JSON không hợp lệ")
        return body

    async def generate_answer(
        self,
        *,
        system_prompt: str,
        query: str,
        history: list[dict[str, str]],
        context: str,
        sources: list[dict],
        provider: AiProvider | None = None,
    ) -> LlmAnswer:
        source_catalog_lines = []
        for source in sources:
            location = [
                str(part).strip()
                for part in source.get("section_path", [])
                if str(part).strip()
            ]
            heading = str(source.get("heading") or "").strip()
            if heading and (not location or location[-1] != heading):
                location.append(heading)
            nearest_section = heading or (location[-1] if location else "")
            location_text = " > ".join(location) if location else "Không xác định"
            source_catalog_lines.append(
                f"[{source['citation']}] {source['title']} | "
                f"MỤC GẦN NHẤT: {nearest_section or 'Không xác định'} | "
                f"ĐƯỜNG DẪN: {location_text}"
            )
        source_catalog = "\n".join(source_catalog_lines)
        user_prompt = (
            f"CÂU HỎI:\n{query}\n\n"
            f"NGỮ CẢNH TRUY XUẤT:\n{context}\n\n"
            f"DANH SÁCH NGUỒN VÀ ĐƯỜNG DẪN PHÂN CẤP:\n"
            f"{source_catalog or 'Không có nguồn'}\n\n"
            "YÊU CẦU BAO PHỦ NGUỒN:\n"
            "- Đọc toàn bộ nguồn trước khi soạn câu trả lời.\n"
            "- Phân loại nguồn thành trực tiếp, hỗ trợ và lân cận. Dùng mọi nguồn trực tiếp, "
            "chỉ dùng nguồn hỗ trợ khi cần và bỏ nguồn lân cận.\n"
            "- Xác định phạm vi chủ yếu bằng MỤC GẦN NHẤT. Nếu mục gần nhất khớp chủ đề được "
            "hỏi, mọi chunk có dữ liệu hoặc dòng bảng riêng biệt trong mục đó đều là nguồn trực "
            "tiếp và phải được sử dụng.\n"
            "- Với mỗi nguồn trực tiếp hoặc nguồn hỗ trợ có thông tin riêng biệt, câu trả lời "
            "cuối cùng phải nêu ít nhất một ý chính từ nguồn đó và đặt nhãn [Sx] ngay sau ý. "
            "Nếu nhiều nguồn cùng chứng minh một ý, gộp thành một ý súc tích và dẫn đủ các "
            "nhãn nguồn, không lặp lại nội dung.\n"
            "- Cùng chương hoặc cùng mục cha không có nghĩa là cùng phạm vi câu hỏi. Không kéo "
            "các mục anh em vào câu trả lời nếu chúng nói về chủ đề khác.\n"
            "- Nếu bảng bị chia qua nhiều nguồn, ghép lại thành bảng Markdown và dẫn đúng "
            "nguồn cho từng dòng hoặc cho toàn bảng.\n"
            "- Câu hỏi tổng quát chỉ yêu cầu tổng quan đầy đủ về đúng chủ đề được nêu, không phải "
            "toàn bộ chương chứa chủ đề đó.\n"
            "- Trước khi kết thúc, vừa kiểm tra nguồn trực tiếp hoặc bảng còn bị bỏ sót, vừa loại "
            "nội dung vượt ngoài phạm vi câu hỏi."
        )

        errors: list[str] = []
        provider_chain = [provider] if provider else self.settings.ai_provider_chain()
        for provider_name in provider_chain:
            try:
                config = self.settings.get_ai_provider_config(provider_name)
                provider_user_prompt = user_prompt
                if config.provider == "openai":
                    provider_user_prompt = (
                        f"{user_prompt}\n\n{OPENAI_CITATION_INSTRUCTIONS}"
                    )
                if config.provider == "gemini":
                    answer = await self._generate_gemini(
                        config=config,
                        system_prompt=system_prompt,
                        user_prompt=provider_user_prompt,
                        history=history,
                    )
                else:
                    answer = await self._generate_openai(
                        config=config,
                        system_prompt=system_prompt,
                        user_prompt=provider_user_prompt,
                        history=history,
                    )
                    answer = clean_openai_citations(answer)
                return LlmAnswer(
                    text=answer,
                    provider=config.provider,
                    model=config.model,
                )
            except (ValueError, LlmServiceError) as exc:
                errors.append(f"{provider_name}: {exc}")

        raise LlmServiceError(
            "Không provider AI nào trả lời thành công. " + " | ".join(errors)
        )

    async def _generate_openai(
        self,
        *,
        config: AiProviderConfig,
        system_prompt: str,
        user_prompt: str,
        history: list[dict[str, str]],
    ) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_prompt})
        body = await self._post(
            f"{config.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {config.api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.model,
                "messages": messages,
                "temperature": 0.2,
            },
        )
        try:
            answer = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmServiceError("Response LLM không đúng định dạng") from exc
        if not isinstance(answer, str) or not answer.strip():
            raise LlmServiceError("LLM trả câu trả lời rỗng")
        return answer.strip()

    async def _generate_gemini(
        self,
        *,
        config: AiProviderConfig,
        system_prompt: str,
        user_prompt: str,
        history: list[dict[str, str]],
    ) -> str:
        contents = [
            {
                "role": "model" if item["role"] == "assistant" else "user",
                "parts": [{"text": item["content"]}],
            }
            for item in history
        ]
        contents.append({"role": "user", "parts": [{"text": user_prompt}]})
        model = quote(config.model, safe="-._")
        body = await self._post(
            f"{config.base_url}/models/{model}:generateContent",
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": config.api_key.get_secret_value(),
            },
            json={
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": contents,
                "generationConfig": {"temperature": 0.2},
            },
        )
        try:
            parts = body["candidates"][0]["content"]["parts"]
            answer = "".join(
                part.get("text", "") for part in parts if isinstance(part, dict)
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmServiceError("Response Gemini không đúng định dạng") from exc
        if not answer.strip():
            raise LlmServiceError("Gemini trả câu trả lời rỗng")
        return answer.strip()

    async def close(self):
        if self._owns_client:
            await self._client.aclose()
