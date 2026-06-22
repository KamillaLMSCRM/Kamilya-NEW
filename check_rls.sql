SELECT tablename, rowsecurity, (SELECT count(*) FROM pg_policies WHERE pg_policies.tablename = pg_tables.tablename) as policy_count FROM pg_tables WHERE schemaname='public' ORDER BY tablename;
