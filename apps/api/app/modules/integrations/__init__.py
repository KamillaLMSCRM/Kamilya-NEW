"""Integrations module — per-tenant credentials for SMTP/Telegram/WhatsApp.

Exposes:
  - models: TenantIntegration, TenantIntegrationAudit
  - schemas: Pydantic request/response shapes
  - crypto: Fernet encrypt/decrypt for credentials at rest
  - wa_gateway_client: HTTP client for wa-gateway microservice
  - router: FastAPI endpoints (mounted at /api/v1/integrations)
"""