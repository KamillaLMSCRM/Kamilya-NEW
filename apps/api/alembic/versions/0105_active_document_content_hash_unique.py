"""Prevent duplicate active document bytes per tenant.

Revision ID: 0105
Revises: 0104
"""

from alembic import op

revision = "0105"
down_revision = "0104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Do not choose or delete a user's documents during a schema change. An
    # operator must resolve legacy active duplicates deliberately before the
    # database can begin enforcing the invariant.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM documents
            WHERE lifecycle_status = 'active' AND content_sha256 IS NOT NULL
            GROUP BY tenant_id, content_sha256
            HAVING count(*) > 1
          ) THEN
            RAISE EXCEPTION
              '0105 upgrade refused: active documents contain duplicate tenant content hashes; resolve duplicates without deleting user data before retrying';
          END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_documents_active_tenant_content_sha256
        ON documents (tenant_id, content_sha256)
        WHERE lifecycle_status = 'active' AND content_sha256 IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_documents_active_tenant_content_sha256")
