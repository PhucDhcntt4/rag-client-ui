"""Orchestrate retrieval and grounded answer generation."""

import re
from pathlib import Path

from app.clients.llm_client import LlmClient
from app.clients.rag_client import RagClient
from app.config import Settings
from app.schemas import ChatRequest, ChatResponse, ChatSource, SourceAsset


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "answer.txt"


def load_answer_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def limit_retrieval(retrieval: dict, limit: int) -> tuple[list[dict], str]:
    """Keep expanded section searches within the requested chunk limit."""
    sources = list(retrieval.get("sources") or [])[:limit]
    raw_context = str(retrieval.get("content") or "")
    parts = [
        part.strip()
        for part in re.split(r"(?=\[Nguồn:)", raw_context)
        if part.strip()
    ]
    if len(parts) >= len(sources) and all(
        part.startswith("[Nguồn:") for part in parts[:len(sources)]
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
    ):
        self.settings = settings
        self.rag_client = rag_client
        self.llm_client = llm_client

    async def answer(self, request: ChatRequest) -> ChatResponse:
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
                sources=[],
                retrieval_elapsed_ms=retrieval.get("elapsed_ms"),
                model=None,
            )

        source_limit = request.top_k or self.settings.rag_top_k
        retrieval_sources, retrieval_content = limit_retrieval(
            retrieval,
            source_limit,
        )
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
        answer = await self.llm_client.generate_answer(
            system_prompt=load_answer_prompt(),
            query=request.query,
            history=[item.model_dump() for item in request.history],
            context=retrieval_content,
            sources=[source.model_dump() for source in sources],
        )
        return ChatResponse(
            status="answered",
            answer=answer,
            sources=sources,
            retrieved_content=retrieval_content,
            retrieval_elapsed_ms=retrieval.get("elapsed_ms"),
            model=self.settings.llm_model,
        )
