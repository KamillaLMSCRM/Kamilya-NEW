"""Exit non-zero when a durable Celery queue exceeds its backlog limit."""

from __future__ import annotations

import argparse
import os
import ssl

from app.core.config import get_settings
from redis import Redis

QUEUES = ("ai", "documents", "notifications", "maintenance", "celery")


def _client() -> Redis:
    settings = get_settings()
    kwargs: dict[str, object] = {
        "socket_connect_timeout": 5,
        "socket_timeout": 5,
        "decode_responses": False,
    }
    if str(settings.REDIS_URL).startswith("rediss://"):
        verify = os.getenv("REDIS_TLS_VERIFY", "true").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED if verify else ssl.CERT_NONE
    return Redis.from_url(str(settings.REDIS_URL), **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-depth", type=int, default=50)
    args = parser.parse_args()

    client = _client()
    over_limit: list[str] = []
    try:
        for queue in QUEUES:
            depth = int(client.llen(queue))
            if depth > args.max_depth:
                over_limit.append(f"{queue}={depth}")
    finally:
        client.close()

    if over_limit:
        print(f"Celery queue backlog exceeds {args.max_depth}: {', '.join(over_limit)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
