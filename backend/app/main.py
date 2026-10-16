from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request  # type: ignore
from fastapi.middleware.cors import CORSMiddleware  # type: ignore
from fastapi.responses import FileResponse, JSONResponse  # type: ignore
from fastapi.staticfiles import StaticFiles  # type: ignore

from app.clients.gemini_vision_client import GeminiVisionClient
from app.clients.image_embedder import ProductImageEmbedder
from app.clients.llm_client import LlmClient, LlmServiceError
from app.clients.product_visual_verifier import ProductVisualVerifier
from app.clients.qdrant_image_client import QdrantImageClient
from app.clients.rag_client import RagClient, RagServiceError
from app.config import get_settings
from app.logging_config import configure_application_logging
from app.routers.assets import router as assets_router
from app.routers.ai import router as ai_router
from app.routers.chat import router as chat_router
from app.routers.documents import router as documents_router
from app.routers.health import router as health_router
from app.routers.products import router as products_router
from app.routers.taxonomy import router as taxonomy_router
from app.services.chat_service import ChatService
from app.services.document_service import DocumentService
from app.services.image_processing_service import ImageProcessingService
from app.services.product_image_decision import ProductImageDecisionEngine
from app.services.product_image_downloader import ProductImageDownloader
from app.services.product_image_service import ProductImageService
from app.services.product_service import ProductService

FRONTEND_ROOT = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()
    rag_client = RagClient(settings)
    llm_client = LlmClient(settings)
    product_service = ProductService(
        rag_client,
        product_timezone=settings.product_timezone,
        chat_page_size=settings.product_chat_page_size,
        candidate_page_size=settings.product_candidate_page_size,
    )
    qdrant_image_client = QdrantImageClient(
        base_url=settings.qdrant_url,
        collection=settings.product_image_collection,
        api_key=(
            settings.qdrant_api_key.get_secret_value()
            if settings.qdrant_api_key
            else None
        ),
        timeout=settings.rag_timeout_seconds,
    )
    gemini_config = None
    if (
        settings.product_vision_enabled
        or settings.product_visual_verification_enabled
    ):
        gemini_config = settings.get_ai_provider_config("gemini")

    gemini_vision_client = None
    if settings.product_vision_enabled and gemini_config is not None:
        gemini_vision_client = GeminiVisionClient(
            api_key=gemini_config.api_key.get_secret_value(),
            model=settings.product_vision_model or gemini_config.model,
            base_url=gemini_config.base_url,
            timeout=settings.product_vision_timeout_seconds,
        )

    visual_verifier = None
    image_downloader = None
    decision_engine = None
    if settings.product_visual_verification_enabled and gemini_config is not None:
        visual_verifier = ProductVisualVerifier(
            api_key=gemini_config.api_key.get_secret_value(),
            model=settings.product_vision_model or gemini_config.model,
            base_url=gemini_config.base_url,
            timeout=settings.product_vision_timeout_seconds,
        )
        image_downloader = ProductImageDownloader(
            max_bytes=settings.product_reference_image_max_bytes,
            timeout=settings.product_reference_image_timeout_seconds,
        )
        decision_engine = ProductImageDecisionEngine(
            vector_weight=settings.product_image_vector_weight,
            visual_weight=settings.product_image_visual_weight,
            verify_min_score=settings.product_image_verify_min_score,
            visual_min_score=settings.product_image_visual_min_score,
            high_confidence=settings.product_image_high_confidence,
            medium_confidence=settings.product_image_medium_confidence,
        )

    product_image_service = ProductImageService(
        settings,
        ProductImageEmbedder(
            model_name=settings.product_clip_model,
            pretrained=settings.product_clip_pretrained,
            device=settings.product_clip_device,
        ),
        qdrant_image_client,
        rag_client,
        vision_client=gemini_vision_client,
        image_processor=ImageProcessingService(),
        visual_verifier=visual_verifier,
        image_downloader=image_downloader,
        decision_engine=decision_engine,
    )
    application.state.rag_client = rag_client
    application.state.product_service = product_service
    application.state.product_image_service = product_image_service
    application.state.document_service = DocumentService(rag_client)
    application.state.chat_service = ChatService(
        settings,
        rag_client,
        llm_client,
        product_service,
    )
    try:
        yield
    finally:
        await llm_client.close()
        if gemini_vision_client is not None:
            await gemini_vision_client.close()
        if visual_verifier is not None:
            await visual_verifier.close()
        if image_downloader is not None:
            await image_downloader.close()
        await qdrant_image_client.close()
        await rag_client.close()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_application_logging(settings.log_level)
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Backend kết nối RAG Service với LLM riêng.",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    application.include_router(health_router)
    application.include_router(ai_router)
    application.include_router(assets_router)
    application.include_router(documents_router)
    application.include_router(taxonomy_router)
    application.include_router(chat_router)
    application.include_router(products_router)
    application.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_ROOT / "assets"),
        name="assets",
    )
    application.mount(
        "/js",
        StaticFiles(directory=FRONTEND_ROOT / "js"),
        name="js",
    )

    @application.exception_handler(RagServiceError)
    async def rag_error(_request: Request, exc: RagServiceError):
        status_code = 404 if exc.status_code == 404 else 503
        headers = {"Retry-After": exc.retry_after} if exc.retry_after else None
        return JSONResponse(
            {"detail": str(exc)},
            status_code=status_code,
            headers=headers,
        )

    @application.exception_handler(LlmServiceError)
    async def llm_error(_request: Request, exc: LlmServiceError):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @application.get("/", include_in_schema=False)
    def root():
        return FileResponse(FRONTEND_ROOT / "index.html")

    return application


app = create_app()
