"""Secret-safe external schemas for tenant BYOK settings."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Purpose = Literal["generation", "embedding"]


class TenantAIProviderUpdate(BaseModel):
    provider: str = Field(min_length=2, max_length=32)
    model: str = Field(min_length=1, max_length=128)
    api_key: str | None = Field(default=None, min_length=8, max_length=512, repr=False)
    enabled: bool = True
    free_only: bool = True
    output_dimensions: int | None = Field(default=None, ge=1, le=4096)

    @field_validator("provider")
    @classmethod
    def provider_is_known(cls, value: str) -> str:
        if value not in {"deepseek", "openrouter", "voyage", "cohere"}:
            raise ValueError("unsupported_provider")
        return value

    @field_validator("model")
    @classmethod
    def model_is_bounded_identifier(cls, value: str) -> str:
        if (
            not value.strip()
            or any(char.isspace() for char in value)
            or "://" in value
            or "@" in value
        ):
            raise ValueError("invalid_model")
        return value

    @field_validator("api_key")
    @classmethod
    def key_is_not_blank(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or "\r" in value or "\n" in value):
            raise ValueError("invalid_api_key")
        return value

class TenantAIProviderResponse(BaseModel):
    purpose: Purpose
    provider: str
    model: str
    enabled: bool
    free_only: bool
    output_dimensions: int | None
    has_key: bool


class TenantAIProviderListResponse(BaseModel):
    providers: list[TenantAIProviderResponse]
