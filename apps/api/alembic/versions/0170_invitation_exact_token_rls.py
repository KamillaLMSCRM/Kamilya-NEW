"""Replace broad public invitation visibility with an exact-token capability.

Deploy the compatible API lookup helper before applying this migration. Old
public lookup code does not set the token scope and must not be rolled back to.
"""

import re

from alembic import op

revision = "0170"
down_revision = "0169"
branch_labels = None
depends_on = None


def upgrade() -> None:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe invitation schema")
    table = f'"{schema}".user_invitations'
    op.execute(f"DROP POLICY IF EXISTS user_invitations_public_pending_lookup ON {table}")
    op.execute(f"DROP POLICY IF EXISTS user_invitations_public_token_lookup ON {table}")
    op.execute(
        f"""
        CREATE POLICY user_invitations_public_token_lookup ON {table}
        FOR SELECT TO lms_app
        USING (
            NULLIF(current_setting('app.tenant_id', true), '') IS NULL
            AND token = NULLIF(current_setting('app.invitation_token', true), '')
        )
        """
    )


def downgrade() -> None:
    raise RuntimeError("0170 security boundary is roll-forward only; broad invitation policy must not be restored")
