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

    # TEMP: enable admin demo-login in production for e2e testing.
    # Set to true on Render via env var, then back to false after testing.
    # Remove this once e2e admin tests are complete.
    ALLOW_ADMIN_DEMO: bool = False

    # Same idea but for superadmin. Askar uses this on prod to log in
    # as superadmin via /login/demo (binds to the kamilya-demo tenant).
    # Set to true on Render; safe to leave enabled — there's exactly
    # one superadmin demo user and it has no other privileges beyond
    # the standard superadmin role.
    ALLOW_SUPERADMIN_DEMO: bool = False

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://lms:lms_dev_password_2026@localhost:5432/kamilya_lms"

    @field_validator("DATABASE_URL", mode="before")
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
