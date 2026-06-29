"""Celery app configuration"""
import ssl

from celery import Celery
from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "kamilya_lms",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.modules.ai.tasks",
        "app.modules.positions.tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=300,
    task_time_limit=600,
    # Upstash uses rediss:// — Celery 5.6+ requires explicit ssl options
    # for the redis broker/backend when REDIS_URL starts with rediss://.
    # Pass ssl.CERT_REQUIRED as the int value (don't pass the string
    # "CERT_REQUIRED" — redis-py 5.x rejects it with
    # "Invalid SSL Certificate Requirements Flag: CERT_REQUIRED").
    broker_use_ssl={"ssl_cert_reqs": ssl.CERT_REQUIRED} if str(settings.REDIS_URL).startswith("rediss://") else None,
    redis_backend_use_ssl={"ssl_cert_reqs": ssl.CERT_REQUIRED} if str(settings.REDIS_URL).startswith("rediss://") else None,
)
