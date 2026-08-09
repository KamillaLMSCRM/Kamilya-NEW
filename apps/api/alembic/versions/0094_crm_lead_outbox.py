"""Add the durable LMS-to-CRM lead outbox.

Revision ID: 0094
Revises: 0093
"""

from alembic import op

revision = "0094"
down_revision = "0093"
branch_labels = None
depends_on = None


PUBLIC_LEAD_FUNCTION_8 = (
    "insert_public_tenant_lead(text, text, text, text, text, text, text, text)"
)
PUBLIC_LEAD_FUNCTION_9 = (
    "insert_public_tenant_lead(text, text, text, text, text, text, text, text, jsonb)"
)


def _revoke_and_grant(signature: str) -> None:
    op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO lms_app")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE crm_lead_outbox (
            id uuid PRIMARY KEY,
            lead_id uuid NOT NULL UNIQUE
                REFERENCES tenant_leads(id) ON DELETE CASCADE,
            tenant_id uuid NULL
                REFERENCES tenants(id) ON DELETE SET NULL,
            event_id text NOT NULL UNIQUE,
            event_type text NOT NULL DEFAULT 'lead.submitted',
            payload_version integer NOT NULL DEFAULT 1,
            payload_bytes bytea NOT NULL,
            occurred_at timestamptz NOT NULL DEFAULT now(),
            status text NOT NULL DEFAULT 'pending',
            attempt_count integer NOT NULL DEFAULT 0,
            next_attempt_at timestamptz NULL,
            claimed_at timestamptz NULL,
            claim_token uuid NULL UNIQUE,
            delivered_at timestamptz NULL,
            terminal_at timestamptz NULL,
            last_status_code integer NULL,
            last_error_category text NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT crm_lead_outbox_event_type
                CHECK (event_type = 'lead.submitted'),
            CONSTRAINT crm_lead_outbox_status
                CHECK (status IN ('pending', 'claimed', 'retry', 'delivered', 'dead')),
            CONSTRAINT crm_lead_outbox_attempt_count
                CHECK (attempt_count >= 0 AND attempt_count <= 8),
            CONSTRAINT crm_lead_outbox_event_id_length
                CHECK (length(event_id) BETWEEN 8 AND 64),
            CONSTRAINT crm_lead_outbox_payload_size
                CHECK (octet_length(payload_bytes) BETWEEN 2 AND 65536)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_crm_lead_outbox_due "
        "ON crm_lead_outbox (status, next_attempt_at, created_at)"
    )
    op.execute(
        "CREATE INDEX ix_crm_lead_outbox_tenant "
        "ON crm_lead_outbox (tenant_id)"
    )
    op.execute("ALTER TABLE crm_lead_outbox ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_lead_outbox FORCE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE crm_lead_outbox FROM PUBLIC, lms_app")

    # Public capture creates the lead and its exact outbound bytes in one DB
    # transaction. The code-owned metadata object cannot override the canonical
    # identity fields because the base object is concatenated last.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION insert_public_tenant_lead(
            p_company_name text,
            p_contact_name text,
            p_email text,
            p_phone text,
            p_employee_count_range text,
            p_preferred_language text,
            p_intent text,
            p_message text,
            p_metadata jsonb
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            created_id uuid := gen_random_uuid();
            event_key text;
            payload jsonb;
        BEGIN
            PERFORM set_config('app.public_lead_insert', 'true', true);
            event_key := 'lmslead_' || replace(created_id::text, '-', '');

            INSERT INTO tenant_leads (
                id, tenant_id, company_name, contact_name, email, phone,
                employee_count_range, preferred_language, intent, status,
                source, message
            )
            VALUES (
                created_id, NULL, p_company_name, p_contact_name, p_email,
                p_phone, p_employee_count_range, p_preferred_language,
                p_intent, 'lead_submitted', 'landing_form', p_message
            );

            payload := coalesce(p_metadata, '{}'::jsonb) || jsonb_build_object(
                'event_id', event_key,
                'lead_id', created_id::text,
                'company_name', p_company_name,
                'contact_name', p_contact_name,
                'email', p_email,
                'phone', CASE WHEN length(p_phone) <= 20 THEN p_phone ELSE NULL END,
                'employee_count_range', p_employee_count_range,
                'preferred_language', p_preferred_language,
                'intent', CASE
                    WHEN p_intent IN ('try', 'demo', 'buy') THEN p_intent
                    ELSE 'demo'
                END,
                'interest', p_intent,
                'source', 'landing_form',
                'message', p_message,
                'submitted_at', now(),
                'payload_version', 1
            );

            INSERT INTO crm_lead_outbox (
                id, lead_id, tenant_id, event_id, event_type,
                payload_version, payload_bytes
            )
            VALUES (
                created_id, created_id, NULL, event_key, 'lead.submitted', 1,
                convert_to(payload::text, 'UTF8')
            );
            RETURN created_id;
        END;
        $$
        """
    )
    _revoke_and_grant(PUBLIC_LEAD_FUNCTION_9)

    # Keep the historical interface safe: old callers still create an outbox
    # row instead of silently bypassing CRM delivery.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION insert_public_tenant_lead(
            p_company_name text,
            p_contact_name text,
            p_email text,
            p_phone text,
            p_employee_count_range text,
            p_preferred_language text,
            p_intent text,
            p_message text
        )
        RETURNS uuid
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT insert_public_tenant_lead(
                p_company_name, p_contact_name, p_email, p_phone,
                p_employee_count_range, p_preferred_language, p_intent,
                p_message, '{}'::jsonb
            )
        $$
        """
    )
    _revoke_and_grant(PUBLIC_LEAD_FUNCTION_8)

    op.execute(
        """
        CREATE FUNCTION crm_enqueue_tenant_lead_outbox(
            p_lead_id uuid,
            p_tenant_id uuid,
            p_metadata jsonb DEFAULT '{}'::jsonb
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            lead tenant_leads;
            event_key text;
            payload jsonb;
        BEGIN
            IF current_setting('app.tenant_id', true)
                IS DISTINCT FROM p_tenant_id::text THEN
                RAISE EXCEPTION 'tenant context mismatch';
            END IF;

            SELECT * INTO lead
            FROM tenant_leads
            WHERE id = p_lead_id AND tenant_id = p_tenant_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'lead tenant mismatch';
            END IF;

            event_key := 'lmslead_' || replace(lead.id::text, '-', '');
            payload := coalesce(p_metadata, '{}'::jsonb) || jsonb_build_object(
                'event_id', event_key,
                'lead_id', lead.id::text,
                'company_name', lead.company_name,
                'contact_name', lead.contact_name,
                'email', lead.email,
                'phone', CASE
                    WHEN length(lead.phone) <= 20 THEN lead.phone ELSE NULL
                END,
                'telegram_username', CASE
                    WHEN length(lead.telegram_username) <= 64
                    THEN lead.telegram_username ELSE NULL
                END,
                'employee_count_range', lead.employee_count_range,
                'preferred_language', lead.preferred_language,
                'intent', CASE
                    WHEN lead.intent IN ('try', 'demo', 'buy') THEN lead.intent
                    ELSE 'demo'
                END,
                'interest', lead.intent,
                'source', lead.source,
                'message', lead.message,
                'submitted_at', lead.created_at,
                'payload_version', 1
            );

            INSERT INTO crm_lead_outbox (
                id, lead_id, tenant_id, event_id, event_type,
                payload_version, payload_bytes
            )
            VALUES (
                lead.id, lead.id, p_tenant_id, event_key,
                'lead.submitted', 1, convert_to(payload::text, 'UTF8')
            )
            ON CONFLICT (lead_id) DO NOTHING;
            RETURN lead.id;
        END;
        $$
        """
    )
    _revoke_and_grant("crm_enqueue_tenant_lead_outbox(uuid, uuid, jsonb)")

    op.execute(
        """
        CREATE FUNCTION crm_claim_lead_outbox(p_id uuid)
        RETURNS TABLE(
            id uuid,
            event_id text,
            event_type text,
            payload_bytes bytea,
            claim_token uuid
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            WITH candidate AS (
                SELECT candidate.id
                FROM crm_lead_outbox AS candidate
                WHERE candidate.id = p_id
                  AND (
                    (
                        candidate.status IN ('pending', 'retry')
                        AND (
                            candidate.next_attempt_at IS NULL
                            OR candidate.next_attempt_at <= now()
                        )
                    )
                    OR (
                        candidate.status = 'claimed'
                        AND candidate.claimed_at <= now() - interval '2 minutes'
                    )
                  )
                FOR UPDATE SKIP LOCKED
            ), claimed AS (
                UPDATE crm_lead_outbox AS outbox
                SET status = 'claimed',
                    claimed_at = now(),
                    claim_token = gen_random_uuid(),
                    updated_at = now()
                FROM candidate
                WHERE outbox.id = candidate.id
                RETURNING outbox.id, outbox.event_id, outbox.event_type,
                          outbox.payload_bytes, outbox.claim_token
            )
            SELECT * FROM claimed
        $$
        """
    )
    _revoke_and_grant("crm_claim_lead_outbox(uuid)")

    op.execute(
        """
        CREATE FUNCTION crm_finalize_lead_outbox(
            p_id uuid,
            p_token uuid,
            p_kind text,
            p_status integer,
            p_error text
        )
        RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        BEGIN
            IF p_kind NOT IN ('success', 'terminal', 'transient', 'defer') THEN
                RAISE EXCEPTION 'invalid outbox finalization kind';
            END IF;

            UPDATE crm_lead_outbox
            SET attempt_count = attempt_count + CASE
                    WHEN p_kind = 'defer' THEN 0 ELSE 1
                END,
                last_status_code = CASE
                    WHEN p_status BETWEEN 100 AND 599 THEN p_status ELSE NULL
                END,
                last_error_category = left(p_error, 64),
                claim_token = NULL,
                claimed_at = NULL,
                status = CASE
                    WHEN p_kind = 'success' THEN 'delivered'
                    WHEN p_kind = 'terminal' THEN 'dead'
                    WHEN p_kind = 'transient' AND attempt_count + 1 >= 8
                        THEN 'dead'
                    ELSE 'retry'
                END,
                delivered_at = CASE
                    WHEN p_kind = 'success' THEN now() ELSE NULL
                END,
                terminal_at = CASE
                    WHEN p_kind = 'terminal'
                      OR (p_kind = 'transient' AND attempt_count + 1 >= 8)
                    THEN now() ELSE NULL
                END,
                next_attempt_at = CASE
                    WHEN p_kind = 'defer' THEN now() + interval '5 minutes'
                    WHEN p_kind = 'transient' AND attempt_count + 1 < 8 THEN
                        now() + make_interval(secs => (
                            least(
                                3600.0,
                                5.0 * power(2.0, least(attempt_count + 1, 9))
                            ) + floor(random() * 4.0)
                        )::integer)
                    ELSE NULL
                END,
                updated_at = now()
            WHERE id = p_id
              AND status = 'claimed'
              AND claim_token = p_token;
            RETURN FOUND;
        END;
        $$
        """
    )
    _revoke_and_grant(
        "crm_finalize_lead_outbox(uuid, uuid, text, integer, text)"
    )

    op.execute(
        """
        CREATE FUNCTION crm_due_lead_outbox(p_limit integer DEFAULT 20)
        RETURNS TABLE(id uuid)
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT outbox.id
            FROM crm_lead_outbox AS outbox
            WHERE (
                outbox.status IN ('pending', 'retry')
                AND (
                    outbox.next_attempt_at IS NULL
                    OR outbox.next_attempt_at <= now()
                )
            ) OR (
                outbox.status = 'claimed'
                AND outbox.claimed_at <= now() - interval '2 minutes'
            )
            ORDER BY outbox.created_at, outbox.id
            LIMIT greatest(1, least(p_limit, 100))
        $$
        """
    )
    _revoke_and_grant("crm_due_lead_outbox(integer)")

    op.execute(
        """
        CREATE FUNCTION crm_lead_outbox_summary()
        RETURNS TABLE(
            pending_count bigint,
            retry_count bigint,
            claimed_count bigint,
            dead_count bigint,
            delivered_count bigint,
            oldest_due_at timestamptz
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        BEGIN
            IF current_setting('app.is_superadmin', true)
                IS DISTINCT FROM 'true' THEN
                RAISE EXCEPTION 'superadmin context required';
            END IF;
            RETURN QUERY
            SELECT
                count(*) FILTER (WHERE status = 'pending'),
                count(*) FILTER (WHERE status = 'retry'),
                count(*) FILTER (WHERE status = 'claimed'),
                count(*) FILTER (WHERE status = 'dead'),
                count(*) FILTER (WHERE status = 'delivered'),
                min(created_at) FILTER (
                    WHERE (
                        status IN ('pending', 'retry')
                        AND (next_attempt_at IS NULL OR next_attempt_at <= now())
                    ) OR (
                        status = 'claimed'
                        AND claimed_at <= now() - interval '2 minutes'
                    )
                )
            FROM crm_lead_outbox;
        END;
        $$
        """
    )
    _revoke_and_grant("crm_lead_outbox_summary()")

    op.execute(
        """
        CREATE FUNCTION crm_requeue_dead_lead_outbox(
            p_limit integer DEFAULT 20,
            p_execute boolean DEFAULT false
        )
        RETURNS TABLE(eligible_count integer, requeued_count integer)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            bounded_limit integer := greatest(1, least(p_limit, 100));
            matched integer;
        BEGIN
            IF current_setting('app.is_superadmin', true)
                IS DISTINCT FROM 'true' THEN
                RAISE EXCEPTION 'superadmin context required';
            END IF;

            IF NOT p_execute THEN
                SELECT least(count(*), bounded_limit)::integer
                INTO matched
                FROM crm_lead_outbox
                WHERE status = 'dead';
                RETURN QUERY SELECT matched, 0;
                RETURN;
            END IF;

            WITH candidates AS (
                SELECT id
                FROM crm_lead_outbox
                WHERE status = 'dead'
                ORDER BY terminal_at, created_at, id
                LIMIT bounded_limit
                FOR UPDATE SKIP LOCKED
            ), changed AS (
                UPDATE crm_lead_outbox AS outbox
                SET status = 'pending',
                    attempt_count = 0,
                    next_attempt_at = NULL,
                    claimed_at = NULL,
                    claim_token = NULL,
                    terminal_at = NULL,
                    delivered_at = NULL,
                    last_status_code = NULL,
                    last_error_category = 'operator_requeue',
                    updated_at = now()
                FROM candidates
                WHERE outbox.id = candidates.id
                RETURNING outbox.id
            )
            SELECT count(*)::integer INTO matched FROM changed;
            RETURN QUERY SELECT matched, matched;
        END;
        $$
        """
    )
    _revoke_and_grant("crm_requeue_dead_lead_outbox(integer, boolean)")


