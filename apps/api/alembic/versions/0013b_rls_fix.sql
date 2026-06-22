-- RLS fix: drop policies on tables without tenant_id, re-enable with correct policies

-- Tables that do NOT have tenant_id — use permissive policy (accessed via joins)
DO $$
DECLARE
  tbl TEXT;
  no_tenant_tables TEXT[] := ARRAY[
    'content_blocks', 'quiz_choices', 'questions'
  ];
BEGIN
  FOREACH tbl IN ARRAY no_tenant_tables LOOP
    -- Drop the broken tenant_isolation policy if it exists
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', tbl);
    -- Create permissive policy instead
    EXECUTE format('DROP POLICY IF EXISTS service_access ON %I', tbl);
    EXECUTE format(
      'CREATE POLICY service_access ON %I USING (true)',
      tbl
    );
    RAISE NOTICE 'RLS policy fixed (permissive) on %', tbl;
  END LOOP;
END $$;
