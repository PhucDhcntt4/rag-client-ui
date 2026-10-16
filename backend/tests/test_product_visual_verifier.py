import json

import httpx
import pytest

from app.clients.product_visual_verifier import (
    ProductVisualCandidate,
    ProductVisualVerifier,
    load_product_visual_verification_prompt,
)


def test_visual_verification_prompt_is_available():
    prompt = load_product_visual_verification_prompt()

    assert "visual_score" in prompt
    assert "product_code" in prompt


@pytest.mark.asyncio
async def test_visual_verifier_sends_all_images_and_rejects_unknown_codes():
    def handler(request: httpx.Request):
        assert request.url.path.endswith("/models/gemini-test:generateContent")
        assert request.headers["x-goog-api-key"] == "secret"
        payload = json.loads(request.content)
        parts = payload["contents"][0]["parts"]
        inline_images = [part for part in parts if "inlineData" in part]
        assert len(inline_images) == 3
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "matches": [
                                                {
                                                    "product_code": "SKU01",
                                                    "visual_score": 0.81,
                                                    "reason": "Cùng kiểu dáng",
                                                },
                                                {
                                                    "product_code": "SKU01",
                                                    "visual_score": 0.92,
                                                    "reason": "Khớp chi tiết",
                                                },
                                                {
                                                    "product_code": "SKU02",
                                                    "visual_score": 0.75,
                                                    "reason": "Khá giống",
                                                },
                                                {
                                                    "product_code": "INVENTED",
                                                    "visual_score": 1.0,
                                                    "reason": "Không hợp lệ",
                                                },
                                            ]
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    async_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    )
    verifier = ProductVisualVerifier(
        api_key="secret",
        model="gemini-test",
        client=async_client,
    )

    result = await verifier.verify(
        query_data=b"query-image",
        query_media_type="image/jpeg",
        candidates=[
            ProductVisualCandidate("SKU01", b"image-1", "image/png"),
            ProductVisualCandidate("SKU02", b"image-2", "image/webp"),
        ],
    )

    await async_client.aclose()
    assert [item.product_code for item in result] == ["SKU01", "SKU02"]
    assert result[0].visual_score == pytest.approx(0.92)

