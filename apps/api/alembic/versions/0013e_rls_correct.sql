-- RLS: Enable on ALL 16 tenant-scoped tables
DO $$
DECLARE
  tbl TEXT;
  tables TEXT[] := ARRAY[
    'users', 'user_roles', 'user_sessions', 'courses', 'modules',
    'lessons', 'quizzes', 'quiz_attempts', 'enrollments', 'progress',
    'documents', 'positions', 'certificates', 'ai_jobs',
    'generated_content', 'audit_logs', 'tenants', 'tenant_settings'
  ];
  has_tenant BOOLEAN;
BEGIN
  FOREACH tbl IN ARRAY tables LOOP
    -- Check if table has tenant_id
    SELECT EXISTS(
      SELECT 1 FROM information_schema.columns
      WHERE table_schema='public' AND table_name=tbl AND column_name='tenant_id'
    ) INTO has_tenant;

    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', tbl);

    IF has_tenant THEN
      EXECUTE format(
        'CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_tenant())',
        tbl
      );
      RAISE NOTICE 'RLS tenant_isolation on %', tbl;
    ELSE
      EXECUTE format(
        'CREATE POLICY service_access ON %I USING (true)',
        tbl
      );
      RAISE NOTICE 'RLS service_access (permissive) on %', tbl;
    END IF;
  END LOOP;
END $$;
