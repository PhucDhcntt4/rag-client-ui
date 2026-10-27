"""Search product data and turn raw RAG payloads into safe chat context."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from datetime import datetime, timedelta, tzinfo
from typing import Any, Literal
from urllib.parse import urlparse

from app.clients.rag_client import RagClient, RagServiceError
from app.schemas import (
    ProductPageResponse,
    ProductResultMeta,
    ProductSource,
    ProductVariant,
)


PRODUCT_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?=[A-Za-z0-9._/-]{3,}(?![A-Za-z0-9._/-]))"
    r"(?=[A-Za-z0-9._/-]*[A-Za-z])"
    r"(?=[A-Za-z0-9._/-]*\d)"
    r"[A-Za-z0-9]+(?:[._/-][A-Za-z0-9]+)*"
    r"(?![A-Za-z0-9])"
)
STOP_WORDS = {
    "anh", "ban", "bao", "bay", "bi", "can", "cac", "cho", "co", "con",
    "cua", "dang", "duoc", "gi", "gia", "giup", "hang", "hay", "het",
    "day", "gan", "hien", "hom", "kiem", "kho", "khong", "la", "loai",
    "luong", "ma", "mau", "nay",
    "minh", "moi", "mot", "nao", "nhat", "nhieu", "pham", "ra", "san",
    "size", "so", "sp", "tai", "thang", "the", "thong", "tin", "toi",
    "ton", "trong", "tuan", "va", "ve", "voi", "xin",
}

StockFilter = Literal["in_stock", "out_of_stock"]

LATEST_PHRASES = (
    "san pham moi", "mau moi", "hang moi", "moi nhat", "moi hien tai",
    "moi ve", "vua ra mat", "vua phat hanh",
)
OUT_OF_STOCK_PHRASES = (
    "het hang", "het kho", "khong con hang", "khong con kho",
    "khong co hang", "da ban het",
)
IN_STOCK_PHRASES = (
    "con hang", "con kho", "dang co hang", "co san", "con ton",
)


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").casefold())
    text = "".join(
        character
        for character in text
        if unicodedata.category(character) != "Mn"
    )
    text = text.replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def safe_http_url(value: Any) -> str | None:
    if not value:
        return None
    url = str(value).strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return url


class ProductService:
    def __init__(
        self,
        rag_client: RagClient,
        *,
        product_timezone: tzinfo,
        chat_page_size: int,
        candidate_page_size: int,
    ):
        self.rag_client = rag_client
        self.product_timezone = product_timezone
        self.chat_page_size = chat_page_size
        self.candidate_page_size = candidate_page_size

    @staticmethod
    def _requested_identifiers(query: str) -> list[str]:
        return list(dict.fromkeys(
            match.group(0).upper()
            for match in PRODUCT_IDENTIFIER_PATTERN.finditer(query)
        ))

    @staticmethod
    def _search_terms(query: str) -> list[str]:
        normalized = normalize_text(query)
        tokens = [
            token
            for token in normalized.split()
            if token not in STOP_WORDS and len(token) >= 2
        ]
        if "nam nay" in normalized:
            tokens = [token for token in tokens if token != "nam"]
        terms: list[str] = []
        if tokens:
            terms.append(" ".join(tokens[:5]))
        terms.extend(token for token in tokens if not token.isdigit())
        return list(dict.fromkeys(terms))[:6]

    @staticmethod
    def _latest_search_terms(query: str) -> list[str]:
        """Remove date expressions before extracting product descriptors."""

        normalized = normalize_text(query)
        normalized = re.sub(
            r"\bthang\s+(?:0?[1-9]|1[0-2])"
            r"(?:\s+(?:nam\s+)?\d{4})?\b",
            " ",
            normalized,
        )
        return ProductService._search_terms(normalized)

    @staticmethod
    def _intent(query: str) -> tuple[bool, StockFilter | None]:
        normalized = normalize_text(query)
        latest = any(phrase in normalized for phrase in LATEST_PHRASES)

        # Kiểm tra hết hàng trước vì "không còn hàng"
        # cũng chứa cụm "còn hàng".
        if any(phrase in normalized for phrase in OUT_OF_STOCK_PHRASES):
            return latest, "out_of_stock"
        if any(phrase in normalized for phrase in IN_STOCK_PHRASES):
            return latest, "in_stock"
        return latest, None

    def _new_date_period(self, query: str) -> tuple[datetime, datetime] | None:
        normalized = normalize_text(query)
        now = datetime.now(self.product_timezone)

        if "hom nay" in normalized:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, start + timedelta(days=1)

        if "tuan nay" in normalized:
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            start = today - timedelta(days=today.weekday())
            return start, start + timedelta(days=7)

        if "thang nay" in normalized:
            start = now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=start.month + 1)
            return start, end

        if "nam nay" in normalized:
            start = now.replace(
                month=1, day=1, hour=0, minute=0, second=0, microsecond=0
            )
            return start, start.replace(year=start.year + 1)

        explicit_month = re.search(
            r"\bthang\s+(0?[1-9]|1[0-2])"
            r"(?:\s+(?:nam\s+)?(\d{4}))?\b",
            normalized,
        )
        if explicit_month:
            month = int(explicit_month.group(1))
            year = int(explicit_month.group(2) or now.year)
            start = now.replace(
                year=year,
                month=month,
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            if month == 12:
                end = start.replace(year=year + 1, month=1)
            else:
                end = start.replace(month=month + 1)
            return start, end

        return None

    @staticmethod
    def _payload(detail: dict) -> dict:
        product = detail.get("product")
        return product if isinstance(product, dict) else detail

    @staticmethod
    def _score(payload: dict, query: str) -> int:
        variants = payload.get("variants") or []
        public_info = payload.get("public_info") or {}
        values = [
            payload.get("product_code"), payload.get("title"),
            payload.get("product_type"), payload.get("vendor"),
            public_info.get("colors"), public_info.get("available_sizes"),
        ]
        for variant in variants:
            if isinstance(variant, dict):
                values.extend(
                    [variant.get("sku"), variant.get("color"), variant.get("size")]
                )
        haystack = normalize_text(" ".join(str(value) for value in values if value))
        tokens = [
            token
            for token in normalize_text(query).split()
            if token not in STOP_WORDS
        ]
        if "nam nay" in normalize_text(query):
            tokens = [token for token in tokens if token != "nam"]
        return sum(1 for token in tokens if token in haystack)

    @staticmethod
    def _to_source(
        detail: dict,
        citation: str,
        query: str = "",
    ) -> ProductSource:
        payload = ProductService._payload(detail)
        public_info = payload.get("public_info") or {}
        detail_product = (payload.get("detail") or {}).get("product") or {}
        images = payload.get("images") or []
        raw_variants = [
            raw
            for raw in payload.get("variants") or []
            if isinstance(raw, dict)
        ]
        image_urls_by_color = public_info.get("image_urls_by_color") or {}
        color_names = list(dict.fromkeys(
            [
                str(color).strip()
                for color in image_urls_by_color
                if str(color).strip()
            ]
            + [
                str(raw.get("color") or "").strip()
                for raw in raw_variants
                if str(raw.get("color") or "").strip()
            ]
        ))
        normalized_query = f" {normalize_text(query)} "
        matched_color = next(
            (
                color
                for color in color_names
                if f" {normalize_text(color)} " in normalized_query
            ),
            "",
        )

        selected_image_values = public_info.get("image_urls") or []
        if matched_color and image_urls_by_color:
            selected_image_values = next(
                (
                    values
                    for color, values in image_urls_by_color.items()
                    if normalize_text(color) == normalize_text(matched_color)
                ),
                selected_image_values,
            )
        image_urls = list(dict.fromkeys(
            url
            for url in (
                safe_http_url(value)
                for value in selected_image_values
            )
            if url
        ))
        image_url = next(
            iter(image_urls),
            None,
        )
        if image_url is None:
            image_url = next(
                (
                    safe_http_url(image.get("source_url"))
                    for image in images
                    if isinstance(image, dict) and safe_http_url(image.get("source_url"))
                ),
                None,
            )

        variants: list[ProductVariant] = []
        for raw in raw_variants:
            if (
                matched_color
                and normalize_text(raw.get("color"))
                != normalize_text(matched_color)
            ):
                continue
            variants.append(
                ProductVariant(
                    sku=str(raw.get("sku") or ""),
                    barcode=str(raw.get("barcode") or ""),
                    external_id=str(raw.get("external_id") or ""),
                    variant_title=str(raw.get("variant_title") or ""),
                    color=str(raw.get("color") or ""),
                    size=str(raw.get("size") or ""),
                    price=optional_float(raw.get("price")),
                    compare_at_price=optional_float(raw.get("compare_at_price")),
                    inventory_quantity=optional_int(raw.get("inventory_quantity")),
                    available=(
                        bool(raw.get("available"))
                        if raw.get("available") is not None
                        else None
                    ),
                )
            )

        known_quantities = [
            variant.inventory_quantity
            for variant in variants
            if variant.inventory_quantity is not None
        ]
        total_inventory = (
            sum(max(0, quantity) for quantity in known_quantities)
            if known_quantities else None
        )
        available_variant_count = sum(
            1
            for variant in variants
            if variant.available
            or (
                variant.inventory_quantity is not None
                and variant.inventory_quantity > 0
            )
        )
        if available_variant_count > 0:
            inventory_status = "in_stock"
        elif variants and (
            known_quantities
            or (
                all(variant.available is not None for variant in variants)
                and all(variant.available is False for variant in variants)
            )
        ):
            inventory_status = "out_of_stock"
        else:
            inventory_status = "unknown"

        prices = [
            variant.price
            for variant in variants
            if variant.price is not None
        ]
        aliases = [
            " - ".join(
                part for part in (
                    str(item.get("alias_type") or "").strip(),
                    str(item.get("alias") or "").strip(),
                ) if part
            )
            for item in payload.get("aliases") or []
            if isinstance(item, dict) and item.get("alias")
        ]
        attributes = [
            ": ".join(
                part for part in (
                    str(item.get("attribute_key") or "").strip(),
                    str(item.get("attribute_value") or "").strip(),
                ) if part
            )
            for item in payload.get("attributes") or []
            if isinstance(item, dict) and item.get("attribute_value")
        ]

        return ProductSource(
            citation=citation,
            product_code=str(
                payload.get("product_code") or public_info.get("product_code") or ""
            ),
            title=str(
                payload.get("title") or public_info.get("product_name") or "Sản phẩm"
            ),
            product_type=str(payload.get("product_type") or ""),
            vendor=str(payload.get("vendor") or ""),
            status=str(payload.get("status") or ""),
            description=str(
                payload.get("description")
                or public_info.get("description")
                or detail_product.get("description")
                or ""
            ),
            material=str(payload.get("material") or public_info.get("material") or ""),
            sole=str(payload.get("sole") or public_info.get("sole") or ""),
            height=str(payload.get("height") or public_info.get("height") or ""),
            handle=str(detail_product.get("handle") or ""),
            aliases=aliases,
            attributes=attributes,
            image_url=image_url,
            image_urls=image_urls,
            online_store_url=safe_http_url(detail_product.get("online_store_url")),
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
            published_at=payload.get("published_at"),
            new_at=payload.get("new_at"),
            minimum_price=min(prices) if prices else None,
            maximum_price=max(prices) if prices else None,
            inventory_synced_at=payload.get("inventory_synced_at"),
            inventory_status=inventory_status,
            total_inventory=total_inventory,
            available_variant_count=available_variant_count,
            variants=variants,
            matched_color=matched_color,
        )

    @staticmethod
    def _matches_identifier(detail: dict, identifier: str) -> bool:
        payload = ProductService._payload(detail)
        values = [
            payload.get("product_code"),
            *(payload.get("variant_skus") or []),
            *(
                row.get("sku")
                for row in payload.get("variants") or []
                if isinstance(row, dict)
            ),
            *(
                row.get("alias")
                for row in payload.get("aliases") or []
                if isinstance(row, dict)
            ),
        ]
        expected = normalize_text(identifier)
        return any(normalize_text(value) == expected for value in values if value)

    async def _load_detail(self, product_code: str) -> dict | None:
        try:
            return await self.rag_client.get_product(product_code)
        except RagServiceError as exc:
            if exc.status_code == 404:
                return None
            raise

    async def _load_details(self, product_codes: list[str]) -> list[dict]:
        semaphore = asyncio.Semaphore(24)

        async def load(product_code: str):
            async with semaphore:
                return await self._load_detail(product_code)

        loaded = await asyncio.gather(*(load(code) for code in product_codes))
        return [item for item in loaded if item is not None]

    async def _resolve_identifiers(self, identifiers: list[str]) -> list[dict]:
        resolved: dict[str, dict] = {}
        for identifier in identifiers:
            direct = await self._load_detail(identifier)
            candidates = [direct] if direct is not None else []
            if direct is None:
                result = await self.rag_client.list_products(
                    query=identifier,
                    status="ACTIVE",
                    page=1,
                    limit=self.candidate_page_size,
                )
                product_codes = [
                    str(row.get("product_code") or "").strip()
                    for row in result.get("products") or []
                    if row.get("product_code")
                ]
                candidates = await self._load_details(product_codes)

            exact = [
                detail
                for detail in candidates
                if self._matches_identifier(detail, identifier)
            ]
            selected = exact or (candidates[:1] if len(candidates) == 1 else [])
            for detail in selected:
                payload = self._payload(detail)
                product_code = str(payload.get("product_code") or "").strip()
                if product_code:
                    resolved.setdefault(product_code, detail)
        return list(resolved.values())

    @staticmethod
    def _number_sources(
        sources: list[ProductSource],
        limit: int,
        *,
        start_index: int = 1,
    ) -> list[ProductSource]:
        return [
            source.model_copy(update={"citation": f"S{index}"})
            for index, source in enumerate(sources[:limit], start=start_index)
        ]

    @staticmethod
    def _page_response(
        sources: list[ProductSource],
        *,
        page: int,
        page_size: int,
        total: int | None = None,
        total_pages: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> ProductPageResponse:
        return ProductPageResponse(
            products=sources,
            result=ProductResultMeta(
                page=page,
                page_size=page_size,
                shown=len(sources),
                total=total,
                total_pages=total_pages,
                has_more=(
                    total_pages is not None and page < total_pages
                ),
                date_from=date_from.isoformat() if date_from else None,
                date_to=date_to.isoformat() if date_to else None,
            ),
        )

    async def list_latest_page(
        self,
        *,
        page: int = 1,
        limit: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> ProductPageResponse:
        page_size = limit or self.chat_page_size
        result = await self.rag_client.list_latest_products(
            page=page,
            limit=page_size,
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
        )
        codes = [
            str(row.get("product_code") or "").strip()
            for row in result.get("products") or []
            if row.get("product_code")
        ]
        details = await self._load_details(codes)
        sources = [self._to_source(detail, "") for detail in details]
        numbered = self._number_sources(
            sources,
            page_size,
            start_index=(page - 1) * page_size + 1,
        )
        total = int(result.get("total") or 0)
        total_pages = int(result.get("total_pages") or 0)
        return self._page_response(
            numbered,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
            date_from=date_from,
            date_to=date_to,
        )

    async def _scan_inventory(
        self,
        stock_filter: StockFilter,
        *,
        limit: int,
    ) -> list[ProductSource]:
        """Scan catalog pages until enough products match an inventory state."""
        matches: list[ProductSource] = []
        page = 1
        page_size = 20 if stock_filter == "in_stock" else 100

        while len(matches) < limit:
            result = await self.rag_client.list_products(
                status="ACTIVE", page=page, limit=page_size,
            )
            summaries = result.get("products") or []
            codes = [
                str(row.get("product_code") or "").strip()
                for row in summaries
                if row.get("product_code")
            ]
            if not codes:
                break

            details = await self._load_details(codes)
            for detail in details:
                source = self._to_source(detail, "")
                if source.inventory_status == stock_filter:
                    matches.append(source)
                    if len(matches) >= limit:
                        break

            total_pages = int(result.get("total_pages") or page)
            if page >= total_pages or len(summaries) < page_size:
                break
            page += 1

        return self._number_sources(matches, limit)

    async def search_for_question(
        self,
        query: str,
        *,
        limit: int | None = None,
    ) -> ProductPageResponse:
        page_size = limit or self.chat_page_size
        exact_codes = self._requested_identifiers(query)
        latest, stock_filter = self._intent(query)
        new_date_period = self._new_date_period(query) if latest else None
        details: list[dict] = []
        result_total: int | None = None
        result_total_pages: int | None = None

        if exact_codes:
            details = await self._resolve_identifiers(exact_codes[:page_size])

        elif latest:
            search_terms = self._latest_search_terms(query)
            candidate_limit = (
                self.candidate_page_size
                if stock_filter or search_terms
                else page_size
            )
            result = await self.rag_client.list_latest_products(
                page=1,
                limit=candidate_limit,
                date_from=(
                    new_date_period[0].isoformat()
                    if new_date_period else None
                ),
                date_to=(
                    new_date_period[1].isoformat()
                    if new_date_period else None
                ),
            )
            codes = [
                str(row.get("product_code") or "").strip()
                for row in result.get("products") or []
                if row.get("product_code")
            ]
            details = await self._load_details(codes)

            # Với câu như "giày nam mới nhất", giữ thứ tự
            # mới nhất nhưng loại sản phẩm không khớp.
            if search_terms:
                matched = [
                    detail
                    for detail in details
                    if self._score(self._payload(detail), query) > 0
                ]
                if matched:
                    details = matched

            if not details:
                return self._page_response(
                    [],
                    page=1,
                    page_size=page_size,
                    total=0,
                    total_pages=0,
                    date_from=new_date_period[0] if new_date_period else None,
                    date_to=new_date_period[1] if new_date_period else None,
                )

            if not stock_filter and not search_terms:
                result_total = int(result.get("total") or 0)
                result_total_pages = int(result.get("total_pages") or 0)

        if not details:
            summaries: dict[str, dict] = {}
            search_terms = self._search_terms(query)
            for term in search_terms:
                result = await self.rag_client.list_products(
                    query=term, status="ACTIVE", page=1, limit=100,
                )
                for row in result.get("products") or []:
                    code = str(row.get("product_code") or "").strip()
                    if code:
                        summaries.setdefault(code, row)
                if len(summaries) >= 100:
                    break

            if not summaries and stock_filter and not search_terms:
                sources = await self._scan_inventory(
                    stock_filter,
                    limit=page_size,
                )
                return self._page_response(
                    sources,
                    page=1,
                    page_size=page_size,
                )

            if not summaries:
                result = await self.rag_client.list_products(
                    status="ACTIVE", page=1, limit=12,
                )
                summaries = {
                    str(row.get("product_code")): row
                    for row in result.get("products") or []
                    if row.get("product_code")
                }

            details = await self._load_details(list(summaries)[:100])

        sources = [self._to_source(detail, "", query) for detail in details]

        # Mã sản phẩm cụ thể luôn được giữ lại để LLM có
        # thể trả lời "còn" hoặc "hết". Chỉ lọc các câu hỏi chung.
        if stock_filter and not exact_codes:
            sources = [
                source
                for source in sources
                if source.inventory_status == stock_filter
            ]

        if not latest:
            sources.sort(
                key=lambda source: self._score(source.model_dump(), query),
                reverse=True,
            )
        numbered = self._number_sources(sources, page_size)
        if result_total is None and (exact_codes or not latest):
            result_total = len(numbered)
            result_total_pages = 1 if numbered else 0
        return self._page_response(
            numbered,
            page=1,
            page_size=page_size,
            total=result_total,
            total_pages=result_total_pages,
            date_from=new_date_period[0] if new_date_period else None,
            date_to=new_date_period[1] if new_date_period else None,
        )

    async def load_latest_answer_context(
        self,
        query: str,
        first_page: ProductPageResponse,
        *,
        max_products: int = 100,
    ) -> ProductPageResponse:
        """Load a complete dated latest-product set for the LLM only.

        The response sent to the browser remains paginated, so product cards
        and galleries are unchanged.
        """

        result = first_page.result
        latest, _stock_filter = self._intent(query)
        if (
            not latest
            or not result.has_more
            or not result.date_from
            or not result.date_to
            or not result.total
        ):
            return first_page

        target_count = min(result.total, max_products)
        page_size = min(50, target_count)
        total_pages = (target_count + page_size - 1) // page_size
        page_results = await asyncio.gather(
            *(
                self.rag_client.list_latest_products(
                    page=page,
                    limit=page_size,
                    date_from=result.date_from,
                    date_to=result.date_to,
                )
                for page in range(1, total_pages + 1)
            )
        )
        codes = list(dict.fromkeys(
            str(row.get("product_code") or "").strip()
            for page_result in page_results
            for row in page_result.get("products") or []
            if row.get("product_code")
        ))[:target_count]
        details = await self._load_details(codes)
        products = [
            self._to_source(detail, "", query)
            for detail in details
        ]
        complete = len(products) >= result.total
        context_result = result.model_copy(
            update={
                "page": 1,
                "page_size": min(50, max(1, len(products))),
                "shown": len(products),
                "total_pages": 1 if complete else result.total_pages,
                "has_more": not complete,
            }
        )
        return ProductPageResponse(
            products=products,
            result=context_result,
        )


def build_product_context(
    products: list[ProductSource],
    query: str,
    result: ProductResultMeta | None = None,
) -> str:
    normalized_query = normalize_text(query)
    query_tokens = set(normalized_query.split()) - STOP_WORDS
    latest, stock_filter = ProductService._intent(query)
    asks_full_product = (
        len(products) == 1
        and bool(ProductService._requested_identifiers(query))
    )
    asks_inventory = asks_full_product or stock_filter is not None or any(
        phrase in normalized_query
        for phrase in ("ton kho", "so luong", "con bao nhieu")
    )
    asks_variants = asks_full_product or asks_inventory or any(
        phrase in normalized_query
        for phrase in ("gia", "mau", "size", "kich co", "bien the")
    )
    intent_parts = []
    if asks_full_product:
        intent_parts.append("tra cứu đầy đủ một sản phẩm theo mã hoặc SKU")
    if latest:
        intent_parts.append("sản phẩm mới nhất")
    if stock_filter == "in_stock":
        intent_parts.append("chỉ sản phẩm còn hàng")
    elif stock_filter == "out_of_stock":
        intent_parts.append("chỉ sản phẩm hết hàng")

    blocks: list[str] = [
        "YÊU CẦU ĐÃ NHẬN DIỆN: "
        + (", ".join(intent_parts) if intent_parts else "tra cứu sản phẩm"),
        "Danh sách bên dưới đã được Client Backend truy xuất và lọc theo yêu cầu.",
    ]
    if result is not None:
        blocks.append(
            "THỐNG KÊ KẾT QUẢ:\n"
            + (
                f"- Tổng số sản phẩm khớp bộ lọc: {result.total}\n"
                if result.total is not None else ""
            )
            + f"- Số sản phẩm trong ngữ cảnh hiện tại: {result.shown}\n"
            + (
                f"- Khoảng ngày đang truy vấn: "
                f"{result.date_from} đến {result.date_to}\n"
                if result.date_from and result.date_to else ""
            )
            + f"- Trang hiện tại: {result.page}"
            + (
                f"/{result.total_pages}"
                if result.total_pages is not None else ""
            )
            + (
                "\n- Vẫn còn kết quả ở trang sau."
                if result.has_more else ""
            )
        )

    def money(value: float | None) -> str:
        return (
            f"{value:,.0f} đ".replace(",", ".")
            if value is not None else ""
        )

    def clean_cell(value: Any) -> str:
        return str(value or "").replace("|", "\\|").replace("\n", " ").strip()

    for product in products:
        lines = [
            f"SẢN PHẨM: {product.title}",
            f"- Mã sản phẩm: {product.product_code}",
        ]
        for label, value in (
            ("Loại", product.product_type),
            ("Nhà cung cấp", product.vendor),
            ("Trạng thái catalog", product.status),
        ):
            if value:
                lines.append(f"- {label}: {value}")

        if asks_full_product:
            optional_fields = [
                ("Mô tả", product.description),
                ("Chất liệu", product.material),
                ("Loại đế", product.sole),
                ("Chiều cao", product.height),
            ]
            for label, value in optional_fields:
                if value:
                    lines.append(f"- {label}: {value}")

            if product.minimum_price is not None:
                minimum = money(product.minimum_price)
                maximum = money(product.maximum_price)
                price_range = (
                    minimum
                    if product.maximum_price == product.minimum_price
                    else f"{minimum} - {maximum}"
                )
                lines.append(f"- Khoảng giá: {price_range}")
            for label, value in (
                ("Handle", product.handle),
                ("Tên/mã thay thế", ", ".join(product.aliases)),
                ("Thuộc tính", "; ".join(product.attributes)),
                ("Ngày tạo", product.created_at),
                ("Ngày cập nhật", product.updated_at),
                ("Ngày xuất bản", product.published_at),
                ("Ngày sản phẩm mới", product.new_at),
            ):
                if value:
                    lines.append(f"- {label}: {value}")

        if latest and not asks_full_product and product.new_at:
            lines.append(
                f"- Ngày sản phẩm mới: {product.new_at}"
            )

        if asks_inventory:
            inventory_label = {
                "in_stock": "Còn hàng",
                "out_of_stock": "Hết hàng",
                "unknown": "Chưa xác định",
            }[product.inventory_status]
            if product.inventory_status != "unknown":
                lines.append(f"- Trạng thái tồn kho: {inventory_label}")
            if product.total_inventory is not None:
                lines.append(f"- Tổng tồn kho: {product.total_inventory}")
            if product.variants:
                lines.append(
                    f"- Số biến thể còn hàng: "
                    f"{product.available_variant_count}"
                )
            if product.inventory_synced_at:
                lines.append(
                    f"- Tồn kho cập nhật lúc: "
                    f"{product.inventory_synced_at}"
                )

        variants = list(product.variants)
        if query_tokens and not asks_full_product:
            variants.sort(
                key=lambda variant: sum(
                    token
                    in normalize_text(f"{variant.sku} {variant.color} {variant.size}")
                    for token in query_tokens
                ),
                reverse=True,
            )
        selected_variants = variants if asks_full_product else variants[:40]
        if asks_variants and selected_variants:
            column_options = [
                ("SKU", lambda item: item.sku),
                ("Barcode", lambda item: item.barcode if asks_full_product else ""),
                (
                    "Tên biến thể",
                    lambda item: item.variant_title if asks_full_product else "",
                ),
                ("Màu", lambda item: item.color),
                ("Size", lambda item: item.size),
                ("Giá", lambda item: money(item.price)),
                (
                    "Giá so sánh",
                    lambda item: money(item.compare_at_price)
                    if asks_full_product else "",
                ),
                (
                    "Số lượng tồn",
                    lambda item: (
                        str(item.inventory_quantity)
                        if asks_inventory
                        and item.inventory_quantity is not None
                        else ""
                    ),
                ),
                (
                    "Còn hàng",
                    lambda item: (
                        "Có" if item.available else "Không"
                    ) if asks_inventory and item.available is not None else "",
                ),
            ]
            columns = [
                (title, getter)
                for title, getter in column_options
                if any(clean_cell(getter(item)) for item in selected_variants)
            ]
            if columns:
                lines.append("- Các biến thể:")
                lines.append(
                    "| " + " | ".join(title for title, _ in columns) + " |"
                )
                lines.append(
                    "| " + " | ".join("---" for _ in columns) + " |"
                )
                for variant in selected_variants:
                    cells = [
                        clean_cell(getter(variant))
                        for _, getter in columns
                    ]
                    lines.append("| " + " | ".join(cells) + " |")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
