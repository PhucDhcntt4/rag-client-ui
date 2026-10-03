from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator # type: ignore


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
    history: list[ChatMessage] = Field(
        default_factory=list,
        max_length=MAX_HISTORY_MESSAGES,
    )
    doc_type_id: int | None = Field(default=None, ge=1)
    group_ids: list[int] | None = Field(default=None, max_length=20)
    top_k: int | None = Field(default=None, ge=1, le=20)

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


class ChatResponse(ApiModel):
    status: Literal["answered", "insufficient_context"]
    answer: str
    sources: list[ChatSource] = Field(default_factory=list)
    retrieved_content: str | None = None
    retrieval_elapsed_ms: float | None = None
    model: str | None = None


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
