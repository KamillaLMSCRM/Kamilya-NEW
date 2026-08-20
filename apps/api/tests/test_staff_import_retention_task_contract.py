from app.core.celery_app import celery_app
from app.modules.admin.superadmin.operations import REQUIRED_CELERY_TASKS
from app.modules.staff_import_sessions import retention_tasks  # noqa: F401


def test_staff_import_retention_task_is_registered_and_routed() -> None:
    assert "staff_import.cleanup_expired_sources" in celery_app.tasks
    assert "staff_import.cleanup_expired_sources" in REQUIRED_CELERY_TASKS
    route = celery_app.amqp.router.route({}, "staff_import.cleanup_expired_sources", args=(), kwargs={})
    assert route["queue"].name == "maintenance"
