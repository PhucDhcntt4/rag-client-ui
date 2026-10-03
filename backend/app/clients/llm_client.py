"""Client for an OpenAI-compatible or Gemini generate-content endpoint."""

from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings


class LlmServiceError(RuntimeError):
    pass


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
            base_url=settings.llm_base_url,
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
    ) -> str:
        source_catalog = "\n".join(
            f"[{source['citation']}] {source['title']}"
            + (f" > {source['heading']}" if source.get("heading") else "")
            for source in sources
        )
        user_prompt = (
            f"CÂU HỎI:\n{query}\n\n"
            f"NGỮ CẢNH TRUY XUẤT:\n{context}\n\n"
            f"DANH SÁCH NGUỒN:\n{source_catalog or 'Không có nguồn'}"
        )

        if self.settings.llm_provider == "gemini":
            return await self._generate_gemini(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                history=history,
            )
        return await self._generate_openai_compatible(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            history=history,
        )

    async def _generate_openai_compatible(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        history: list[dict[str, str]],
    ) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_prompt})
        body = await self._post(
            "chat/completions",
            headers={
                "Authorization": (
                    f"Bearer {self.settings.llm_api_key.get_secret_value()}"
                ),
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.llm_model,
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
        model = quote(self.settings.llm_model, safe="-._")
        body = await self._post(
            f"models/{model}:generateContent",
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.settings.llm_api_key.get_secret_value(),
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
