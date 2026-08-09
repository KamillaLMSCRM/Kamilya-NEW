import asyncio
from uuid import UUID

from app.core.celery_app import celery_app
from app.modules.learning_cycles.service import materialize_rule, recover_due


@celery_app.task(name="learning_cycles.materialize")
def materialize_rule_task(rule_id: str, tenant_id: str):
    return asyncio.run(materialize_rule(UUID(rule_id), UUID(tenant_id)))


@celery_app.task(name="learning_cycles.recover_due")
def recover_due_task():
    return asyncio.run(recover_due())
