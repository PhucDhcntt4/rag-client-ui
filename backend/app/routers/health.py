from fastapi import APIRouter # type: ignore

from app.config import get_settings


router = APIRouter(
    prefix="/api",
    tags=["Health"],
)


@router.get("/health")
def health():
    settings = get_settings()

    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
    }
