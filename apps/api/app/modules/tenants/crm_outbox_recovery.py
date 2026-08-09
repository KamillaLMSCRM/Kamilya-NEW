"""Broker-independent entry point for the CRM outbox recovery timer."""

from __future__ import annotations

import asyncio
import logging

from app.modules.tenants.crm_outbox import recover_due_events

logger = logging.getLogger(__name__)


def main() -> None:
    result = asyncio.run(recover_due_events())
    logger.info(
        "crm.lead_outbox.recovery_complete due=%s processed=%s",
        result["due"],
        result["processed"],
    )


if __name__ == "__main__":
    main()
