"""Task-local correlation after caller authorizes a job."""

import contextvars
import logging

job_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("generation_timeout_job_id", default=None)


def emit(logger: logging.Logger, stage: str) -> None:
    owner = job_id.get()
    if owner is None:
        logger.warning("generation_timeout_boundary stage=%s", stage)
    else:
        logger.warning("generation_timeout_boundary stage=%s job_id=%s", stage, owner)
