"""Queue isolation contracts for durable background work."""

import pytest

from app.core.celery_app import celery_app


@pytest.mark.parametrize(
    ("task_name", "expected_queue"),
    [
        ("ai.generate_course", "ai"),
        ("ai.regenerate_module", "ai"),
        ("ai.regenerate_lesson", "ai"),
        ("ai.ingest_document", "documents"),
        ("documents.reindex", "documents"),
        ("documents.cleanup", "maintenance"),
        ("documents.hash_backfill", "maintenance"),
        ("positions.apply_course_rules", "maintenance"),
        ("users.deliver_invitation", "notifications"),
        ("enrollments.deliver_assignment_notification", "notifications"),
        ("enrollments.recover_assignment_notifications", "notifications"),
    ],
)
def test_background_tasks_have_explicit_queues(task_name: str, expected_queue: str) -> None:
    route = celery_app.amqp.router.route({}, task_name, args=(), kwargs={})

    assert route["queue"].name == expected_queue


def test_long_tasks_have_limits_above_remote_converter_timeout() -> None:
    annotations = celery_app.conf.task_annotations

    assert annotations["documents.reindex"] == {
        "soft_time_limit": 900,
        "time_limit": 1200,
    }
    assert annotations["ai.generate_course"] == {
        "soft_time_limit": 1200,
        "time_limit": 1500,
    }
    assert celery_app.conf.broker_transport_options["visibility_timeout"] > 1500
