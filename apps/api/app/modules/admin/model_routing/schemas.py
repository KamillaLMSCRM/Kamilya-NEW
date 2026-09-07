"""Public, secret-free contracts for generation-model routing."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.modules.admin.model_routing.catalog import validate_generation_model_order


class GenerationModelRouteItem(BaseModel):
    id: str
    provider: str
    display_name: str
    model: str
    is_enabled: bool
    position: int | None
    is_required: bool
    is_configured: bool


class GenerationModelRoutingResponse(BaseModel):
    revision: int
    models: list[GenerationModelRouteItem]
    updated_at: datetime


class GenerationModelRoutingUpdate(BaseModel):
    revision: int = Field(..., ge=1)
    ordered_model_ids: list[str] = Field(..., min_length=1, max_length=3)

    @field_validator("ordered_model_ids")
    @classmethod
    def validate_order(cls, value: list[str]) -> list[str]:
        try:
            return list(validate_generation_model_order(value))
        except ValueError as exc:
            raise ValueError(str(exc)) from None
