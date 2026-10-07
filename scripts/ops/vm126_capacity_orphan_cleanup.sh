#!/usr/bin/env bash
# kamilya-target: vm126
# kamilya-mode: mutation
# kamilya-correlation: CAPACITY-ORPHAN-20261007
# kamilya-output: sanitized
set -Eeuo pipefail
# Owner approved this exact owned row; no tenant-wide or generic cleanup.
test "$(hostname)" = kml
source /etc/kamilya-release-plane/ct125.env
test "$CT125_HOST" = 192.168.1.225
test "$CT125_IDENTITY_FILE" = /root/.ssh/kamilya_ct125_ed25519
test "$CT125_KNOWN_HOSTS" = /root/.ssh/known_hosts.ct125
ssh -T -i "$CT125_IDENTITY_FILE" -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$CT125_KNOWN_HOSTS" "root@$CT125_HOST" bash -se -- "$CT125_DB_NAME" <<'CTMAINT'
set -Eeuo pipefail
test "$(hostname)" = KML-1-77
runuser -u postgres -- psql -d "$1" -v ON_ERROR_STOP=1 -Atq <<'SQL'
BEGIN;
SET LOCAL lock_timeout='3s';
SET LOCAL statement_timeout='30s';
DO $$
DECLARE
    target_id CONSTANT uuid := 'cd94db33-6968-4198-bf9e-406af0713cb3';
    target_tenant CONSTANT uuid := '34aeb387-7009-49c8-88e9-a19ff76f1b64';
    candidate public.positions%ROWTYPE;
    reference record;
    reference_count bigint;
    affected integer;
BEGIN
    IF (SELECT version_num FROM public.alembic_version) <> '0178' THEN
        RAISE EXCEPTION 'schema_identity_refused';
    END IF;
    IF EXISTS(SELECT 1 FROM public.tenants WHERE id=target_tenant) THEN
        RAISE EXCEPTION 'tenant_still_exists';
    END IF;
    SELECT * INTO STRICT candidate FROM public.positions WHERE id=target_id FOR UPDATE;
    IF candidate.tenant_id<>target_tenant OR candidate.name<>'Capacity QA no automatic assignments'
       OR (SELECT count(*) FROM public.positions WHERE tenant_id=target_tenant)<>1 THEN
        RAISE EXCEPTION 'exact_orphan_identity_refused';
    END IF;
    -- Check both declared FK columns and conventional position_id columns,
    -- including soft references. Restrict every count to this exact UUID.
    FOR reference IN
        SELECT DISTINCT ns.nspname AS schema_name,c.relname AS table_name,a.attname AS column_name
        FROM pg_catalog.pg_constraint fk
        JOIN pg_catalog.pg_class c ON c.oid=fk.conrelid
        JOIN pg_catalog.pg_namespace ns ON ns.oid=c.relnamespace
        JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid AND a.attnum=ANY(fk.conkey)
        WHERE fk.contype='f' AND fk.confrelid='public.positions'::regclass
        UNION
        SELECT table_schema,table_name,column_name FROM information_schema.columns
        WHERE table_schema='public' AND column_name LIKE '%position_id' AND udt_name='uuid'
    LOOP
        EXECUTE format('SELECT count(*) FROM %I.%I WHERE %I=$1',
                       reference.schema_name,reference.table_name,reference.column_name)
            INTO reference_count USING target_id;
        IF reference_count<>0 THEN RAISE EXCEPTION 'owned_position_referenced'; END IF;
    END LOOP;
    DELETE FROM public.positions
    WHERE id=target_id AND tenant_id=target_tenant AND name='Capacity QA no automatic assignments';
    GET DIAGNOSTICS affected=ROW_COUNT;
    IF affected<>1 THEN RAISE EXCEPTION 'exact_delete_count_refused'; END IF;
END $$;
COMMIT;
BEGIN READ ONLY;
SELECT 'EVIDENCE|owned_position_rows='||count(*) FROM public.positions
WHERE id='cd94db33-6968-4198-bf9e-406af0713cb3' OR tenant_id='34aeb387-7009-49c8-88e9-a19ff76f1b64';
SELECT 'EVIDENCE|owned_tenant_rows='||count(*) FROM public.tenants
WHERE id='34aeb387-7009-49c8-88e9-a19ff76f1b64';
ROLLBACK;
SQL
CTMAINT
