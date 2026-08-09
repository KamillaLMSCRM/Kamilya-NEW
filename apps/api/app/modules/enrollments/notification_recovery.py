"""Broker-independent recovery entry point for assignment notifications."""

from __future__ import annotations

import asyncio

from app.modules.enrollments.notification_tasks import recover_due_notifications


def main() -> None:
    asyncio.run(recover_due_notifications())


if __name__ == "__main__":
    main()
