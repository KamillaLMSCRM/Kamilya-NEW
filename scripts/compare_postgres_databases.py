"""Compare public PostgreSQL schemas and row counts without reading row data."""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict

import asyncpg


COLUMNS_SQL = """
SELECT c.relname AS table_name,
       a.attname AS column_name,
       pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type
FROM pg_catalog.pg_attribute AS a
JOIN pg_catalog.pg_class AS c ON c.oid = a.attrelid
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p')
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY c.relname, a.attnum
"""

TABLES_SQL = """
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name
"""


async def _schema(connection: asyncpg.Connection) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = defaultdict(dict)
    for row in await connection.fetch(COLUMNS_SQL):
        result[row["table_name"]][row["column_name"]] = row["data_type"]
    return dict(result)


async def _counts(
    connection: asyncpg.Connection, tables: list[str]
) -> dict[str, int]:
    result: dict[str, int] = {}
    for table in tables:
        quoted = table.replace('"', '""')
        result[table] = await connection.fetchval(
            f'SELECT count(*) FROM public."{quoted}"'
        )
    return result


async def compare(
    source_dsn: str,
    target_dsn: str,
    include_counts: bool,
    print_source_counts: bool,
) -> int:
    source = await asyncpg.connect(source_dsn)
    target = await asyncpg.connect(target_dsn)
    try:
        source_schema = await _schema(source)
        target_schema = await _schema(target)
        differences = 0

        if print_source_counts:
            source_tables = [row["table_name"] for row in await source.fetch(TABLES_SQL)]
            for table, count in (await _counts(source, source_tables)).items():
                print(f"{table}|{count}")
            return 0

        for table in sorted(source_schema):
            if table not in target_schema:
                print(f"SCHEMA {table}: target table is missing")
                differences += 1
                continue
            missing = {
                column: data_type
                for column, data_type in source_schema[table].items()
                if column not in target_schema[table]
            }
            if missing:
                details = ", ".join(
                    f"{column} ({data_type})" for column, data_type in missing.items()
                )
                print(f"SCHEMA {table}: target columns missing: {details}")
                differences += 1

        if include_counts:
            source_tables = [row["table_name"] for row in await source.fetch(TABLES_SQL)]
            common = [table for table in source_tables if table in target_schema]
            source_counts = await _counts(source, common)
            target_counts = await _counts(target, common)
            for table in common:
                if source_counts[table] != target_counts[table]:
                    print(
                        f"COUNT {table}: source={source_counts[table]} "
                        f"target={target_counts[table]}"
                    )
                    differences += 1

        if differences == 0:
            message = "OK: source tables are compatible with target"
            if include_counts:
                message += " and row counts match"
            print(message)
        return 1 if differences else 0
    finally:
        await source.close()
        await target.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--counts", action="store_true")
    parser.add_argument("--print-source-counts", action="store_true")
    args = parser.parse_args()
    return asyncio.run(
        compare(args.source, args.target, args.counts, args.print_source_counts)
    )


if __name__ == "__main__":
    raise SystemExit(main())
