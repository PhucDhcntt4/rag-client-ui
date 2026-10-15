"""Find visually similar products from the existing Qdrant image collection."""

from __future__ import annotations

import asyncio
from pathlib import PurePath
from typing import Any

from app.clients.image_embedder import (
    ImageEmbeddingError,
    InvalidProductImageError,
    ProductImageEmbedder,
)
from app.clients.qdrant_image_client import QdrantImageClient, QdrantImageError
from app.clients.rag_client import RagClient, RagServiceError
from app.config import Settings
from app.schemas import (
    ProductImageQuery,
    ProductImageSearchResponse,
    ProductResultMeta,
    ProductSource,
)
from app.services.product_service import ProductService, safe_http_url


class ProductImageSearchError(RuntimeError):
    def __init__(self, message: str, *, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class ProductImageService:
    ALLOWED_MEDIA_TYPES = {
        "image/jpeg",
        "image/png",
        "image/webp",
    }

    def __init__(
        self,
        settings: Settings,
        embedder: ProductImageEmbedder,
        qdrant: QdrantImageClient,
        rag_client: RagClient,
    ):
        self.settings = settings
        self.embedder = embedder
        self.qdrant = qdrant
        self.rag_client = rag_client

    @staticmethod
    def _safe_filename(value: str) -> str:
        normalized = str(value or "image").replace("\\", "/")
        return PurePath(normalized).name[:255] or "image"

    @staticmethod
    def _best_matches(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        best_by_product: dict[str, dict[str, Any]] = {}
        for point in points:
            payload = point.get("payload")
            if not isinstance(payload, dict):
                continue
            product_code = str(payload.get("product_code") or "").strip()
            if not product_code:
                continue
            try:
                similarity = float(point.get("score"))
            except (TypeError, ValueError):
                continue
            current = best_by_product.get(product_code)
            if current is None or similarity > current["similarity"]:
                best_by_product[product_code] = {
                    "product_code": product_code,
                    "similarity": similarity,
                    "color": str(payload.get("color") or "").strip(),
                    "image_checksum": str(
                        payload.get("image_checksum") or ""
                    ).strip(),
                }
        return sorted(
            best_by_product.values(),
            key=lambda item: item["similarity"],
            reverse=True,
        )

    @staticmethod
    def _matched_image_url(detail: dict, match: dict[str, Any]) -> str | None:
        payload = ProductService._payload(detail)
        images = payload.get("images") or []
        expected_checksum = match.get("image_checksum")
        expected_color = str(match.get("color") or "").casefold()

        for image in images:
            if not isinstance(image, dict):
                continue
            checksum_matches = (
                expected_checksum
                and image.get("image_checksum") == expected_checksum
            )
            color_matches = (
                expected_color
                and str(image.get("color") or "").casefold() == expected_color
            )
            if checksum_matches or color_matches:
                url = safe_http_url(image.get("source_url"))
                if url:
                    return url
        return None

    async def _load_product(
        self,
        match: dict[str, Any],
    ) -> ProductSource | None:
        try:
            detail = await self.rag_client.get_product(match["product_code"])
        except RagServiceError as exc:
            if exc.status_code == 404:
                return None
            raise

        source = ProductService._to_source(detail, "")
        if source.status and source.status.upper() != "ACTIVE":
            return None

        matched_image_url = self._matched_image_url(detail, match)
        image_urls = list(source.image_urls)
        if matched_image_url:
            image_urls = [
                matched_image_url,
                *(url for url in image_urls if url != matched_image_url),
            ]

        return source.model_copy(
            update={
                "image_urls": image_urls,
                "image_url": image_urls[0] if image_urls else source.image_url,
                "image_similarity": match["similarity"],
                "matched_image_url": matched_image_url,
                "matched_color": match["color"],
            }
        )

    async def search(
        self,
        *,
        filename: str,
        media_type: str,
        data: bytes,
    ) -> ProductImageSearchResponse:
        if not self.settings.product_image_search_enabled:
            raise ProductImageSearchError(
                "Tìm kiếm sản phẩm bằng ảnh đang tắt.",
                status_code=503,
            )
        normalized_media_type = media_type.split(";", 1)[0].strip().lower()
        if normalized_media_type not in self.ALLOWED_MEDIA_TYPES:
            raise ProductImageSearchError(
                "Chỉ hỗ trợ ảnh JPEG, PNG và WebP.",
                status_code=415,
            )
        if not data:
            raise ProductImageSearchError("Ảnh tải lên không có dữ liệu.", status_code=422)
        if len(data) > self.settings.product_image_max_bytes:
            raise ProductImageSearchError(
                "Ảnh vượt quá dung lượng cho phép.",
                status_code=413,
            )

        try:
            vector = await asyncio.to_thread(self.embedder.embed, data)
        except InvalidProductImageError as exc:
            raise ProductImageSearchError(str(exc), status_code=422) from exc
        except ImageEmbeddingError as exc:
            raise ProductImageSearchError(str(exc), status_code=503) from exc

        try:
            points = await self.qdrant.search(
                vector,
                limit=self.settings.product_image_candidate_limit,
                score_threshold=None,
            )
        except QdrantImageError as exc:
            raise ProductImageSearchError(str(exc), status_code=503) from exc

        ranked = self._best_matches(points)
        qualified = [
            match
            for match in ranked
            if match["similarity"] >= self.settings.product_image_min_score
        ]
        low_confidence = not qualified and bool(ranked)
        if low_confidence:
            selected_matches = ranked[: min(3, self.settings.product_image_result_limit)]
        else:
            selected_matches = qualified
        # Fetch a few extra products because stale/inactive catalog entries may
        # be skipped after the image-vector query.
        detail_candidates = selected_matches[
            : self.settings.product_image_result_limit * 3
        ]
        loaded = await asyncio.gather(
            *(self._load_product(match) for match in detail_candidates)
        )
        products = [product for product in loaded if product is not None]
        products = products[: self.settings.product_image_result_limit]

        total = len(products)
        return ProductImageSearchResponse(
            query_image=ProductImageQuery(
                filename=self._safe_filename(filename),
                media_type=normalized_media_type,
                size_bytes=len(data),
            ),
            products=products,
            result=ProductResultMeta(
                page=1,
                page_size=self.settings.product_image_result_limit,
                shown=total,
                total=total,
                total_pages=1 if total else 0,
                has_more=False,
            ),
            low_confidence=low_confidence,
            best_similarity=(ranked[0]["similarity"] if ranked else None),
        )
