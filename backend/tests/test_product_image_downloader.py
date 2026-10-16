import httpx
import pytest

from app.services.product_image_downloader import (
    ProductImageDownloadError,
    ProductImageDownloader,
)


@pytest.mark.asyncio
async def test_product_image_downloader_returns_a_valid_public_image():
    def handler(request: httpx.Request):
        assert request.url == "https://cdn.example.test/product.jpg"
        return httpx.Response(
            200,
            headers={"Content-Type": "image/jpeg"},
            content=b"reference-image",
        )

    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    downloader = ProductImageDownloader(
        max_bytes=1024,
        timeout=5,
        client=async_client,
        resolver=lambda _hostname: ["8.8.8.8"],
    )

    result = await downloader.download(
        "https://cdn.example.test/product.jpg"
    )

    await async_client.aclose()
    assert result.data == b"reference-image"
    assert result.media_type == "image/jpeg"


@pytest.mark.asyncio
async def test_product_image_downloader_blocks_private_networks():
    downloader = ProductImageDownloader(
        max_bytes=1024,
        timeout=5,
        resolver=lambda _hostname: ["127.0.0.1"],
    )

    with pytest.raises(ProductImageDownloadError):
        await downloader.download("https://internal.example.test/image.jpg")

    await downloader.close()


@pytest.mark.asyncio
async def test_product_image_downloader_rejects_oversized_images():
    def handler(_request: httpx.Request):
        return httpx.Response(
            200,
            headers={
                "Content-Type": "image/png",
                "Content-Length": "2048",
            },
            content=b"x",
        )

    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    downloader = ProductImageDownloader(
        max_bytes=1024,
        timeout=5,
        client=async_client,
        resolver=lambda _hostname: ["8.8.8.8"],
    )

    with pytest.raises(ProductImageDownloadError):
        await downloader.download("https://cdn.example.test/large.png")

    await async_client.aclose()

