from dataclasses import dataclass
from datetime import timedelta, timezone, tzinfo
from functools import lru_cache
from pathlib import Path
import re
from typing import Literal

from pydantic import Field, SecretStr, field_validator  # type: ignore
from pydantic_settings import BaseSettings, SettingsConfigDict  # type: ignore


BACKEND_ROOT = Path(__file__).resolve().parents[1]
AiProvider = Literal["openai", "gemini"]


@dataclass(frozen=True)
class AiProviderConfig:
    provider: AiProvider
    base_url: str
    api_key: SecretStr
    model: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "RAG Client Backend"
    app_env: Literal["development", "production", "test"] = "development"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8100, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    frontend_origin: str = "http://127.0.0.1:5500"

    rag_base_url: str
    rag_search_api_key: SecretStr
    rag_admin_api_key: SecretStr
    rag_timeout_seconds: float = Field(default=45, gt=0, le=300)
    rag_top_k: int = Field(default=8, ge=1, le=20)

    product_timezone_offset: str
    product_chat_page_size: int = Field(ge=1, le=50)
    product_candidate_page_size: int = Field(ge=1, le=50)

    product_image_search_enabled: bool = False
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: SecretStr | None = None
    product_image_collection: str = Field(
        default="bot_product_images_clip_v2",
        pattern=r"^[A-Za-z0-9._-]{1,255}$",
    )
    product_clip_model: str = "ViT-B-32"
    product_clip_pretrained: str = "laion2b_s34b_b79k"
    product_clip_device: str = "auto"
    product_image_max_bytes: int = Field(
        default=8 * 1024 * 1024,
        ge=1024,
        le=20 * 1024 * 1024,
    )
    product_image_result_limit: int = Field(default=8, ge=1, le=20)
    product_image_candidate_limit: int = Field(default=50, ge=1, le=200)
    product_image_min_score: float = Field(default=0.25, ge=0, le=1)

    # Pipeline Gemini Vision được phát triển sau feature flag này. Khi tắt,
    # luồng OpenCLIP + Qdrant hiện tại tiếp tục hoạt động như trước.
    product_vision_enabled: bool = False
    product_vision_model: str | None = None
    product_vision_timeout_seconds: float = Field(default=45, gt=0, le=180)
    product_vision_verify_top_k: int = Field(default=5, ge=1, le=10)
    product_vision_original_candidate_slots: int = Field(default=2, ge=1, le=10)
    product_visual_verification_enabled: bool = False
    product_reference_image_timeout_seconds: float = Field(
        default=15,
        gt=0,
        le=60,
    )
    product_reference_image_max_bytes: int = Field(
        default=6 * 1024 * 1024,
        ge=1024,
        le=20 * 1024 * 1024,
    )
    product_image_fast_accept_score: float = Field(default=0.88, ge=0, le=1)
    product_image_fast_accept_margin: float = Field(default=0.08, ge=0, le=1)
    product_image_vector_weight: float = Field(default=0.55, ge=0, le=1)
    product_image_visual_weight: float = Field(default=0.45, ge=0, le=1)
    product_image_verify_min_score: float = Field(default=0.65, ge=0, le=1)
    product_image_visual_min_score: float = Field(default=0.50, ge=0, le=1)
    product_image_high_confidence: float = Field(default=0.82, ge=0, le=1)
    product_image_medium_confidence: float = Field(default=0.65, ge=0, le=1)

    ai_provider: AiProvider | None = None
    ai_fallback_provider: AiProvider | None = None

    gemini_api_key: SecretStr | None = None
    gemini_model: str | None = None
    gemini_base_url: str | None = None

    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    openai_base_url: str | None = None

    llm_timeout_seconds: float = Field(default=90, gt=0, le=600)

    # Tương thích .env cũ; có thể xóa sau khi chuyển sang bộ biến AI_* mới.
    llm_provider: Literal["openai_compatible", "openai", "gemini"] | None = None
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None

    @field_validator("frontend_origin", "rag_base_url", "qdrant_url")
    @classmethod
    def normalize_required_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("URL phải bắt đầu bằng http:// hoặc https://")
        return normalized

    @field_validator(
        "gemini_base_url",
        "openai_base_url",
        "llm_base_url",
        mode="before",
    )
    @classmethod
    def normalize_optional_url(cls, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        normalized = str(value).strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("URL phải bắt đầu bằng http:// hoặc https://")
        return normalized

    @field_validator("rag_search_api_key", "rag_admin_api_key", mode="before")
    @classmethod
    def validate_rag_key(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("RAG API key không được để trống")
        return value.strip()

    @field_validator("product_timezone_offset")
    @classmethod
    def validate_product_timezone_offset(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"[+-](?:0\d|1[0-4]):[0-5]\d", normalized):
            raise ValueError(
                "PRODUCT_TIMEZONE_OFFSET phải có dạng +07:00 hoặc -05:30"
            )
        return normalized

    @field_validator("product_clip_model", "product_clip_pretrained")
    @classmethod
    def validate_required_product_image_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Cấu hình OpenCLIP không được để trống")
        return normalized

    @field_validator("product_clip_device")
    @classmethod
    def validate_product_clip_device(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"(?:auto|cpu|mps|cuda(?::\d+)?)", normalized):
            raise ValueError(
                "PRODUCT_CLIP_DEVICE phải là auto, cpu, mps, cuda hoặc cuda:<số>"
            )
        return normalized

    @property
    def product_timezone(self) -> tzinfo:
        sign = 1 if self.product_timezone_offset[0] == "+" else -1
        hours, minutes = map(int, self.product_timezone_offset[1:].split(":"))
        return timezone(sign * timedelta(hours=hours, minutes=minutes))

    @property
    def primary_ai_provider(self) -> AiProvider:
        if self.ai_provider:
            return self.ai_provider
        if self.llm_provider in {"openai", "openai_compatible"}:
            return "openai"
        return "gemini"

    def ai_provider_chain(self) -> list[AiProvider]:
        chain = [self.primary_ai_provider]
        if (
            self.ai_fallback_provider
            and self.ai_fallback_provider != self.primary_ai_provider
        ):
            chain.append(self.ai_fallback_provider)
        return chain

    def get_ai_provider_config(self, provider: AiProvider) -> AiProviderConfig:
        using_legacy = (
            self.llm_provider == provider
            or (
                provider == "openai"
                and self.llm_provider == "openai_compatible"
            )
        )

        if provider == "gemini":
            base_url = self.gemini_base_url or (
                self.llm_base_url if using_legacy else None
            ) or "https://generativelanguage.googleapis.com/v1beta"
            api_key = self.gemini_api_key or (
                self.llm_api_key if using_legacy else None
            )
            model = self.gemini_model or (
                self.llm_model if using_legacy else None
            ) or "gemini-3.5-flash-lite"
        else:
            base_url = self.openai_base_url or (
                self.llm_base_url if using_legacy else None
            ) or "https://api.openai.com/v1"
            api_key = self.openai_api_key or (
                self.llm_api_key if using_legacy else None
            )
            model = self.openai_model or (
                self.llm_model if using_legacy else None
            ) or "gpt-4.1-mini"

        if api_key is None or not api_key.get_secret_value().strip():
            variable = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
            raise ValueError(
                f"Provider '{provider}' chưa được cấu hình {variable}"
            )

        return AiProviderConfig(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model.strip(),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
