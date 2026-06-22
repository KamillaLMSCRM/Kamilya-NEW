-- RLS: Enable on tenant-scoped tables (final — no position_courses)
DO $$
DECLARE
  tbl TEXT;
  tables TEXT[] := ARRAY[
    'users', 'user_roles', 'user_sessions', 'courses', 'modules',
    'lessons', 'quizzes', 'quiz_attempts', 'enrollments', 'progress',
    'documents', 'positions', 'certificates',
    'ai_jobs', 'generated_content', 'audit_logs', 'tenants', 'tenant_settings'
  ];
BEGIN
  FOREACH tbl IN ARRAY tables LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', tbl);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_tenant())',
      tbl
    );
    RAISE NOTICE 'RLS enabled on %', tbl;
  END LOOP;
END $$;
