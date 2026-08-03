"""Add tenant-scoped training-evidence retention policies and controlled purge.

Revision ID: 0088
Revises: 0087
"""

from alembic import op

revision = "0088"
down_revision = "0087"
branch_labels = None
depends_on = None

TENANT_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
PURGE_TOKEN = "PURGE_TRAINING_EVIDENCE"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE training_retention_policies (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
            procedure_type text NOT NULL CHECK (
                procedure_type IN ('acknowledgement', 'training', 'knowledge_check', 'internal_attestation', 'admission_decision')
            ),
            retention_days integer NOT NULL CHECK (retention_days BETWEEN 1 AND 36500),
            legal_basis text,
            local_basis text,
            active boolean NOT NULL DEFAULT false,
            created_by_user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            updated_by_user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_training_retention_policies_tenant_procedure UNIQUE (tenant_id, procedure_type),
            CONSTRAINT ck_training_retention_policies_active_basis CHECK (
                NOT active OR NULLIF(btrim(legal_basis), '') IS NOT NULL OR NULLIF(btrim(local_basis), '') IS NOT NULL
            )
        )
        """
    )
    op.execute("CREATE INDEX ix_training_retention_policies_tenant_id ON training_retention_policies (tenant_id)")
    op.execute("CREATE INDEX ix_training_retention_policies_tenant_active ON training_retention_policies (tenant_id, active)")
    op.execute("ALTER TABLE training_retention_policies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE training_retention_policies FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_training_retention_policies_isolation ON training_retention_policies "
        f"FOR ALL TO lms_app USING ({TENANT_EXPR}) WITH CHECK ({TENANT_EXPR})"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON training_retention_policies TO lms_app")

    # Advance a tenant-scoped cursor after every bounded call. This prevents
    # permanent blockers among the oldest roots from hiding younger eligible
    # chains forever across repeated purge calls.
    op.execute(
        """
        CREATE TABLE training_evidence_retention_cursors (
            tenant_id uuid PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
            last_occurred_at timestamptz,
            last_root_id uuid,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_training_evidence_retention_cursor_pair CHECK (
                (last_occurred_at IS NULL AND last_root_id IS NULL)
                OR (last_occurred_at IS NOT NULL AND last_root_id IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_training_evidence_retention_cursors_updated "
        "ON training_evidence_retention_cursors (updated_at)"
    )
    op.execute("ALTER TABLE training_evidence_retention_cursors ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE training_evidence_retention_cursors FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_training_evidence_retention_cursors_isolation "
        f"ON training_evidence_retention_cursors FOR ALL TO lms_app "
        f"USING ({TENANT_EXPR}) WITH CHECK ({TENANT_EXPR})"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON training_evidence_retention_cursors TO lms_app")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_training_retention_policy_ownership()
        RETURNS trigger AS $$
        DECLARE creator_tenant uuid;
        DECLARE updater_tenant uuid;
        BEGIN
            SELECT tenant_id INTO creator_tenant FROM users WHERE id = NEW.created_by_user_id;
            SELECT tenant_id INTO updater_tenant FROM users WHERE id = NEW.updated_by_user_id;
            IF creator_tenant IS NULL OR creator_tenant <> NEW.tenant_id
               OR updater_tenant IS NULL OR updater_tenant <> NEW.tenant_id THEN
                RAISE EXCEPTION 'Retention policy actors must belong to the same tenant'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER training_retention_policies_validate_ownership
        BEFORE INSERT OR UPDATE ON training_retention_policies
        FOR EACH ROW EXECUTE FUNCTION validate_training_retention_policy_ownership();
        """
    )

    # The helper is intentionally not SECURITY DEFINER. It is only used by
    # append-only triggers, and checks that the caller is the owner of the
    # controlled purge function before allowing a delete.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION training_evidence_retention_purge_authorized()
        RETURNS boolean AS $$
        BEGIN
            RETURN current_setting('app.training_evidence_retention_purge', true) = 'true'
               AND current_user = (
                   SELECT pg_get_userbyid(proowner)
                   FROM pg_proc
                   WHERE oid = 'purge_training_evidence_chains(uuid,text,boolean,integer)'::regprocedure
               );
        END;
        $$ LANGUAGE plpgsql STABLE SET search_path = public, pg_temp;
        """
    )

    # Normal lms_app UPDATE/DELETE operations remain rejected. Only the
    # security-definer purge function can set the owner-checked transaction flag.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_training_evidence_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND training_evidence_retention_purge_authorized() THEN
                RETURN OLD;
            END IF;
            IF TG_OP = 'DELETE' AND EXISTS (
                SELECT 1 FROM training_evidence_legal_holds h
                WHERE h.event_id = OLD.id AND h.action = 'placed'
                  AND NOT EXISTS (
                    SELECT 1 FROM training_evidence_legal_holds r
                    WHERE r.event_id = OLD.id AND r.action = 'released' AND r.occurred_at > h.occurred_at
                  )
            ) THEN
                RAISE EXCEPTION 'Legal hold blocks deletion of training evidence' USING ERRCODE = 'check_violation';
            END IF;
            RAISE EXCEPTION 'Training evidence events are append-only' USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql SET search_path = public, pg_temp;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_training_evidence_confirmation_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND training_evidence_retention_purge_authorized() THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'Step-up confirmations are append-only' USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql SET search_path = public, pg_temp;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_training_evidence_hold_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND training_evidence_retention_purge_authorized() THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'Legal hold records are append-only' USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql SET search_path = public, pg_temp;
        """
    )

    # This is the only controlled deletion entry point. Tenant context, fixed
    # confirmation token and bounded root count are checked inside the function.
    op.execute(
        f"""
        CREATE FUNCTION purge_training_evidence_chains(
            p_tenant_id uuid,
            p_confirmation_token text,
            p_dry_run boolean DEFAULT true,
            p_max_roots integer DEFAULT 100
        )
        RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            root record;
            chain_count integer;
            chain_latest timestamptz;
            active_hold boolean;
            active_share boolean;
            cutoff timestamptz;
            deleted_count integer;
            deleted_this_chain integer;
            deleted_this_pass integer;
            candidate_count integer := 0;
            scan_budget integer := 0;
            cursor_occurred_at timestamptz;
            cursor_root_id uuid;
            last_scanned_occurred_at timestamptz;
            last_scanned_root_id uuid;
            roots_scanned integer := 0;
            eligible_roots integer := 0;
            purged_roots integer := 0;
            purged_events integer := 0;
            purged_confirmations integer := 0;
            purged_hold_history integer := 0;
            purged_shares integer := 0;
            reason_active_hold integer := 0;
            reason_newer_chain integer := 0;
            reason_active_share integer := 0;
            truncated boolean := false;
        BEGIN
            IF NULLIF(current_setting('app.tenant_id', true), '')::uuid IS DISTINCT FROM p_tenant_id THEN
                RAISE EXCEPTION 'Retention purge tenant context mismatch' USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF p_confirmation_token IS DISTINCT FROM '{PURGE_TOKEN}' THEN
                RAISE EXCEPTION 'Invalid retention purge confirmation token' USING ERRCODE = 'invalid_parameter_value';
            END IF;
            IF p_max_roots < 1 OR p_max_roots > 100 THEN
                RAISE EXCEPTION 'Retention purge root limit must be between 1 and 100' USING ERRCODE = 'invalid_parameter_value';
            END IF;

            CREATE TEMP TABLE IF NOT EXISTS retention_chain_ids (id uuid PRIMARY KEY) ON COMMIT DROP;
            CREATE TEMP TABLE IF NOT EXISTS retention_share_ids (id uuid PRIMARY KEY) ON COMMIT DROP;
            CREATE TEMP TABLE IF NOT EXISTS retention_root_candidates (
                id uuid PRIMARY KEY,
                procedure_type text NOT NULL,
                retention_days integer NOT NULL,
                occurred_at timestamptz NOT NULL,
                pass_no integer NOT NULL
            ) ON COMMIT DROP;
            TRUNCATE retention_chain_ids, retention_share_ids, retention_root_candidates;

            INSERT INTO training_evidence_retention_cursors (tenant_id)
            VALUES (p_tenant_id)
            ON CONFLICT (tenant_id) DO NOTHING;
            SELECT last_occurred_at, last_root_id
            INTO cursor_occurred_at, cursor_root_id
            FROM training_evidence_retention_cursors
            WHERE tenant_id = p_tenant_id
            FOR UPDATE;

            -- Scan more candidates than we can delete, but never beyond the
            -- fixed upper bound. This lets blocked old roots stop consuming
            -- the deletion budget while keeping one purge call predictable.
            scan_budget := LEAST(p_max_roots * 10, 1000);
            INSERT INTO retention_root_candidates (id, procedure_type, retention_days, occurred_at, pass_no)
            WITH active_roots AS (
                SELECT e.id, e.procedure_type, p.retention_days, e.occurred_at
                FROM training_evidence_events e
                JOIN training_retention_policies p
                  ON p.tenant_id = e.tenant_id
                 AND p.procedure_type = e.procedure_type
                 AND p.active = true
                WHERE e.tenant_id = p_tenant_id
                  AND e.record_type = 'original'
                  AND e.related_event_id IS NULL
            ), ordered_roots AS (
                SELECT id, procedure_type, retention_days, occurred_at, 0 AS pass_no
                FROM active_roots
                WHERE cursor_occurred_at IS NULL
                   OR (occurred_at, id) > (cursor_occurred_at, cursor_root_id)
                UNION ALL
                SELECT id, procedure_type, retention_days, occurred_at, 1 AS pass_no
                FROM active_roots
                WHERE cursor_occurred_at IS NOT NULL
                  AND (occurred_at, id) <= (cursor_occurred_at, cursor_root_id)
            )
            SELECT id, procedure_type, retention_days, occurred_at, pass_no
            FROM ordered_roots
            ORDER BY pass_no ASC, occurred_at ASC, id ASC
            LIMIT scan_budget + 1;
            SELECT count(*) INTO candidate_count FROM retention_root_candidates;

            FOR root IN
                SELECT id, procedure_type, retention_days, occurred_at
                FROM retention_root_candidates
                ORDER BY pass_no ASC, occurred_at ASC, id ASC
            LOOP
                EXIT WHEN roots_scanned >= scan_budget OR eligible_roots >= p_max_roots;
                roots_scanned := roots_scanned + 1;
                last_scanned_occurred_at := root.occurred_at;
                last_scanned_root_id := root.id;

                TRUNCATE retention_chain_ids;
                INSERT INTO retention_chain_ids (id)
                WITH RECURSIVE chain AS (
                    SELECT e.id
                    FROM training_evidence_events e
                    WHERE e.id = root.id AND e.tenant_id = p_tenant_id
                    UNION
                    SELECT child.id
                    FROM training_evidence_events child
                    JOIN chain parent ON child.related_event_id = parent.id
                    WHERE child.tenant_id = p_tenant_id
                )
                SELECT id FROM chain;

                cutoff := now() - make_interval(days => root.retention_days);
                SELECT count(*), max(e.occurred_at),
                       EXISTS (
                           SELECT 1 FROM training_evidence_legal_holds h
                           WHERE h.tenant_id = p_tenant_id
                             AND h.event_id IN (SELECT id FROM retention_chain_ids)
                             AND h.action = 'placed'
                             AND NOT EXISTS (
                                 SELECT 1 FROM training_evidence_legal_holds r
                                 WHERE r.tenant_id = p_tenant_id
                                   AND r.event_id = h.event_id
                                   AND r.action = 'released'
                                   AND r.occurred_at > h.occurred_at
                             )
                       ),
                       EXISTS (
                           SELECT 1 FROM training_evidence_shares s
                           WHERE s.tenant_id = p_tenant_id
                             AND s.revoked_at IS NULL
                             AND s.expires_at > now()
                             AND jsonb_typeof(s.source_event_ids) = 'array'
                             AND EXISTS (
                                 SELECT 1 FROM jsonb_array_elements_text(s.source_event_ids) source_id
                                 WHERE source_id IN (SELECT id::text FROM retention_chain_ids)
                             )
                       )
                INTO chain_count, chain_latest, active_hold, active_share
                FROM training_evidence_events e
                WHERE e.id IN (SELECT id FROM retention_chain_ids);

                IF active_hold THEN
                    reason_active_hold := reason_active_hold + 1;
                    CONTINUE;
                END IF;
                IF active_share THEN
                    reason_active_share := reason_active_share + 1;
                    CONTINUE;
                END IF;
                IF chain_latest IS NULL OR chain_latest >= cutoff THEN
                    reason_newer_chain := reason_newer_chain + 1;
                    CONTINUE;
                END IF;

                eligible_roots := eligible_roots + 1;

                -- An expired or revoked share is part of the retained package.
                -- Queue it before deleting events so package_bytes cannot outlive
                -- the evidence chain. Active shares were already a hard block.
                INSERT INTO retention_share_ids (id)
                SELECT s.id
                FROM training_evidence_shares s
                WHERE s.tenant_id = p_tenant_id
                  AND (s.revoked_at IS NOT NULL OR s.expires_at <= now())
                  AND jsonb_typeof(s.source_event_ids) = 'array'
                  AND EXISTS (
                      SELECT 1 FROM jsonb_array_elements_text(s.source_event_ids) source_id
                      WHERE source_id IN (SELECT id::text FROM retention_chain_ids)
                  )
                ON CONFLICT (id) DO NOTHING;

                IF p_dry_run THEN
                    CONTINUE;
                END IF;

                PERFORM set_config('app.training_evidence_retention_purge', 'true', true);
                DELETE FROM training_evidence_shares
                WHERE tenant_id = p_tenant_id AND id IN (SELECT id FROM retention_share_ids);
                GET DIAGNOSTICS deleted_count = ROW_COUNT;
                purged_shares := purged_shares + deleted_count;

                DELETE FROM training_evidence_step_up_confirmations
                WHERE tenant_id = p_tenant_id AND event_id IN (SELECT id FROM retention_chain_ids);
                GET DIAGNOSTICS deleted_count = ROW_COUNT;
                purged_confirmations := purged_confirmations + deleted_count;

                DELETE FROM training_evidence_legal_holds
                WHERE tenant_id = p_tenant_id AND event_id IN (SELECT id FROM retention_chain_ids);
                GET DIAGNOSTICS deleted_count = ROW_COUNT;
                purged_hold_history := purged_hold_history + deleted_count;

                deleted_this_chain := 0;
                LOOP
                    -- The self-reference is ON DELETE RESTRICT. Delete leaves
                    -- first, then their parents, while the purge authorization
                    -- trigger remains active for every row.
                    DELETE FROM training_evidence_events e
                    WHERE e.tenant_id = p_tenant_id
                      AND e.id IN (SELECT id FROM retention_chain_ids)
                      AND NOT EXISTS (
                          SELECT 1
                          FROM training_evidence_events child
                          WHERE child.tenant_id = p_tenant_id
                            AND child.related_event_id = e.id
                            AND child.id IN (SELECT id FROM retention_chain_ids)
                      );
                    GET DIAGNOSTICS deleted_this_pass = ROW_COUNT;
                    deleted_this_chain := deleted_this_chain + deleted_this_pass;
                    purged_events := purged_events + deleted_this_pass;
                    EXIT WHEN deleted_this_pass = 0;
                END LOOP;
                IF deleted_this_chain <> chain_count THEN
                    RAISE EXCEPTION 'Retention chain could not be fully reduced' USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                purged_roots := purged_roots + 1;
            END LOOP;

            IF roots_scanned > 0 THEN
                UPDATE training_evidence_retention_cursors
                SET last_occurred_at = last_scanned_occurred_at,
                    last_root_id = last_scanned_root_id,
                    updated_at = now()
                WHERE tenant_id = p_tenant_id;
            END IF;

            -- candidate_count includes one sentinel row when the bounded
            -- candidate query found more work than this call was allowed to
            -- inspect. It also stays true when the deletion cap stopped the
            -- loop before all candidates were evaluated.
            truncated := candidate_count > roots_scanned;

            IF p_dry_run THEN
                SELECT count(*) INTO purged_shares FROM retention_share_ids;
            END IF;

            RETURN jsonb_build_object(
                'dry_run', p_dry_run,
                'scan_budget', scan_budget,
                'roots_scanned', roots_scanned,
                'truncated', truncated,
                'eligible_roots', eligible_roots,
                'purged_roots', purged_roots,
                'purged_events', purged_events,
                'purged_confirmations', purged_confirmations,
                'purged_hold_history', purged_hold_history,
                'purged_shares', purged_shares,
                'reason_counts', jsonb_build_object(
                    'active_legal_hold', reason_active_hold,
                    'newer_chain_event', reason_newer_chain,
                    'active_external_share', reason_active_share
                )
            );
        END;
        $$;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION purge_training_evidence_chains(uuid, text, boolean, integer) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION purge_training_evidence_chains(uuid, text, boolean, integer) TO lms_app")


def downgrade() -> None:
    # Restore the fail-closed append-only trigger bodies before dropping the
    # retention-only authorization helper.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_training_evidence_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND EXISTS (
                SELECT 1 FROM training_evidence_legal_holds h
                WHERE h.event_id = OLD.id AND h.action = 'placed'
                  AND NOT EXISTS (
                    SELECT 1 FROM training_evidence_legal_holds r
                    WHERE r.event_id = OLD.id AND r.action = 'released' AND r.occurred_at > h.occurred_at
                  )
            ) THEN
                RAISE EXCEPTION 'Legal hold blocks deletion of training evidence' USING ERRCODE = 'check_violation';
            END IF;
            RAISE EXCEPTION 'Training evidence events are append-only' USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_training_evidence_confirmation_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Step-up confirmations are append-only' USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_training_evidence_hold_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Legal hold records are append-only' USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION purge_training_evidence_chains(uuid, text, boolean, integer) FROM PUBLIC")
    op.execute("DROP FUNCTION IF EXISTS purge_training_evidence_chains(uuid, text, boolean, integer)")
    op.execute("DROP FUNCTION IF EXISTS training_evidence_retention_purge_authorized()")
    op.execute(
        "DROP POLICY IF EXISTS tenant_training_evidence_retention_cursors_isolation "
        "ON training_evidence_retention_cursors"
    )
    op.execute("DROP INDEX IF EXISTS ix_training_evidence_retention_cursors_updated")
    op.execute("DROP TABLE IF EXISTS training_evidence_retention_cursors")
    op.execute("DROP TRIGGER IF EXISTS training_retention_policies_validate_ownership ON training_retention_policies")
    op.execute("DROP FUNCTION IF EXISTS validate_training_retention_policy_ownership()")
    op.execute("DROP POLICY IF EXISTS tenant_training_retention_policies_isolation ON training_retention_policies")
    op.execute("DROP INDEX IF EXISTS ix_training_retention_policies_tenant_active")
    op.execute("DROP INDEX IF EXISTS ix_training_retention_policies_tenant_id")
    op.execute("DROP TABLE IF EXISTS training_retention_policies")
