import base64
import json

import httpx
import pytest

from app.clients.gemini_vision_client import (
    GeminiVisionClient,
    GeminiVisionError,
    load_product_vision_analysis_prompt,
)


def test_product_vision_analysis_prompt_is_available():
    prompt = load_product_vision_analysis_prompt()

    assert prompt
    assert "product_detected" in prompt
    assert "box_2d" in prompt
    assert "[ymin, xmin, ymax, xmax]" in prompt
    assert "Không được đoán mã sản phẩm" in prompt


@pytest.mark.asyncio
async def test_gemini_vision_analyzes_product():
    def handler(request: httpx.Request):
        assert request.url.path.endswith(
            "/models/vision-test-model:generateContent"
        )
        assert request.headers["x-goog-api-key"] == "test-key"

        body = json.loads(request.content)
        inline_data = body["contents"][0]["parts"][0]["inlineData"]
        assert inline_data["mimeType"] == "image/jpeg"
        assert base64.b64decode(inline_data["data"]) == b"image-data"
        assert "product_detected" in body["contents"][0]["parts"][1]["text"]

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
                                            "product_detected": True,
                                            "category": "shoe",
                                            "label": "Giày cao gót",
                                            "box_2d": [100, 200, 900, 800],
                                            "confidence": 0.93,
                                            "description": "Giày cao gót màu đen.",
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GeminiVisionClient(
        api_key="test-key",
        model="vision-test-model",
        base_url="https://gemini.test/v1beta",
        client=async_client,
    )

    result = await client.analyze(data=b"image-data", media_type="image/jpeg")

    assert result.product_detected is True
    assert result.category == "shoe"
    assert result.label == "Giày cao gót"
    assert result.confidence == pytest.approx(0.93)
    assert result.bounding_box is not None
    assert result.bounding_box.x_min == pytest.approx(0.2)
    assert result.bounding_box.y_min == pytest.approx(0.1)
    assert result.bounding_box.x_max == pytest.approx(0.8)
    assert result.bounding_box.y_max == pytest.approx(0.9)

    await async_client.aclose()


@pytest.mark.asyncio
async def test_gemini_vision_handles_no_product():
    def handler(_request: httpx.Request):
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
                                            "product_detected": False,
                                            "category": "unknown",
                                            "label": "",
                                            "box_2d": [0, 0, 1000, 1000],
                                            "confidence": 0.1,
                                            "description": "Không thấy sản phẩm.",
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GeminiVisionClient(
        api_key="test-key",
        model="vision-test-model",
        base_url="https://gemini.test/v1beta",
        client=async_client,
    )

    result = await client.analyze(data=b"image-data", media_type="image/png")

    assert result.product_detected is False
    assert result.category == "unknown"
    assert result.bounding_box is None
    await async_client.aclose()


@pytest.mark.asyncio
async def test_gemini_vision_rejects_invalid_box():
    def handler(_request: httpx.Request):
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
                                            "product_detected": True,
                                            "category": "shoe",
                                            "label": "Giày",
                                            "box_2d": [900, 800, 100, 200],
                                            "confidence": 0.8,
                                            "description": "Giày.",
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GeminiVisionClient(
        api_key="test-key",
        model="vision-test-model",
        base_url="https://gemini.test/v1beta",
        client=async_client,
    )

    with pytest.raises(GeminiVisionError, match="Thứ tự tọa độ"):
        await client.analyze(data=b"image-data", media_type="image/webp")
    await async_client.aclose()


@pytest.mark.asyncio
async def test_gemini_vision_rejects_unsupported_media_type():
    client = GeminiVisionClient(
        api_key="test-key",
        model="vision-test-model",
    )

    with pytest.raises(GeminiVisionError, match="JPEG, PNG và WebP"):
        await client.analyze(data=b"image-data", media_type="image/gif")
    await client.close()
