"""Preview or safely delete old synthetic tenants.

The command is dry-run by default. Destructive execution requires both
``--execute`` and ``--confirm-token CLEANUP_SYNTHETIC_TENANTS``. It uses the
same superadmin operations service as the HTTP endpoint and therefore keeps
the same demo flag, slug prefix, age, and per-tenant guards.

Examples:
  python scripts/cleanup_synthetic_tenants.py
  python scripts/cleanup_synthetic_tenants.py --min-age-hours 72
  python scripts/cleanup_synthetic_tenants.py --execute \
      --confirm-token CLEANUP_SYNTHETIC_TENANTS
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

# Keep argument validation usable without loading application settings. This
# means a typo in the destructive confirmation token fails before any database
# connection or secret-dependent application import is attempted.
CLEANUP_CONFIRM_TOKEN = "CLEANUP_SYNTHETIC_TENANTS"
MIN_CLEANUP_AGE_HOURS = 24
MAX_CLEANUP_AGE_HOURS = 24 * 365 * 5


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-age-hours",
        type=int,
        default=MIN_CLEANUP_AGE_HOURS,
        choices=range(MIN_CLEANUP_AGE_HOURS, MAX_CLEANUP_AGE_HOURS + 1),
        metavar="HOURS",
        help="minimum tenant age; defaults to 24 hours",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="perform deletion; without this flag the command only previews",
    )
    parser.add_argument(
        "--confirm-token",
        default=None,
        help="required with --execute; exact fixed cleanup confirmation token",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    from app.core.db import async_session_factory
    from app.modules.admin.superadmin.operations import SuperadminOperationsService

    async with async_session_factory() as db:
        result = await SuperadminOperationsService(db).cleanup_synthetic_tenants(
            dry_run=not args.execute,
            min_age_hours=args.min_age_hours,
            confirm=args.execute,
            confirm_token=args.confirm_token,
        )
    print(result.model_dump_json(indent=2))
    return 0


def main() -> int:
    args = _parser().parse_args()
    if args.execute and args.confirm_token != CLEANUP_CONFIRM_TOKEN:
        _parser().error(
            "--execute requires --confirm-token "
            f"{CLEANUP_CONFIRM_TOKEN}"
        )
    try:
        return asyncio.run(_run(args))
    except ValueError as exc:
        _parser().error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
