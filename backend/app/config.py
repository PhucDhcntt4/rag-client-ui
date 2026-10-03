from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator # type: ignore
from pydantic_settings import BaseSettings, SettingsConfigDict# type: ignore


BACKEND_ROOT = Path(__file__).resolve().parents[1]


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

    llm_provider: Literal["openai_compatible", "gemini"] = "openai_compatible"
    llm_base_url: str
    llm_api_key: SecretStr
    llm_model: str
    llm_timeout_seconds: float = Field(default=90, gt=0, le=600)

    @field_validator(
        "frontend_origin",
        "rag_base_url",
        "llm_base_url",
    )
    @classmethod
    def normalize_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")

        if not normalized.startswith(("http://", "https://")):
            raise ValueError("URL phải bắt đầu bằng http:// hoặc https://")

        return normalized

    @field_validator(
        "rag_search_api_key",
        "rag_admin_api_key",
        mode="before",
    )
    @classmethod
    def validate_rag_key(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("RAG API key không được để trống")

        return value.strip()

    @field_validator("llm_model")
    @classmethod
    def validate_llm_model(cls, value: str) -> str:
        model = value.strip()

        if not model:
            raise ValueError("LLM_MODEL không được để trống")

        return model

    @field_validator("llm_api_key", mode="before")
    @classmethod
    def validate_llm_key(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("LLM_API_KEY không được để trống")
        normalized = value.strip()
        if normalized.startswith("GEMINI_API_KEY="):
            normalized = normalized.removeprefix("GEMINI_API_KEY=").strip()
        if not normalized:
            raise ValueError("LLM_API_KEY không được để trống")
        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings()
