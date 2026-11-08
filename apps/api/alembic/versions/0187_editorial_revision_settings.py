"""Extend audited runtime settings with the autonomous editorial revision budget.

Revision ID:0187
Revises:0186
"""
import importlib.util
from pathlib import Path

from alembic import op

revision = '0187'
down_revision = '0186'
branch_labels = depends_on = None
NUMBERS = {'generation.editorial_max_revisions': (3, 1, 5, True),
    'generation.editorial_rules_per_review': (128, 1, 128, True),
    'generation.editorial_luna_max_tokens': (32768, 8192, 32768, True),
    'generation.editorial_deepseek_max_tokens': (65536, 16384, 65536, True)}


def _previous():
    spec = importlib.util.spec_from_file_location('source_settings_0186_frozen',
        Path(__file__).with_name('0186_source_preparation_settings.py'))
    if spec is None or spec.loader is None:
        raise RuntimeError('runtime_settings_frozen_catalog_missing')
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    return previous


def upgrade() -> None:
    previous = _previous()
    schema = previous._schema()
    previous._keys(schema, (*previous._original_keys(), *previous.NUMBERS, *NUMBERS))
    names = ('ck_editorial_revision_budget', 'ck_editorial_rule_part_budget',
             'ck_editorial_luna_output_budget', 'ck_editorial_deepseek_output_budget')
    for name, (key, (_, lower, upper, _)) in zip(names, NUMBERS.items(), strict=True):
        numeric = f"(overrides->>'{key}')::numeric"
        op.execute(f'ALTER TABLE {schema}.runtime_settings ADD CONSTRAINT {name} '
            f"CHECK(NOT overrides ? '{key}' OR (jsonb_typeof(overrides->'{key}')='number' "
            f'AND {numeric} BETWEEN {lower} AND {upper} AND {numeric}=trunc({numeric})))')


def downgrade() -> None:
    previous = _previous()
    schema = previous._schema()
    # Retain owner overrides/history; the old key constraint rejects a downgrade
    # while a new override is in use, rather than silently deleting audit data.
    previous._keys(schema, (*previous._original_keys(), *previous.NUMBERS))
    op.execute(f'ALTER TABLE {schema}.runtime_settings DROP CONSTRAINT ck_editorial_revision_budget')
    op.execute(f'ALTER TABLE {schema}.runtime_settings DROP CONSTRAINT ck_editorial_rule_part_budget')
    op.execute(f'ALTER TABLE {schema}.runtime_settings DROP CONSTRAINT ck_editorial_luna_output_budget')
    op.execute(f'ALTER TABLE {schema}.runtime_settings DROP CONSTRAINT ck_editorial_deepseek_output_budget')
