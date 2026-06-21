import json
from pydantic_settings import BaseSettings
from functools import lru_cache
from pydantic import field_validator


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Kamilya LMS"
    APP_ENV: str = "development"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://lms:lms_dev_password_2026@localhost:5432/kamilya_lms"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_SECRET: str = "dev-secret-dont-use-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # MinIO / S3
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin_secret_2026"
    MINIO_BUCKET: str = "lms-content"
    MINIO_USE_SSL: bool = False

    # Qwen
    QWEN_API_URL: str = "http://localhost:8555"
    QWEN_EMBEDDING_URL: str = "http://localhost:8001"

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = ""

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "https://app.kml.kz"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [origin.strip() for origin in v.split(",")]
        return v

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
