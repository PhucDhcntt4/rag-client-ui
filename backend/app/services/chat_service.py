
import asyncio
import re
from pathlib import Path

from app.clients.llm_client import LlmAnswer, LlmClient, LlmServiceError
from app.clients.rag_client import RagClient
from app.config import Settings
from app.schemas import ChatRequest, ChatResponse, ChatSource, SourceAsset
from app.services.conversation_resolver import resolve_conversation_query
from app.services.access_control import DocumentAccess
from app.services.product_service import ProductService, build_product_context
from app.services.query_router import resolve_product_query


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

    async def answer(
        self,
        request: ChatRequest,
        access: DocumentAccess | None = None,
    ) -> ChatResponse:
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
        retrieval_query = request.query
        if data_source == "auto":
            resolution = await resolve_conversation_query(
                query=request.query,
                history=request.history,
                llm_client=self.llm_client,
                provider=request.ai_provider,
                has_document_scope=bool(
                    request.doc_type_id or request.group_ids
                ),
            )
            data_source = resolution.data_source
            retrieval_query = resolution.standalone_query
        elif data_source == "products":
            retrieval_query = resolve_product_query(
                request.query,
                request.history,
            )

        if data_source == "products":
            return await self._answer_products(
                request,
                provider_name=llm_config.provider,
                retrieval_query=retrieval_query,
            )

        retrieval = await self._search_documents(
            request,
            retrieval_query,
            access,
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

    async def _search_documents(
        self,
        request: ChatRequest,
        query: str,
        access: DocumentAccess | None,
    ) -> dict:
        if access is None or access.unrestricted:
            return await self.rag_client.search(
                query,
                doc_type_id=request.doc_type_id,
                group_ids=request.group_ids,
                top_k=request.top_k,
            )
        if not access.has_access:
            return {
                "success": False,
                "status": "knowledge_not_found",
                "content": "",
                "sources": [],
                "elapsed_ms": 0,
            }

        if request.doc_type_id is not None:
            if request.doc_type_id in access.doc_type_ids:
                return await self.rag_client.search(
                    query,
                    doc_type_id=request.doc_type_id,
                    group_ids=request.group_ids,
                    top_k=request.top_k,
                )

            allowed_groups = access.groups_for_doc_type(request.doc_type_id)
            requested_groups = set(request.group_ids or allowed_groups)
            if not requested_groups or not requested_groups.issubset(
                allowed_groups
            ):
                return {
                    "success": False,
                    "status": "knowledge_not_found",
                    "content": "",
                    "sources": [],
                    "elapsed_ms": 0,
                }
            return await self.rag_client.search(
                query,
                doc_type_id=request.doc_type_id,
                group_ids=sorted(requested_groups),
                top_k=request.top_k,
            )

        if request.group_ids:
            requested_groups = set(request.group_ids)
            if not requested_groups.issubset(access.group_ids):
                return {
                    "success": False,
                    "status": "knowledge_not_found",
                    "content": "",
                    "sources": [],
                    "elapsed_ms": 0,
                }
            return await self.rag_client.search(
                query,
                group_ids=sorted(requested_groups),
                top_k=request.top_k,
            )

        searches = [
            self.rag_client.search(
                query,
                doc_type_id=doc_type_id,
                top_k=request.top_k,
            )
            for doc_type_id in sorted(access.doc_type_ids)
        ]
        if access.group_ids:
            searches.append(
                self.rag_client.search(
                    query,
                    group_ids=sorted(access.group_ids),
                    top_k=request.top_k,
                )
            )
        results = await asyncio.gather(*searches)
        successful = [
            result
            for result in results
            if result.get("success")
            and result.get("status") != "knowledge_not_found"
        ]
        if not successful:
            return {
                "success": False,
                "status": "knowledge_not_found",
                "content": "",
                "sources": [],
                "elapsed_ms": sum(
                    float(result.get("elapsed_ms") or 0)
                    for result in results
                ),
            }
        return {
            "success": True,
            "status": "knowledge_found",
            "content": "\n\n".join(
                str(result.get("content") or "")
                for result in successful
                if result.get("content")
            ),
            "sources": [
                source
                for result in successful
                for source in result.get("sources", [])
            ],
            "elapsed_ms": sum(
                float(result.get("elapsed_ms") or 0)
                for result in results
            ),
        }

    async def _answer_products(
        self,
        request: ChatRequest,
        *,
        provider_name,
        retrieval_query: str | None = None,
    ) -> ChatResponse:
        product_query = retrieval_query or resolve_product_query(
            request.query,
            request.history,
        )
        search_result = await self.product_service.search_for_question(
            product_query
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

        answer_context = await self.product_service.load_latest_answer_context(
            product_query,
            search_result,
        )
        context = build_product_context(
            answer_context.products,
            product_query,
            answer_context.result,
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
