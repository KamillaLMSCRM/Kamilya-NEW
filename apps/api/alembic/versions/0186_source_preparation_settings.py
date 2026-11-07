"""Extend the existing audited settings catalog for source preparation.

Revision ID:0186
Revises:0185
"""

import importlib.util
import re
from pathlib import Path

from alembic import op

revision = "0186"
down_revision = "0185"
branch_labels = depends_on = None

# Frozen policy. Never import the mutable application catalog from migrations.
NUMBERS = {
    "source_preparation.image_max_bytes": (16_777_216, 65_536, 33_554_432, True),
    "source_preparation.image_max_pixels": (24_000_000, 1_000_000, 64_000_000, True),
    "source_preparation.vision_batch_size": (2, 1, 4, True),
    "source_preparation.max_tokens": (16_384, 4096, 32_768, True),
    "source_preparation.part_preview_chars": (600, 120, 2000, True),
}


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("unsafe_runtime_settings_schema")
    return f'"{schema}"'


def _original_keys() -> tuple[str, ...]:
    spec = importlib.util.spec_from_file_location("runtime_settings_0182_frozen", Path(__file__).with_name("0182_runtime_settings.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("runtime_settings_frozen_catalog_missing")
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    return (*old.NUMBERS, *old.MODEL_KEYS)


def _keys(schema: str, keys: tuple[str, ...]) -> None:
    quoted = ",".join(f"'{key}'" for key in keys)
    op.execute(f"ALTER TABLE {schema}.runtime_settings DROP CONSTRAINT ck_runtime_settings_keys")
    op.execute(f"ALTER TABLE {schema}.runtime_settings ADD CONSTRAINT ck_runtime_settings_keys "
               f"CHECK(overrides - ARRAY[{quoted}]::text[] = '{{}}'::jsonb)")


def upgrade() -> None:
    schema = _schema()
    _keys(schema, (*_original_keys(), *NUMBERS))
    for index, (key, (_, minimum, maximum, _)) in enumerate(NUMBERS.items()):
        numeric = f"(overrides->>'{key}')::numeric"
        op.execute(f"ALTER TABLE {schema}.runtime_settings ADD CONSTRAINT ck_source_preparation_number_{index} "
            f"CHECK(NOT overrides ? '{key}' OR (jsonb_typeof(overrides->'{key}')='number' "
            f"AND {numeric} BETWEEN {minimum} AND {maximum} AND {numeric}=trunc({numeric})))")


def downgrade() -> None:
    schema = _schema()
    # Removing the catalog while new overrides exist fails the retained key
    # constraint. No audit rows or owner-selected settings are erased.
    _keys(schema, _original_keys())
    for index in range(len(NUMBERS)):
        op.execute(f"ALTER TABLE {schema}.runtime_settings DROP CONSTRAINT ck_source_preparation_number_{index}")
