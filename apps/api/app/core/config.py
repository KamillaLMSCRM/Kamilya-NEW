import json
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from pydantic import field_validator, model_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    APP_NAME: str = "Kamilya LMS"
    APP_ENV: str = "development"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"

    # Demo-login flags removed in favor of the simpler rule:
    #   - non-production env: admin and superadmin demo-login always work.
    #   - production env: both are rejected with 404.
    # See apps/api/app/modules/auth/router.py::demo_login() for the
    # implementation. E2E tests added in commit 215158a cover this path
    # so we no longer need the env-var opt-in (audit §4.8).

    # Database
    # IMPORTANT: in production the URL must point at the `lms_app` role
    # (created by alembic migration 0033) and NOT at `postgres`. The
    # `postgres` user is a superuser and bypasses RLS even with FORCE
    # enabled. See docs/adr/0004-rls-force-and-app-role.md for the
    # operational checklist after migration.
    DATABASE_URL: str = "postgresql+asyncpg://lms:lms_dev_password_2026@localhost:5432/kamilya_lms"
    MIGRATION_DATABASE_URL: str = ""
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_TIMEOUT: int = 10
    DB_POOL_RECYCLE_SECONDS: int = 1800

    @field_validator("DATABASE_URL", "MIGRATION_DATABASE_URL", mode="before")
    @classmethod
    def fix_database_url(cls, v):
        if isinstance(v, str) and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        return v

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    # Bucket name as created in Supabase Dashboard -> Storage. Spaces are allowed
    # in bucket names; supabase-py handles URL-encoding internally.
    SUPABASE_BUCKET: str = "Kamilya LMS"
    SUPABASE_SIGNED_URL_TTL: int = 300  # seconds

    # Storage backend selector: "local" | "supabase". Falls back to local if
    # Supabase env vars are missing or init fails.
    STORAGE_BACKEND: str = "local"

    # JWT
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_AUDIENCE: str = "kamilya-lms"  # claimed in 'aud'; validated on every decode
    JWT_ISSUER: str = "kamilya-lms"  # claimed in 'iss'; validated on every decode
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # MinIO / S3
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin_secret_2026"
    MINIO_BUCKET: str = "lms-content"
    MINIO_USE_SSL: bool = False

    # Qwen (via Cloudflare tunnel) — primary LLM + embeddings provider
    QWEN_API_URL: str = "https://qwen.kml.kz/v1"
    QWEN_EMBEDDING_URL: str = "https://qwen-embed.kml.kz/v1"
    EMBEDDING_URL: str = "https://qwen-embed.kml.kz/v1"
    EMBEDDING_DIMENSIONS: int = 4096
    LLM_API_URL: str = "https://qwen.kml.kz/v1"

    # LLM
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit"

    # DeepSeek — LLM fallback (cost). Activated only when DEEPSEEK_API_KEY is set
    # and the primary Qwen endpoint fails. Pricing (per 1M tokens, June 2026):
    #   deepseek-v4-flash  $0.14 in / $0.28 out
    #   deepseek-v4-pro    $0.435 in / $0.87 out
    # Endpoint is OpenAI-compatible (https://api.deepseek.com/v1).
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-v4-flash"

    # Voyage AI — embeddings fallback. Endpoint is OpenAI-compatible
    # (https://api.voyageai.com/v1). Free tier: 200M tokens per account for
    # voyage-4-lite/voyage-4/voyage-context-3. Activated only when
    # VOYAGE_API_KEY is set and Qwen embeddings fail.
    #   voyage-4-lite        $0.02/M  (free up to 200M)
    #   voyage-4             $0.06/M  (free up to 200M)
    #   voyage-multilingual-2 $0.12/M (free up to 50M)
    VOYAGE_API_KEY: str = ""
    VOYAGE_BASE_URL: str = "https://api.voyageai.com/v1"
    VOYAGE_MODEL: str = "voyage-4-lite"

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = ""
    # If empty, the server generates a random secret at startup
    # (apps/api/app/core/config.py autogenerate logic). The webhook
    # endpoint always requires the X-Telegram-Bot-Api-Secret-Token
    # header to match. To set up the webhook with Telegram, call
    # setWebhook with the same secret — the secret is logged on
    # startup so you can copy it.
    TELEGRAM_WEBHOOK_SECRET: str = ""

    # Email
    # Provider values: "log" (default, no external delivery) or "resend".
    EMAIL_PROVIDER: str = "log"
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "Kamilya LMS <no-reply@notify.kml.kz>"


    # Observability (audit §9.4)
    # Sentry DSN — leave empty to disable Sentry entirely. When set,
    # app/main.py initializes the SDK with FastAPI + SQLAlchemy + asyncpg
    # integrations. PII (Authorization header, cookies, passwords) is
    # scrubbed via send_default_pii=False.
    SENTRY_DSN: str = ""

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "https://web-inky-three-48.vercel.app",
        "https://web-natt1inhm-kamillalmscrms-projects.vercel.app",
        "https://app.kml.kz",
        "https://www.kml.kz",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [origin.strip() for origin in v.split(",")]
        return v

    @model_validator(mode="after")
    def validate_jwt_secret(self):
        if not self.JWT_SECRET:
            raise ValueError("JWT_SECRET is required. Set it in .env or environment variables.")
        if len(self.JWT_SECRET) < 32:
            raise ValueError(
                f"JWT_SECRET must be at least 32 characters (got {len(self.JWT_SECRET)}). "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        if self.JWT_ALGORITHM not in ("HS256", "HS384", "HS512"):
            raise ValueError(
                f"JWT_ALGORITHM='{self.JWT_ALGORITHM}' is not allowed. "
                "Only symmetric HMAC algorithms are permitted (HS256/HS384/HS512). "
                "Asymmetric keys (RS256, ES256) and 'none' are rejected."
            )
        return self

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # Storage
    CERTIFICATE_STORAGE_DIR: str = "storage/certificates"

    # Public URL — used to build invite links (e.g. /accept-invite?token=...)
    # Defaults to app.kml.kz in production. Override in .env for staging.
    PUBLIC_URL: str = "https://app.kml.kz"

    # Encryption key for secrets stored in provider_keys table.
    # Fernet key (base64-encoded 32-byte key). Generate via:
    #     python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Loss of this key = all stored provider keys become unreadable.
    # Keep an offline backup in your password manager alongside other
    # production secrets.
    PROVIDER_KEY_ENCRYPTION_KEY: str = ""

    # Master encryption key for tenant_integrations.config_encrypted.
    # Same Fernet format as PROVIDER_KEY_ENCRYPTION_KEY.
    # Loss of this key = all tenant SMTP passwords / Telegram bot tokens
    # become unrecoverable. Tenants must re-enter. Backup required.
    MASTER_ENCRYPTION_KEY: str = ""

    # WhatsApp gateway — base URL of wa-gateway microservice.
    # Empty by default so dev environments without the gateway don't
    # crash. Production sets this to http://wa.kml.kz (or https if
    # Cloudflare proxy terminates TLS).
    WA_GATEWAY_URL: str = ""

    # Shared JWT secret for wa-gateway authentication. Must match the
    # KAMILYA_BACKEND_SECRET on the wa-gateway VPS.
    KAMILYA_BACKEND_SECRET: str = ""


@lru_cache()
def get_settings() -> Settings:
    return Settings()