def downgrade() -> None:
    # A schema rollback must never silently erase accepted lead deliveries.
    # Operators must first export/archive the outbox and explicitly clear it.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.crm_lead_outbox') IS NOT NULL
                AND EXISTS (SELECT 1 FROM crm_lead_outbox) THEN
                RAISE EXCEPTION
                    '0094 downgrade blocked: archive and clear crm_lead_outbox first';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "crm_requeue_dead_lead_outbox(integer, boolean)"
    )
    op.execute("DROP FUNCTION IF EXISTS crm_lead_outbox_summary()")
    op.execute("DROP FUNCTION IF EXISTS crm_due_lead_outbox(integer)")
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "crm_finalize_lead_outbox(uuid, uuid, text, integer, text)"
    )
    op.execute("DROP FUNCTION IF EXISTS crm_claim_lead_outbox(uuid)")
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "crm_enqueue_tenant_lead_outbox(uuid, uuid, jsonb)"
    )

    # Restore the exact bounded 0091 behavior before removing the outbox table.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION insert_public_tenant_lead(
            p_company_name text,
            p_contact_name text,
            p_email text,
            p_phone text,
            p_employee_count_range text,
            p_preferred_language text,
            p_intent text,
            p_message text
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            created_id uuid;
        BEGIN
            PERFORM set_config('app.public_lead_insert', 'true', true);
            INSERT INTO tenant_leads (
                id, tenant_id, company_name, contact_name, email, phone,
                employee_count_range, preferred_language, intent, status,
                source, message
            )
            VALUES (
                gen_random_uuid(), NULL, p_company_name, p_contact_name,
                p_email, p_phone, p_employee_count_range,
                p_preferred_language, p_intent, 'lead_submitted',
                'landing_form', p_message
            )
            RETURNING id INTO created_id;
            RETURN created_id;
        END;
        $$
        """
    )
    _revoke_and_grant(PUBLIC_LEAD_FUNCTION_8)
    op.execute(f"DROP FUNCTION IF EXISTS {PUBLIC_LEAD_FUNCTION_9}")
    op.execute("DROP TABLE crm_lead_outbox")
