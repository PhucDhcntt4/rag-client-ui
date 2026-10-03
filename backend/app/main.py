from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request # type: ignore
from fastapi.middleware.cors import CORSMiddleware# type: ignore
from fastapi.responses import FileResponse, JSONResponse# type: ignore
from fastapi.staticfiles import StaticFiles# type: ignore

from app.clients.llm_client import LlmClient, LlmServiceError
from app.clients.rag_client import RagClient, RagServiceError
from app.config import get_settings
from app.routers.assets import router as assets_router
from app.routers.chat import router as chat_router
from app.routers.documents import router as documents_router
from app.routers.health import router as health_router
from app.routers.taxonomy import router as taxonomy_router
from app.services.chat_service import ChatService
from app.services.document_service import DocumentService


FRONTEND_ROOT = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()
    rag_client = RagClient(settings)
    llm_client = LlmClient(settings)
    application.state.rag_client = rag_client
    application.state.document_service = DocumentService(rag_client)
    application.state.chat_service = ChatService(settings, rag_client, llm_client)
    try:
        yield
    finally:
        await llm_client.close()
        await rag_client.close()


def create_app() -> FastAPI:
    settings = get_settings()
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
    application.include_router(assets_router)
    application.include_router(documents_router)
    application.include_router(taxonomy_router)
    application.include_router(chat_router)
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
