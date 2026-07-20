"""Smoke-test tenant isolation and transaction-local context through PgBouncer."""

from __future__ import annotations

import argparse
import asyncio
import uuid

import asyncpg


async def _visible_users(connection: asyncpg.Connection, tenant_id: uuid.UUID) -> int:
    await connection.execute("SELECT set_current_tenant($1::uuid)", tenant_id)
    cross_tenant = await connection.fetchval(
        "SELECT count(*) FROM users WHERE tenant_id <> $1::uuid", tenant_id
    )
    if cross_tenant:
        raise RuntimeError(f"RLS leak: {cross_tenant} cross-tenant user rows are visible")
    # The platform superadmin row has tenant_id NULL and is intentionally
    # visible for login lookup; it is not tenant data.
    return await connection.fetchval(
        "SELECT count(*) FROM users WHERE tenant_id IS NOT NULL"
    )


async def verify(dsn: str, tenant_a: uuid.UUID, tenant_b: uuid.UUID) -> None:
    connection = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        async with connection.transaction():
            visible_a = await _visible_users(connection, tenant_a)

        async with connection.transaction():
            without_context = await connection.fetchval(
                "SELECT count(*) FROM users WHERE tenant_id IS NOT NULL"
            )
            if without_context:
                raise RuntimeError(
                    f"Tenant context leaked between transactions: {without_context} rows visible"
                )

        async with connection.transaction():
            visible_b = await _visible_users(connection, tenant_b)

        print(
            "OK: PgBouncer transaction isolation passed "
            f"(tenant A visible users={visible_a}, tenant B visible users={visible_b})"
        )
    finally:
        await connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--tenant-a", required=True, type=uuid.UUID)
    parser.add_argument("--tenant-b", required=True, type=uuid.UUID)
    args = parser.parse_args()
    asyncio.run(verify(args.dsn, args.tenant_a, args.tenant_b))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
