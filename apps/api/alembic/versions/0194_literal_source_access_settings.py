"""Extend the existing audited runtime settings; no source or course mutations.

Revision ID:0194
Revises:0192
"""
import importlib.util
from pathlib import Path

from alembic import op

revision = '0194'
down_revision = '0192'
branch_labels = depends_on = None
NUMBERS = {'generation.reference_literal_chars': (30000, 1000, 120000, True),
           'generation.reference_lookup_rounds': (2, 0, 3, True)}


def _previous():
    spec = importlib.util.spec_from_file_location('literal_settings_0187_frozen',
        Path(__file__).with_name('0187_editorial_revision_settings.py'))
    if spec is None or spec.loader is None:
        raise RuntimeError('runtime_settings_frozen_catalog_missing')
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    return previous


def upgrade() -> None:
    editorial = _previous()
    previous = editorial._previous()
    schema = previous._schema()
    previous._keys(schema, (*previous._original_keys(), *previous.NUMBERS, *editorial.NUMBERS, *NUMBERS))
    for index, (key, (_, lower, upper, _)) in enumerate(NUMBERS.items()):
        numeric = f"(overrides->>'{key}')::numeric"
        op.execute(f'ALTER TABLE {schema}.runtime_settings ADD CONSTRAINT ck_literal_source_number_{index} '
            f"CHECK(NOT overrides ? '{key}' OR (jsonb_typeof(overrides->'{key}')='number' "
            f'AND {numeric} BETWEEN {lower} AND {upper} AND {numeric}=trunc({numeric})))')


def downgrade() -> None:
    editorial = _previous()
    previous = editorial._previous()
    schema = previous._schema()
    # Refuse removal while an override is in use. Never erase settings/history.
    previous._keys(schema, (*previous._original_keys(), *previous.NUMBERS, *editorial.NUMBERS))
    for index in range(len(NUMBERS)):
        op.execute(f'ALTER TABLE {schema}.runtime_settings DROP CONSTRAINT ck_literal_source_number_{index}')
