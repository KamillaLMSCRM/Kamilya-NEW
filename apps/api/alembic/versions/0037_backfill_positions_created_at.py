"""Backfill positions.created_at for legacy NULL rows.

Some positions were inserted before the `server_default=func.now()` on
`positions.created_at` became effective, or via a code path that bypassed
the column default (notably bulk INSERTs from the staff-import wizard
during employee_onboarding Stage 1d — the import service adds rows with
positional kwargs and never reads back the freshly generated created_at).

Net result: a subset of `positions` rows in production have
`created_at IS NULL`. The API layer (PositionResponse in
`app/modules/positions/schemas.py`) had `created_at: datetime` (required,
no default), so any list call that included one of these rows
returned 422 Unprocessable Content for the entire tenant — including
the new /admin/staff RulesTab and the /positions page in this epic.

This migration is a one-shot data fix that ensures every row has a
non-NULL created_at. After it runs, the schema switch to
`created_at: datetime | None = None` (also part of B2) prevents
re-occurrence without hiding the issue.

We backfill from a heuristic that is monotonic-enough for v1.0:
  - If `users` table has any user with `position_id = positions.id` whose
    own `created_at` is non-NULL: take the minimum user.created_at for
    that position (the earliest person to hold it was the seed for
    "when this position first existed in our system").
  - Otherwise: fall back to now().

This is intentionally a runtime-bounded heuristic, not a perfect
reconstruction. For true point-in-time history the audit_log can be
backfilled separately, but that's out of scope for this fix.

Run on deploy automatically (startCommand in render.yaml runs
`alembic upgrade head`).
"""
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    # 1. Backfill using earliest user.created_at for that position.
    op.execute(
        sa.text(
            """
            UPDATE positions AS p
            SET created_at = (
                SELECT MIN(u.created_at)
                FROM users AS u
                WHERE u.position_id = p.id
                  AND u.created_at IS NOT NULL
            )
            WHERE p.created_at IS NULL
              AND EXISTS (
                SELECT 1 FROM users AS u2
                WHERE u2.position_id = p.id
                  AND u2.created_at IS NOT NULL
              )
            """
        )
    )

    # 2. Anything still NULL has no users — fall back to now(). These are
    #    legacy positions from before staffing data was migrated over,
    #    so "now" is at worst an upper bound on when they existed.
    op.execute(
        sa.text(
            """
            UPDATE positions
            SET created_at = now()
            WHERE created_at IS NULL
            """
        )
    )

    # 3. Defensive: same treatment for position_quizzes + position_jd_versions
    #    in case the issue surfaces elsewhere. These are referenced in the
    #    same code area and use the same server_default pattern.
    for tbl in ("position_quizzes", "position_jd_versions"):
        op.execute(
            sa.text(
                f"""
                UPDATE {tbl}
                SET created_at = now()
                WHERE created_at IS NULL
                """
            )
        )


def downgrade() -> None:
    # No-op: data backfill can't be safely reversed — we don't have the
    # original created_at values to restore.
    pass
