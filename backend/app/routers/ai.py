from fastapi import APIRouter, Depends

from app.config import AiProvider, Settings, get_settings
from app.schemas import AiProviderInfo, AiProvidersResponse


router = APIRouter(prefix="/api/ai", tags=["AI"])

PROVIDER_LABELS = {
    "gemini": "Gemini",
    "openai": "OpenAI",
}


def provider_info(
    settings: Settings,
    provider: AiProvider,
) -> AiProviderInfo:
    try:
        config = settings.get_ai_provider_config(provider)
        model = config.model
        available = True
    except ValueError:
        model = (
            settings.gemini_model or "gemini-3.5-flash-lite"
            if provider == "gemini"
            else settings.openai_model or "gpt-4.1-mini"
        )
        available = False
    return AiProviderInfo(
        id=provider,
        label=PROVIDER_LABELS[provider],
        model=model,
        available=available,
    )


@router.get("/providers", response_model=AiProvidersResponse)
def list_ai_providers(
    settings: Settings = Depends(get_settings),
) -> AiProvidersResponse:
    providers = [
        provider_info(settings, "gemini"),
        provider_info(settings, "openai"),
    ]
    available = [item.id for item in providers if item.available]
    default = (
        settings.primary_ai_provider
        if settings.primary_ai_provider in available or not available
        else available[0]
    )
    return AiProvidersResponse(default=default, providers=providers)
