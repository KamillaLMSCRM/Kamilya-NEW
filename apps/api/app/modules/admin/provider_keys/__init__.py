"""Provider API keys management (superadmin only).

Allows the platform operator (Askar) to manage API keys for cloud
providers (DeepSeek, Voyage, future OpenRouter) via the admin UI instead
of editing environment variables. Keys are encrypted at rest with Fernet.

For v1.0 only global keys (tenant_id NULL) are exposed in the UI.
Per-tenant override is intentionally not in scope.
"""

from app.modules.admin.provider_keys.models import ProviderKey
from app.modules.admin.provider_keys.schemas import (
    ProviderKeyCreate,
    ProviderKeyListResponse,
    ProviderKeyResponse,
    ProviderKeyTestResult,
    ProviderKeyUpdate,
)
from app.modules.admin.provider_keys.service import ProviderKeyService

__all__ = [
    "ProviderKey",
    "ProviderKeyCreate",
    "ProviderKeyListResponse",
    "ProviderKeyResponse",
    "ProviderKeyService",
    "ProviderKeyTestResult",
    "ProviderKeyUpdate",
]