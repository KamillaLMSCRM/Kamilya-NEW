"""Broker-independent entry point for candidate retention enforcement."""

from __future__ import annotations

import asyncio

from app.modules.candidate_assessments.retention_tasks import enforce_candidate_retention


def main() -> None:
    asyncio.run(enforce_candidate_retention())


if __name__ == "__main__":
    main()
