
import re
from pathlib import Path

from app.clients.llm_client import LlmAnswer, LlmClient, LlmServiceError
from app.clients.rag_client import RagClient
from app.config import Settings
from app.schemas import ChatRequest, ChatResponse, ChatSource, SourceAsset
from app.services.product_service import ProductService, build_product_context
from app.services.query_router import detect_data_source


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "answer.txt"
PRODUCT_PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "product_answer.txt"
)


def load_answer_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def load_product_prompt() -> str:
    return PRODUCT_PROMPT_PATH.read_text(encoding="utf-8").strip()


def prepare_retrieval(retrieval: dict) -> tuple[list[dict], str]:
    """Preserve every source returned after the RAG server expands a section."""
    sources = list(retrieval.get("sources") or [])
    raw_context = str(retrieval.get("content") or "")
    parts = [
        part.strip()
        for part in re.split(r"(?=\[Nguồn:)", raw_context)
        if part.strip()
    ]
    if (
        sources
        and len(parts) >= len(sources)
        and all(
            part.startswith("[Nguồn:")
            for part in parts[:len(sources)]
        )
    ):
        context = "\n\n".join(
            f"[S{index}] {part}"
            for index, part in enumerate(parts[:len(sources)], start=1)
        )
    else:
        context = raw_context
    return sources, context


class ChatService:
    def __init__(
        self,
        settings: Settings,
        rag_client: RagClient,
        llm_client: LlmClient,
        product_service: ProductService | None = None,
    ):
        self.settings = settings
        self.rag_client = rag_client
        self.llm_client = llm_client
        self.product_service = product_service or ProductService(
            rag_client,
            product_timezone=settings.product_timezone,
            chat_page_size=settings.product_chat_page_size,
            candidate_page_size=settings.product_candidate_page_size,
        )

    async def answer(self, request: ChatRequest) -> ChatResponse:
        requested_provider = (
            request.ai_provider or self.settings.primary_ai_provider
        )
        try:
            llm_config = self.settings.get_ai_provider_config(
                requested_provider
            )
        except ValueError as exc:
            raise LlmServiceError(str(exc)) from exc

        data_source = request.data_source
        if data_source == "auto":
            data_source = detect_data_source(
                request.query,
                request.history,
                has_document_scope=bool(
                    request.doc_type_id or request.group_ids
                ),
            )

        if data_source == "products":
            return await self._answer_products(
                request,
                provider_name=llm_config.provider,
            )

        retrieval = await self.rag_client.search(
            request.query,
            doc_type_id=request.doc_type_id,
            group_ids=request.group_ids,
            top_k=request.top_k,
        )
        if not retrieval["success"] or retrieval["status"] == "knowledge_not_found":
            return ChatResponse(
                status="insufficient_context",
                answer="Tôi chưa tìm thấy thông tin phù hợp trong kho tài liệu.",
                data_source="documents",
                sources=[],
                retrieval_elapsed_ms=retrieval.get("elapsed_ms"),
                model=None,
                llm_provider=llm_config.provider,
            )

        retrieval_sources, retrieval_content = prepare_retrieval(retrieval)
        sources = [
            ChatSource(
                citation=f"S{index}",
                source_key=str(source.get("source_key") or ""),
                title=str(source.get("title") or "Nguồn"),
                category=str(source.get("category") or "other"),
                heading=source.get("heading"),
                section_path=list(source.get("section_path") or []),
                chunk_index=int(source.get("chunk_index") or 0),
                similarity=source.get("similarity"),
                assets=[
                    SourceAsset(
                        id=int(asset["id"]),
                        asset_type=str(asset.get("asset_type") or "image"),
                        page_number=int(asset["page_number"]),
                        width=int(asset["width"]),
                        height=int(asset["height"]),
                        bbox=[float(value) for value in asset.get("bbox", [])],
                        media_type=str(asset.get("media_type") or "image/png"),
                        url=f"/api/rag-assets/{int(asset['id'])}",
                        caption=asset.get("caption"),
                    )
                    for asset in source.get("assets", [])
                ],
            )
            for index, source in enumerate(retrieval_sources, start=1)
        ]
        generation = await self.llm_client.generate_answer(
            system_prompt=load_answer_prompt(),
            query=request.query,
            history=[item.model_dump() for item in request.history],
            context=retrieval_content,
            sources=[source.model_dump() for source in sources],
            provider=request.ai_provider,
        )
        if isinstance(generation, LlmAnswer):
            answer = generation.text
            answer_model = generation.model
            answer_provider = generation.provider
        else:
            # Giữ tương thích với fake client trong test/tích hợp cũ.
            answer = generation
            answer_model = llm_config.model
            answer_provider = llm_config.provider
        return ChatResponse(
            status="answered",
            answer=answer,
            data_source="documents",
            sources=sources,
            retrieved_content=retrieval_content,
            retrieval_elapsed_ms=retrieval.get("elapsed_ms"),
            model=answer_model,
            llm_provider=answer_provider,
        )

    async def _answer_products(
        self,
        request: ChatRequest,
        *,
        provider_name,
    ) -> ChatResponse:
        search_result = await self.product_service.search_for_question(
            request.query
        )
        products = search_result.products
        if not products:
            return ChatResponse(
                status="insufficient_context",
                answer=(
                    "Tôi chưa tìm thấy sản phẩm phù hợp. "
                    "Hãy cung cấp mã sản phẩm hoặc tên sản phẩm cụ thể hơn."
                ),
                data_source="products",
                product_sources=[],
                product_result=search_result.result,
                llm_provider=provider_name,
            )

        context = build_product_context(
            products,
            request.query,
            search_result.result,
        )
        generation = await self.llm_client.generate_answer(
            system_prompt=load_product_prompt(),
            query=request.query,
            history=[item.model_dump() for item in request.history],
            context=context,
            sources=[],
            provider=request.ai_provider,
        )
        if isinstance(generation, LlmAnswer):
            answer = generation.text
            answer_model = generation.model
            answer_provider = generation.provider
        else:
            answer = generation
            answer_model = None
            answer_provider = provider_name

        return ChatResponse(
            status="answered",
            answer=answer,
            data_source="products",
            sources=[],
            product_sources=products,
            product_result=search_result.result,
            retrieved_content=context,
            model=answer_model,
            llm_provider=answer_provider,
        )
