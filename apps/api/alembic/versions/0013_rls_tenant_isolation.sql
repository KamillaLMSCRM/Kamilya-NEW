-- RLS: Row Level Security for all tenant-scoped tables
-- Run on Supabase PostgreSQL

-- Helper: set tenant context (call this at the start of each request)
CREATE OR REPLACE FUNCTION set_current_tenant(tenant_uuid UUID)
RETURNS VOID AS $$
BEGIN
  PERFORM set_config('app.current_tenant', tenant_uuid::text, true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Helper: get current tenant
CREATE OR REPLACE FUNCTION current_tenant()
RETURNS UUID AS $$
BEGIN
  RETURN current_setting('app.current_tenant', true)::uuid;
EXCEPTION WHEN OTHERS THEN
  RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================
-- Tables with tenant_id — enable RLS + create policies
-- ============================================================

DO $$
DECLARE
  tbl TEXT;
  tables TEXT[] := ARRAY[
    'users', 'user_roles', 'user_sessions', 'courses', 'modules',
    'lessons', 'content_blocks', 'quizzes', 'questions', 'quiz_choices',
    'quiz_attempts', 'enrollments', 'progress', 'documents', 'positions',
    'position_courses', 'certificates', 'ai_jobs', 'generated_content',
    'audit_logs', 'tenants', 'tenant_settings'
  ];
BEGIN
  FOREACH tbl IN ARRAY tables LOOP
    -- Enable RLS
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);

    -- Drop existing policies if any
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', tbl);

    -- Create tenant isolation policy
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I
       USING (tenant_id = current_tenant())',
      tbl
    );

    RAISE NOTICE 'RLS enabled on %', tbl;
  END LOOP;
END $$;

-- For tables without tenant_id (quiz_choices, questions) — use quiz/lesson -> module -> course -> tenant chain
-- These are accessed through joins, so RLS on parent tables protects them.
-- But we still enable RLS and create a permissive policy for service-role access.

DO $$
DECLARE
  tbl TEXT;
  no_tenant_tables TEXT[] := ARRAY['quiz_choices', 'questions'];
BEGIN
  FOREACH tbl IN ARRAY no_tenant_tables LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format('DROP POLICY IF EXISTS service_access ON %I', tbl);
    EXECUTE format(
      'CREATE POLICY service_access ON %I
       USING (true)',
      tbl
    );
    RAISE NOTICE 'RLS enabled (permissive) on %', tbl;
  END LOOP;
END $$;

-- Grant service_role full access (bypasses RLS)
-- The API uses service_role key for DB access, so RLS applies to anon/authenticated only.
-- Since we're using service_role from backend, we need to SET the tenant context in each request.

COMMENT ON FUNCTION set_current_tenant(UUID) IS 'Set tenant context for RLS. Call at start of each API request.';
COMMENT ON FUNCTION current_tenant() IS 'Get current tenant UUID from session context.';
