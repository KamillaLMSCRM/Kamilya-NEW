import ipaddress
import json
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    APP_NAME: str = "Kamilya LMS"
    APP_ENV: str = "development"
    # APP_ENV controls application behavior. These fields identify the actual
    # deployment and release so monitors cannot mistake a legacy provider for
    # the authoritative KZ runtime.
    DEPLOYMENT_ENVIRONMENT: str = "local"
    RELEASE_SHA: str = ""
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"
    # Disables new approval-workflow requests while retaining immutable
    # revisions and audit history for rollback/forensics.
    COURSE_APPROVAL_WORKFLOW_ENABLED: bool = True

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
    ASSIGNMENT_RECOVERY_DATABASE_URL: str = ""
    CANDIDATE_RETENTION_DATABASE_URL: str = ""
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_TIMEOUT: int = 10
    DB_POOL_RECYCLE_SECONDS: int = 1800

    @field_validator(
        "DATABASE_URL",
        "MIGRATION_DATABASE_URL",
        "ASSIGNMENT_RECOVERY_DATABASE_URL",
        "CANDIDATE_RETENTION_DATABASE_URL",
        mode="before",
    )
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
    # Browser-session policy is intentionally separate from CORS. Production
    # uses the same-site KZ app/API topology; legacy cross-site development
    # must opt in explicitly and cannot be enabled in production.
    AUTH_BROWSER_ORIGINS: list[str] = ["https://app.kml.kz"]
    AUTH_COOKIE_PROFILE: Literal["same_site", "cross_site"] = "same_site"
    AUTH_COOKIE_SECURE: bool = True
    AUTH_REFRESH_BODY_FALLBACK: bool = False
    # No-email assignment sessions remain memory-only access tokens: unlike a
    # normal login they never receive a refresh cookie. Keep the bounded TTL
    # long enough to complete a course without turning the copied credential
    # into a long-lived session.
    ASSIGNMENT_ACCESS_SESSION_MINUTES: int = Field(default=240, ge=30, le=480)

    # Legacy MinIO endpoint metadata. The application has no MinIO credential
    # consumer; local object-store root credentials belong only to Compose and
    # must never be embedded in application defaults.
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_BUCKET: str = "lms-content"
    MINIO_USE_SSL: bool = False

    # Free private vLLM pool for user-facing generation. These endpoints are
    # reachable only from the approved WireGuard/VPS contour. Keep the pool
    # disabled on Render or any runtime without that route: the managed
    # DeepSeek/public-Qwen chain remains available as the fallback.
    FREE_LLM_POOL_ENABLED: bool = False
    FREE_LLM_QWEN38_URL: str = "http://10.66.66.30:8002/v1"
    FREE_LLM_QWEN38_MODEL: str = "orcarouter/Qwen3.8-27B-Uncensored-NVFP4"
    FREE_LLM_QWEN4_URL: str = "http://10.66.66.31:8003/v1"
    FREE_LLM_QWEN4_MODEL: str = "assessment/Qwen3.5-4B-FP8-dynamic"
    FREE_LLM_THINKINGCAP_URL: str = "http://10.66.66.20:8000/v1"
    FREE_LLM_THINKINGCAP_MODEL: str = "morosystems/ThinkingCap-Qwen3.6-27B-NVFP4"
    FREE_LLM_NVFP4_URL: str = "http://10.66.66.15:8000/v1"
    FREE_LLM_NVFP4_MODEL: str = "nvidia/Qwen3.6-35B-A3B-NVFP4"
    FREE_LLM_CONNECT_TIMEOUT_SECONDS: float = Field(default=3.0, ge=1.0, le=15.0)
    FREE_LLM_REQUEST_TIMEOUT_SECONDS: float = Field(default=600.0, ge=30.0, le=900.0)

    # Qwen 35B AWQ is the third free model and the established self-hosted
    # provider. It is deliberately reused rather than added to the chain a
    # second time under another name.
    QWEN_API_URL: str = "https://qwen.kml.kz/v1"
    QWEN_EMBEDDING_URL: str = "https://qwen-embed.kml.kz/v1"
    EMBEDDING_URL: str = "https://qwen-embed.kml.kz/v1"
    EMBEDDING_DIMENSIONS: int = 4096
    LLM_API_URL: str = "https://qwen.kml.kz/v1"

    # LLM
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit"

    # DeepSeek — owner-selected primary provider. Activated when
    # DEEPSEEK_API_KEY is set. The private production contour falls back to
    # Qwen 27B and then Qwen 4B. Pricing (per 1M tokens, July 2026):
    #   deepseek-v4-flash  $0.14 in / $0.28 out
    #   deepseek-v4-pro    $0.435 in / $0.87 out
    # Endpoint is OpenAI-compatible (https://api.deepseek.com/v1).
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-v4-flash"

    # Voyage AI — primary managed embeddings provider. Endpoint is OpenAI-compatible
    # (https://api.voyageai.com/v1). Free tier: 200M tokens per account for
    # voyage-4-lite/voyage-4/voyage-context-3. Activated only when
    # VOYAGE_API_KEY is set; Qwen embeddings remain the fallback.
    #   voyage-4-lite        $0.02/M  (free up to 200M)
    #   voyage-4             $0.06/M  (free up to 200M)
    #   voyage-multilingual-2 $0.12/M (free up to 50M)
    VOYAGE_API_KEY: str = ""
    VOYAGE_BASE_URL: str = "https://api.voyageai.com/v1"
    VOYAGE_MODEL: str = "voyage-4-lite"

    # Cohere managed embeddings fallback. Its API uses the native v2
    # /embed schema rather than the OpenAI-compatible /embeddings schema.
    COHERE_API_KEY: str = ""
    COHERE_BASE_URL: str = "https://api.cohere.com/v2"
    COHERE_EMBED_MODEL: str = "embed-v4.0"

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = ""
    # Must be configured explicitly in every environment where Telegram is
    # enabled. The webhook endpoint requires the matching
    # X-Telegram-Bot-Api-Secret-Token header; the server never logs or
    # autogenerates this secret.
    TELEGRAM_WEBHOOK_SECRET: str = ""

    # Email
    # Provider values: "log" (default, no external delivery), "resend", or
    # "smtp". SMTP defaults match the project mail server but credentials must
    # always be supplied by the active environment.
    EMAIL_PROVIDER: str = "log"
    RESEND_API_KEY: str = ""
    EMAIL: str = ""
    EMAIL_PASSWORD: str = ""
    SMTP_HOST: str = "mail.kml.kz"
    SMTP_PORT: int = 465
    SMTP_USE_SSL: bool = True
    EMAIL_FROM: str = "Kamilya LMS <no-reply@notify.kml.kz>"
    SUPPORT_EMAIL: str = "support@kml.kz"
    # Optional operator copies of every successfully stored public website lead
    # and self-service trial registration. Accepts comma- or semicolon-separated
    # recipients; keep empty outside explicitly configured environments.
    PUBLIC_LEAD_NOTIFICATION_EMAIL: str = ""

    # CRM webhook is deliberately optional: absent configuration keeps durable
    # lead events observable and pending, never rejects public lead capture.
    CRM_WEBHOOK_URL: str = ""
    CRM_WEBHOOK_HEALTH_URL: str = ""
    CRM_WEBHOOK_SECRET: str = ""

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
        "https://kamilya-lms-dev.vercel.app",
        "https://app.kml.kz",
        "https://www.kml.kz",
    ]

    @field_validator("CORS_ORIGINS", "AUTH_BROWSER_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [origin.strip() for origin in v.split(",")]
        return v

    @model_validator(mode="after")
    def validate_security_settings(self):
        if not self.JWT_SECRET:
            raise ValueError("JWT_SECRET is required. Set it in .env or environment variables.")
        if len(self.JWT_SECRET) < 32:
            raise ValueError(
                f"JWT_SECRET must be at least 32 characters (got {len(self.JWT_SECRET)}). "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        if self.JWT_ALGORITHM not in ("HS256", "HS384", "HS512"):
            raise ValueError(
                f"JWT_ALGORITHM='{self.JWT_ALGORITHM}' is not allowed. "
                "Only symmetric HMAC algorithms are permitted (HS256/HS384/HS512). "
                "Asymmetric keys (RS256, ES256) and 'none' are rejected."
            )
        for field_name in ("CRM_WEBHOOK_URL", "CRM_WEBHOOK_HEALTH_URL"):
            endpoint = getattr(self, field_name)
            if not endpoint:
                continue
            parsed = urlsplit(endpoint)
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                raise ValueError(f"{field_name} must use an HTTP(S) URL with a hostname")
            if parsed.username or parsed.password:
                raise ValueError(f"{field_name} must not contain credentials")
            if parsed.query or parsed.fragment:
                raise ValueError(f"{field_name} must not contain a query or fragment")
            if self.APP_ENV.lower() == "production" and parsed.scheme.lower() != "https":
                raise ValueError(f"{field_name} must use HTTPS in production")
            if self.APP_ENV.lower() == "production":
                if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
                    raise ValueError(f"{field_name} must not target a private or non-public host")
                try:
                    address = ipaddress.ip_address(parsed.hostname)
                except ValueError:
                    address = None
                if address is not None and not address.is_global:
                    raise ValueError(f"{field_name} must not target a private or non-public host")
        if self.APP_ENV.lower() == "production" and self.CRM_WEBHOOK_SECRET and len(self.CRM_WEBHOOK_SECRET) < 32:
            raise ValueError("CRM_WEBHOOK_SECRET must be at least 32 characters in production")
        if self.APP_ENV.lower() == "production":
            if self.SCORM_CONTENT_ORIGIN:
                scorm = urlsplit(self.SCORM_CONTENT_ORIGIN)
                if scorm.scheme != "https":
                    raise ValueError("SCORM_CONTENT_ORIGIN must use HTTPS in production")
                public = urlsplit(self.PUBLIC_URL.rstrip("/"))
                if (scorm.scheme.lower(), scorm.netloc.lower()) == (public.scheme.lower(), public.netloc.lower()):
                    raise ValueError("SCORM_CONTENT_ORIGIN must be a separate origin from PUBLIC_URL")
        return self

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # Transactional tenant admission for course-generation jobs. Queue
    # position is tenant-relative; Celery has no reliable global position.
    AI_MAX_ACTIVE_JOBS_PER_TENANT: int = 2
    AI_WORKER_CONCURRENCY: int = 2
    AI_ESTIMATED_JOB_SECONDS: int = 510

    # Aggregate source budget for one multi-document generation: the sum of
    # indexed chunks across all selected documents must stay within this
    # limit so provider context stays bounded instead of silently truncating.
    AI_MULTI_DOC_MAX_TOTAL_CHUNKS: int = 4000

    @field_validator(
        "AI_MAX_ACTIVE_JOBS_PER_TENANT",
        "AI_WORKER_CONCURRENCY",
        "AI_ESTIMATED_JOB_SECONDS",
        "AI_MULTI_DOC_MAX_TOTAL_CHUNKS",
    )
    @classmethod
    def validate_positive_ai_capacity(cls, value: int) -> int:
        if value < 1:
            raise ValueError("AI capacity settings must be greater than zero")
        return value

    # Storage
    CERTIFICATE_STORAGE_DIR: str = "storage/certificates"

    # Dedicated, cookieless origin used exclusively for tenant-uploaded SCORM
    # HTML/JavaScript. Production routes only the scoped SCORM endpoints there;
    # it must never share app/API auth cookies or browser storage.
    SCORM_CONTENT_ORIGIN: str = ""

    @field_validator("SCORM_CONTENT_ORIGIN", mode="before")
    @classmethod
    def normalize_scorm_content_origin(cls, value):
        if value is None:
            return ""
        origin = str(value).strip().rstrip("/")
        if not origin:
            return ""
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("SCORM_CONTENT_ORIGIN must be an origin without credentials, path, query, or fragment")
        return origin

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

    # YouTube transcript import: bounded worker flow, disabled by default.
    YOUTUBE_IMPORT_ENABLED: bool = False
    YOUTUBE_INLINE_EXECUTION: bool = False
    YOUTUBE_MAX_VIDEO_DURATION_SECONDS: int = Field(default=7200, ge=60, le=7200)
    YOUTUBE_MAX_TOTAL_CHARS: int = Field(default=500_000, ge=1000, le=2_000_000)
    YOUTUBE_PROVIDER_TIMEOUT_SECONDS: float = Field(default=20.0, ge=3.0, le=60.0)
    # Optional authenticated caption relay. Development uses this when the
    # application host's public cloud IP is blocked by YouTube. The URL must
    # be HTTPS and the bearer token is stored only in environment secrets.
    YOUTUBE_CAPTION_SERVICE_URL: str = ""
    YOUTUBE_CAPTION_SERVICE_TOKEN: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
