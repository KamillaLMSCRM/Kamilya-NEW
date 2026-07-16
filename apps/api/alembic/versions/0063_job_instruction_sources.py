"""Link job-instruction documents to positions and generated courses.

Revision ID: 0063
Revises: 0062
"""

from alembic import op


revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS category "
        "TEXT NOT NULL DEFAULT 'general'"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_document_category'
                  AND conrelid = 'documents'::regclass
            ) THEN
                ALTER TABLE documents ADD CONSTRAINT ck_document_category
                    CHECK (category IN ('general', 'job_instruction'));
            END IF;
        END $$;
        """
    )

    op.execute(
        "ALTER TABLE positions ADD COLUMN IF NOT EXISTS instruction_document_id UUID"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_positions_instruction_document'
            ) THEN
                ALTER TABLE positions ADD CONSTRAINT fk_positions_instruction_document
                    FOREIGN KEY (instruction_document_id) REFERENCES documents(id)
                    ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_positions_instruction_document_id "
        "ON positions (instruction_document_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_positions_tenant_instruction_document "
        "ON positions (tenant_id, instruction_document_id) "
        "WHERE instruction_document_id IS NOT NULL"
    )

    op.execute(
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS source_instruction_id UUID"
    )
    op.execute(
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS source_instruction_version_at TIMESTAMPTZ"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_courses_source_instruction'
            ) THEN
                ALTER TABLE courses ADD CONSTRAINT fk_courses_source_instruction
                    FOREIGN KEY (source_instruction_id) REFERENCES documents(id)
                    ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_courses_source_instruction_id "
        "ON courses (source_instruction_id) "
        "WHERE source_instruction_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_courses_source_instruction_id")
    op.execute("ALTER TABLE courses DROP CONSTRAINT IF EXISTS fk_courses_source_instruction")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS source_instruction_version_at")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS source_instruction_id")
    op.execute("DROP INDEX IF EXISTS uq_positions_tenant_instruction_document")
    op.execute("DROP INDEX IF EXISTS ix_positions_instruction_document_id")
    op.execute("ALTER TABLE positions DROP CONSTRAINT IF EXISTS fk_positions_instruction_document")
    op.execute("ALTER TABLE positions DROP COLUMN IF EXISTS instruction_document_id")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS ck_document_category")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS category")
