"""Closed catalog and invariants for user-facing generation providers.

Only identifiers from this module may be persisted by the superadmin API.
Endpoints and credentials remain server-owned configuration and are never
accepted from or returned to the browser.
"""

from __future__ import annotations

from dataclasses import dataclass

DEEPSEEK_ROUTE_ID = "deepseek"
QWEN38_ROUTE_ID = "qwen38_flash_next"
GLM53_ROUTE_ID = "glm53_flash"

DEFAULT_GENERATION_MODEL_ORDER = (
    DEEPSEEK_ROUTE_ID,
    QWEN38_ROUTE_ID,
    GLM53_ROUTE_ID,
)


@dataclass(frozen=True)
class GenerationModelCatalogEntry:
    id: str
    provider: str
    display_name: str
    is_required: bool = False


GENERATION_MODEL_CATALOG = {
    DEEPSEEK_ROUTE_ID: GenerationModelCatalogEntry(
        id=DEEPSEEK_ROUTE_ID,
        provider="deepseek",
        display_name="DeepSeek",
        is_required=True,
    ),
    QWEN38_ROUTE_ID: GenerationModelCatalogEntry(
        id=QWEN38_ROUTE_ID,
        provider="custom:qwen38-flash-next",
        display_name="Qwen 3.8 Flash Next",
    ),
    GLM53_ROUTE_ID: GenerationModelCatalogEntry(
        id=GLM53_ROUTE_ID,
        provider="glm53-flash-asus",
        display_name="GLM 5.3 Flash",
    ),
}


def validate_generation_model_order(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Return a validated immutable route or raise a stable error code."""
    order = tuple(values)
    if not order:
        raise ValueError("generation_model_order_empty")
    if len(order) != len(set(order)):
        raise ValueError("generation_model_order_duplicates")
    unknown = set(order) - set(GENERATION_MODEL_CATALOG)
    if unknown:
        raise ValueError("generation_model_order_unknown")
    if order[0] != DEEPSEEK_ROUTE_ID:
        raise ValueError("generation_model_order_deepseek_first")
    return order
