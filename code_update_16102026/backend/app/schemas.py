from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator # type: ignore

from app.config import AiProvider


MAX_HISTORY_MESSAGES = 12
MAX_HISTORY_CHARACTERS = 24_000


class ApiModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class ChatMessage(ApiModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class ChatRequest(ApiModel):
    query: str = Field(min_length=1, max_length=4_000)
    data_source: Literal["auto", "documents", "products"] = "auto"
    history: list[ChatMessage] = Field(
        default_factory=list,
        max_length=MAX_HISTORY_MESSAGES,
    )
    doc_type_id: int | None = Field(default=None, ge=1)
    group_ids: list[int] | None = Field(default=None, max_length=20)
    top_k: int | None = Field(default=None, ge=1, le=20)
    ai_provider: AiProvider | None = None

    @model_validator(mode="after")
    def validate_request(self):
        history_length = sum(
            len(message.content)
            for message in self.history
        )

        if history_length > MAX_HISTORY_CHARACTERS:
            raise ValueError(
                "Tổng nội dung lịch sử không được vượt quá "
                f"{MAX_HISTORY_CHARACTERS} ký tự"
            )

        if self.group_ids is not None:
            if not self.group_ids:
                raise ValueError(
                    "group_ids không được là danh sách rỗng"
                )

            if len(set(self.group_ids)) != len(self.group_ids):
                raise ValueError(
                    "group_ids không được chứa giá trị trùng nhau"
                )

        return self


class SourceAsset(ApiModel):
    id: int = Field(ge=1)
    asset_type: str
    page_number: int = Field(ge=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    bbox: list[float]
    media_type: str
    url: str
    caption: str | None = None


class ChatSource(ApiModel):
    citation: str
    source_key: str
    title: str
    category: str
    heading: str | None = None
    section_path: list[str] = Field(default_factory=list)
    chunk_index: int
    similarity: float | None = None
    assets: list[SourceAsset] = Field(default_factory=list)


class ProductVariant(ApiModel):
    sku: str = ""
    barcode: str = ""
    external_id: str = ""
    variant_title: str = ""
    color: str = ""
    size: str = ""
    price: float | None = None
    compare_at_price: float | None = None
    inventory_quantity: int | None = None
    available: bool | None = None


class ProductSource(ApiModel):
    citation: str
    product_code: str
    title: str
    product_type: str = ""
    vendor: str = ""
    status: str = ""
    description: str = ""
    material: str = ""
    sole: str = ""
    height: str = ""
    handle: str = ""
    aliases: list[str] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)
    image_url: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    online_store_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    published_at: str | None = None
    new_at: str | None = None
    minimum_price: float | None = None
    maximum_price: float | None = None
    inventory_synced_at: str | None = None
    inventory_status: Literal["in_stock", "out_of_stock", "unknown"] = "unknown"
    total_inventory: int | None = None
    available_variant_count: int = 0
    variants: list[ProductVariant] = Field(default_factory=list)
    image_similarity: float | None = Field(default=None, ge=-1, le=1)
    matched_image_url: str | None = None
    matched_color: str = ""


class ProductResultMeta(ApiModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=50)
    shown: int = Field(ge=0)
    total: int | None = Field(default=None, ge=0)
    total_pages: int | None = Field(default=None, ge=0)
    has_more: bool = False
    date_from: str | None = None
    date_to: str | None = None


class ProductPageResponse(ApiModel):
    products: list[ProductSource] = Field(default_factory=list)
    result: ProductResultMeta


class ProductImageQuery(ApiModel):
    filename: str
    media_type: str
    size_bytes: int = Field(ge=1)


class ProductImageSearchResponse(ApiModel):
    query_image: ProductImageQuery
    products: list[ProductSource] = Field(default_factory=list)
    result: ProductResultMeta
    low_confidence: bool = False
    best_similarity: float | None = Field(default=None, ge=-1, le=1)


class ChatResponse(ApiModel):
    status: Literal["answered", "insufficient_context"]
    answer: str
    data_source: Literal["documents", "products"] = "documents"
    sources: list[ChatSource] = Field(default_factory=list)
    product_sources: list[ProductSource] = Field(default_factory=list)
    product_result: ProductResultMeta | None = None
    retrieved_content: str | None = None
    retrieval_elapsed_ms: float | None = None
    model: str | None = None
    llm_provider: AiProvider | None = None


class AiProviderInfo(ApiModel):
    id: AiProvider
    label: str
    model: str
    available: bool


class AiProvidersResponse(ApiModel):
    default: AiProvider
    providers: list[AiProviderInfo]


class DocumentSummary(ApiModel):
    id: str
    source_key: str
    title: str
    category: str
    doc_type_id: int | None = None
    group_id: int | None = None
    description: str = ""
    updated_at: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    chunk_count: int = 0
    is_active: bool = True


class DocumentDetail(DocumentSummary):
    content: str = ""
    has_local_file: bool = False


class DocumentListResponse(ApiModel):
    documents: list[DocumentSummary]


class TaxonomyGroup(ApiModel):
    id: int
    code: str
    name: str
    description: str = ""
    doc_type_id: int
    is_active: bool = True
    sort_order: int = 0
    document_count: int = 0


class TaxonomyDocType(ApiModel):
    id: int
    code: str
    name: str
    description: str = ""
    is_active: bool = True
    sort_order: int = 0
    groups: list[TaxonomyGroup] = Field(default_factory=list)


class TaxonomyResponse(ApiModel):
    doc_types: list[TaxonomyDocType]
