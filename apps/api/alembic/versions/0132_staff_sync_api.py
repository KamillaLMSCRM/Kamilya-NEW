"""Add tenant-scoped Staff Sync credentials, identities and events.

Revision ID: 0132
Revises: 0131
Create Date: 2026-08-26
"""

from __future__ import annotations

from alembic import op

revision = "0132"
down_revision = "0131"
branch_labels = None
depends_on = None


TABLES = ("staff_sync_credentials", "staff_sync_identities", "staff_sync_events")


def _tenant_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE staff_sync_credentials (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            scopes JSONB NOT NULL DEFAULT '["staff:sync"]'::jsonb,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            expires_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            last_used_at TIMESTAMPTZ,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_staff_sync_token_hash CHECK (token_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_staff_sync_credential_name CHECK (length(btrim(name)) BETWEEN 3 AND 120),
            CONSTRAINT ck_staff_sync_scopes_array CHECK (jsonb_typeof(scopes) = 'array')
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_staff_sync_active_credential ON staff_sync_credentials (tenant_id) WHERE revoked_at IS NULL"
    )
    op.execute("CREATE INDEX ix_staff_sync_credentials_tenant ON staff_sync_credentials (tenant_id)")

    op.execute(
        """
        CREATE TABLE staff_sync_identities (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            source VARCHAR(80) NOT NULL,
            external_employee_id VARCHAR(200) NOT NULL,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_staff_sync_external_identity UNIQUE (tenant_id, source, external_employee_id),
            CONSTRAINT uq_staff_sync_user_source UNIQUE (tenant_id, source, user_id),
            CONSTRAINT ck_staff_sync_identity_source CHECK (length(btrim(source)) > 0),
            CONSTRAINT ck_staff_sync_external_id CHECK (length(btrim(external_employee_id)) > 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_staff_sync_identities_user ON staff_sync_identities (tenant_id, user_id)")

    op.execute(
        """
        CREATE TABLE staff_sync_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            credential_id UUID NOT NULL REFERENCES staff_sync_credentials(id) ON DELETE RESTRICT,
            source VARCHAR(80) NOT NULL,
            event_id VARCHAR(200) NOT NULL,
            payload_sha256 VARCHAR(64) NOT NULL,
            action VARCHAR(24) NOT NULL,
            external_employee_id VARCHAR(200) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'processing',
            employee_id UUID REFERENCES users(id) ON DELETE RESTRICT,
            effective_at TIMESTAMPTZ NOT NULL,
            outcome_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            processed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_staff_sync_event UNIQUE (tenant_id, source, event_id),
            CONSTRAINT ck_staff_sync_event_hash CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_staff_sync_action CHECK (action IN ('upsert','terminate','reactivate')),
            CONSTRAINT ck_staff_sync_status CHECK (status IN ('processing','created','linked','updated','unchanged','deactivated','reactivated','conflict'))
        )
        """
    )
    op.execute("CREATE INDEX ix_staff_sync_events_tenant_created ON staff_sync_events (tenant_id, created_at)")
    op.execute("CREATE INDEX ix_staff_sync_events_employee ON staff_sync_events (tenant_id, employee_id)")

    for table in TABLES:
        _tenant_rls(table)

    op.execute(
        """
        CREATE FUNCTION validate_staff_sync_identity_ownership() RETURNS trigger
        LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM users u
                WHERE u.id = NEW.user_id AND u.tenant_id = NEW.tenant_id AND u.role = 'student'
            ) THEN
                RAISE EXCEPTION 'staff sync identity tenant/user mismatch';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER staff_sync_identity_ownership BEFORE INSERT OR UPDATE ON staff_sync_identities FOR EACH ROW EXECUTE FUNCTION validate_staff_sync_identity_ownership()"
    )
    op.execute(
        """
        CREATE FUNCTION validate_staff_sync_event_ownership() RETURNS trigger
        LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM staff_sync_credentials c
                WHERE c.id = NEW.credential_id AND c.tenant_id = NEW.tenant_id
            ) OR (
                NEW.employee_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM users u WHERE u.id = NEW.employee_id AND u.tenant_id = NEW.tenant_id
                )
            ) THEN
                RAISE EXCEPTION 'staff sync event tenant ownership mismatch';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER staff_sync_event_ownership BEFORE INSERT OR UPDATE ON staff_sync_events FOR EACH ROW EXECUTE FUNCTION validate_staff_sync_event_ownership()"
    )
    op.execute(
        """
        CREATE FUNCTION lookup_staff_sync_credential(access_token_hash text)
        RETURNS TABLE (credential_id uuid, tenant_id uuid, credential_name text, scopes jsonb)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
            SELECT id, tenant_id, name, scopes
            FROM staff_sync_credentials
            WHERE token_hash = access_token_hash
              AND is_active = TRUE
              AND revoked_at IS NULL
              AND (expires_at IS NULL OR expires_at > NOW())
            LIMIT 1
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION lookup_staff_sync_credential(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION lookup_staff_sync_credential(text) TO lms_app")
    for table in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO lms_app")


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM staff_sync_identities)
               OR EXISTS (SELECT 1 FROM staff_sync_events) THEN
                RAISE EXCEPTION '0132 downgrade refused: staff sync identity or event evidence exists';
            END IF;
        END $$
        """
    )
    op.execute("DROP FUNCTION IF EXISTS lookup_staff_sync_credential(text)")
    op.execute("DROP FUNCTION IF EXISTS validate_staff_sync_event_ownership() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS validate_staff_sync_identity_ownership() CASCADE")
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"DROP TABLE IF EXISTS {table}")
