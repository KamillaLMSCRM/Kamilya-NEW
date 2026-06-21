"""Celery app configuration"""
from celery import Celery
from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "kamilya_lms",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.modules.ai.tasks",
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
)
